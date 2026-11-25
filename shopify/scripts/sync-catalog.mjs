#!/usr/bin/env node
/**
 * Sincroniza catalog/products.json con Shopify (Admin GraphQL). Por defecto DRY-RUN: no llama a Shopify.
 *   node scripts/sync-catalog.mjs                 # valida y muestra qué haría
 *   node scripts/sync-catalog.mjs --promo-starter # Starter a 99 € (tachado 149 €)
 *   SHOPIFY_SHOP_DOMAIN=x.myshopify.com SHOPIFY_ADMIN_TOKEN=shpat_... node scripts/sync-catalog.mjs --apply
 * Idempotente por SKU (si existe un producto con ese SKU, se actualiza; no se duplica).
 * ESTADO: lógica de validación probada en dry-run; las llamadas a Shopify NO se han probado contra una tienda real.
 */
import { readFileSync } from "node:fs";
const API_VERSION = "2025-10";
const args = new Set(process.argv.slice(2));
const catalog = JSON.parse(readFileSync(new URL("../catalog/products.json", import.meta.url), "utf8"));

export function buildPlan(cat, { promoStarter = false } = {}) {
  const errors = [];
  const seen = new Set();
  const items = cat.products.map((p) => {
    if (!/^[a-z0-9_]+$/.test(p.sku)) errors.push(`SKU inválido: ${p.sku}`);
    if (seen.has(p.sku)) errors.push(`SKU duplicado: ${p.sku}`);
    seen.add(p.sku);
    if (!/^\d+\.\d{2}$/.test(p.price) || Number(p.price) <= 0) errors.push(`${p.sku}: precio inválido (${p.price})`);
    const promo = promoStarter && p.promo ? p.promo : null;
    return { ...p, price: promo?.price ?? p.price, compareAtPrice: promo?.compareAtPrice ?? p.compareAtPrice };
  });
  return { errors, items };
}

async function gql(query, variables) {
  const r = await fetch(`https://${process.env.SHOPIFY_SHOP_DOMAIN}/admin/api/${API_VERSION}/graphql.json`, {
    method: "POST", headers: { "content-type": "application/json", "x-shopify-access-token": process.env.SHOPIFY_ADMIN_TOKEN },
    body: JSON.stringify({ query, variables }),
  });
  const j = await r.json();
  if (!r.ok || j.errors) throw new Error(JSON.stringify(j.errors ?? j));
  return j.data;
}
const must = (payload, key) => { const e = payload?.[key]?.userErrors; if (e?.length) throw new Error(`${key}: ${JSON.stringify(e)}`); return payload[key]; };

async function apply(items) {
  if (!process.env.SHOPIFY_SHOP_DOMAIN || !process.env.SHOPIFY_ADMIN_TOKEN) throw new Error("Faltan SHOPIFY_SHOP_DOMAIN y SHOPIFY_ADMIN_TOKEN");
  const g = catalog.sellingPlanGroup;
  const productIds = [];
  for (const p of items) {
    const found = await gql(`query($q:String!){ productVariants(first:1, query:$q){ nodes{ id product{ id } } } }`, { q: `sku:${p.sku}` });
    let node = found.productVariants.nodes[0];
    if (!node) {
      const created = must(await gql(`mutation($p:ProductCreateInput!){ productCreate(product:$p){ product{ id variants(first:1){ nodes{ id } } } userErrors{ field message } } }`,
        { p: { title: p.title, descriptionHtml: p.descriptionHtml, tags: p.tags, status: "DRAFT", productOptions: [{ name: "Plan", values: [{ name: "Mensual" }] }] } }), "productCreate");
      node = { id: created.product.variants.nodes[0].id, product: { id: created.product.id } };
    } else {
      must(await gql(`mutation($p:ProductUpdateInput!){ productUpdate(product:$p){ product{ id } userErrors{ field message } } }`, { p: { id: node.product.id, title: p.title, descriptionHtml: p.descriptionHtml, tags: p.tags } }), "productUpdate");
    }
    must(await gql(`mutation($pid:ID!,$v:[ProductVariantsBulkInput!]!){ productVariantsBulkUpdate(productId:$pid, variants:$v){ userErrors{ field message } } }`,
      { pid: node.product.id, v: [{ id: node.id, price: p.price, compareAtPrice: p.compareAtPrice, inventoryItem: { sku: p.sku, tracked: false, requiresShipping: false } }] }), "productVariantsBulkUpdate");
    productIds.push(node.product.id);
    console.log(`✔ ${p.sku} → ${node.product.id} (${p.price} €${p.compareAtPrice ? `, antes ${p.compareAtPrice} €` : ""}) [DRAFT: publícalo tú tras revisar]`);
  }
  const grp = must(await gql(`mutation($i:SellingPlanGroupInput!,$r:SellingPlanGroupResourceInput){ sellingPlanGroupCreate(input:$i, resources:$r){ sellingPlanGroup{ id } userErrors{ field message } } }`,
    { i: { name: g.name, merchantCode: g.merchantCode, options: [g.planName], sellingPlansToCreate: [{ name: g.planName, options: g.planName, category: "SUBSCRIPTION",
        billingPolicy: { recurring: { interval: g.interval, intervalCount: g.intervalCount } }, deliveryPolicy: { recurring: { interval: g.interval, intervalCount: g.intervalCount } }, pricingPolicies: [] }] },
      r: { productIds } }), "sellingPlanGroupCreate");
  console.log(`✔ Grupo de suscripción mensual: ${grp.sellingPlanGroup.id} (si ya existe uno con ese código, Shopify devolverá error: reutilízalo desde el admin)`);
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { errors, items } = buildPlan(catalog, { promoStarter: args.has("--promo-starter") });
  if (errors.length) { console.error("Catálogo inválido:\n- " + errors.join("\n- ")); process.exit(1); }
  for (const p of items) console.log(`${args.has("--apply") ? "APLICAR" : "DRY-RUN"} ${p.sku.padEnd(18)} ${p.price.padStart(8)} €/mes sin IVA${p.compareAtPrice ? ` (tachado ${p.compareAtPrice})` : ""} → colección ${p.collection}`);
  if (args.has("--apply")) { try { await apply(items); } catch (e) { console.error("ERROR:", e.message); process.exit(1); } } else console.log("\nDry-run: no se ha llamado a Shopify. Usa --apply con credenciales.");
}
