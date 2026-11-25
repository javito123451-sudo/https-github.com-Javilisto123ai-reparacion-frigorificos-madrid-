# Omnitech-Core Store (Shopify)

Tema Online Store 2.0 (`theme/`) + catálogo (`catalog/products.json`) + sincronizador (`scripts/sync-catalog.mjs`).
Shopify es el canal comercial; el motor sigue siendo Omnitech-Core (ver `docs/omnicommerce/`, repo `omnitech-core-v1`, rama `claude/omnicommerce-bridge`).

## Flujo comercial (decisión del propietario, 25-nov-2026)
**Primero se capta, un administrador autoriza, y solo entonces se puede contratar; la activación es manual tras el pago.**
1. El público solo ve «Solicitar contratación» (`/pages/solicitar`): el formulario envía la captación a `…/api/commerce-public/requests` (ajustes del tema → «URL de la API de captación»). No hay compra ni cobro.
2. En OmniCommerce Control → Captación, un SUPER_ADMIN autoriza plan, módulos y vigencia. Si hay credenciales, el cliente recibe la etiqueta `autorizado` en Shopify y el tema le muestra «Contratar».
3. El cliente autorizado compra; el pedido se enlaza a su autorización; un administrador activa.
**Honestidad sobre la barrera:** ocultar el botón es solo comodidad. La barrera real es del servidor: sin autorización vigente del mismo plan, la activación se rechaza y la compra queda señalada para reembolso. Para impedir el checkout directo haría falta una Shopify Function de validación de carrito (no incluida).

## Contenido
- **Tema** (identidad violeta/cian oscura configurable en *Personalizar tema*): Inicio, Plataforma, Soluciones, Módulos, Planes, Enterprise, Servicios, Solicitar contratación, Demo, Contacto, Producto, Carrito, 404. «Mi cuenta» usa las cuentas de cliente de Shopify (enlace en cabecera). Responsive (móvil primero), SEO (title/description/OG/JSON-LD Organization y Product), formularios con consentimiento RGPD obligatorio.
- **Módulos**: no se venden sueltos; la página Módulos es informativa. Mostrar precios de complemento = casilla en la sección (oculto por defecto).
- **Catálogo**: 3 planes de suscripción mensual (Starter 149 €, Professional 249 €, Enterprise 1.000 €, sin IVA). SKU = `commerce_products.code` (lo que el Bridge usa para mapear pedidos). Promo Starter 99 € con `--promo-starter` (y activarla también en OmniCommerce Control).

## Puesta en marcha (requiere acceso a la tienda)
1. Shopify admin → Ajustes → Impuestos: **precios sin IVA** (los precios se muestran «+ IVA»). Activa el cobro de IVA según tu configuración fiscal.
2. Crea la app personalizada (scopes: `write_products`, `write_selling_plan_groups` o equivalente, `read_orders`, `read_customers`, `read_own_subscription_contracts`) y obtén token y API secret.
3. `SHOPIFY_SHOP_DOMAIN=… SHOPIFY_ADMIN_TOKEN=… node scripts/sync-catalog.mjs --apply` (crea productos en BORRADOR + grupo de suscripción mensual). Revisa y publica; añade los productos a las colecciones `planes` y `enterprise` (el script no las crea).
4. `shopify theme push --path theme` (Shopify CLI) y crea las páginas `plataforma, soluciones, modulos, planes, enterprise, servicios, demo, contacto` (incluida `solicitar`) asignando su plantilla `page.<handle>`. Menú principal `main-menu`.
5. Webhooks hacia el Bridge: ver `PUESTA-EN-PRODUCCION.md` de `omnitech-core-v1`.
6. Suscripciones: requiere una pasarela compatible con Shopify Subscriptions; confirmar en tu plan.

## Estado verificado / no verificado
Verificado: JSON válido, sintaxis JS del formulario, plantillas→secciones existentes, balance de etiquetas Liquid, dry-run del sincronizador, precios y SKU idénticos a los del Bridge.
NO verificado: `shopify theme check`/render en tienda real (la descarga de la CLI fue bloqueada en este entorno), llamadas reales a la Admin API, checkout con suscripción, textos legales. Los textos de marketing son borradores basados en funciones reales del producto; revísalos.
Aviso: las propiedades de línea (email, empresa, aceptación) se guardan en el pedido, pero el Bridge aún no las lee para precargar la solicitud de activación (mejora pendiente).
