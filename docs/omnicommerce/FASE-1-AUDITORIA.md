# OmniCommerce / Omnitech-Core Store — Fase 1: Auditoría y diagnóstico de compatibilidad

Fecha: 2026-11-25 · Estado: **Fase 1 completada (solo lectura). No se ha modificado ningún sistema existente.**

## 1. Dónde vive realmente Omnitech-Core

Este repositorio (`...reparacion-frigorificos-madrid-`) está **vacío** (solo `README.md`). El proyecto está en otros repos de la misma cuenta:

| Repo | Visibilidad | Contenido | Último push |
|---|---|---|---|
| `omnitech-core-v1` | público | **SaaS principal** (886 ficheros): monorepo pnpm, API Express 5, front React/Vite, Drizzle/Postgres | 2026-11-21 |
| `OmniTech-Core` (clonado como `omnitech-core`) | privado | Versión anterior del mismo SaaS (546 ficheros) — **desfasada**, v1 es superconjunto | 2026-07-27 |
| `omnitech-core-info` | público | Web pública estática de marketing/precios (Vercel) | 2026-11-13 |

**Base de integración propuesta: `omnitech-core-v1`.**

## 2. Arquitectura detectada (omnitech-core-v1)

- **Monorepo pnpm** (Node 24, TS 5.9): `artifacts/api-server` (Express 5, bundle esbuild), `artifacts/omniflow` (React 19 + Vite + wouter + React Query), `lib/db` (Drizzle ORM), `lib/api-spec` (OpenAPI → Orval → `api-client-react` / `api-zod`).
- **Auth**: Clerk (`@clerk/express`). Roles de plataforma en `platform_roles` (`SUPER_ADMIN`, `STAFF_OMNITECH`) y `users.platform_role`.
- **Multiempresa / multiworkspace**: `organizations` (= workspace), `org_members` (owner/admin/member…), aislamiento por `org_id` en cada tabla, `org_invitations`.
- **Licencias y módulos**: `license_plans` (1 fila/org: plan, seats, valid_from/until, is_active, billing_cycle), `module_configs` (módulo on/off por org, único `(org_id, module_slug)`), plan→módulos en `auth.ts` (`PLAN_MODULES`), gating fail-closed (`requireModule`). La BD manda sobre el plan.
- **Control Center** (`routes/control-center.ts`, `pages/control-center/*`): Dashboard, Workspaces, Usuarios, Roles, Módulos, IA, Integraciones, Seguridad, Auditoría, Licencias, **Onboard Wizard** (10 pasos; crea workspace + licencia + módulos + admin). Protegido por `requireSuperAdmin`. Montado **antes** de `resolveOrg` (ojo: `req.userId` no existe ahí; hay `resolveUserId`).
- **Auditoría**: `audit_logs` + `utils/auditLogger.ts` (`logAudit`, `logAuditSystem`).
- **Omni Security Core**: slug `omni_security` (plan Business+), más informes `AUDITORIA_SEGURIDAD_OMNITECH.md`, `OmniTech_Security_Final_Report.md`.
- **Webhooks entrantes existentes** (patrón a reutilizar): WhatsApp con HMAC vía `rawBody` (`express.json({ verify })` en `app.ts`) y `META_APP_SECRET`; Telegram; outreach (Resend).
- **Email**: Resend (`lib/email.ts`, `sendEmail`). `RESEND_API_KEY` **sin configurar** en producción (`env-production.md`).
- **Créditos IA (OmniCredits)**: `credit_plans`, `credit_packs`, `credit_accounts`, `credit_ledger` (append-only con triggers). `purchaseService.ts` documenta "sin integración de pago (Stripe/Hotmart)".
- **Migraciones**: Drizzle (`lib/db/drizzle/0000…0017`) **y además** migraciones SQL de arranque (`utils/startupMigrations.ts`, FIX-A…FIX-AF). Convención vigente: tablas nuevas con SQL idempotente.
- **Tests**: Vitest en `api-server` (con BD real vía rama Neon desechable) y `smoke:deploy`.
- **Estado de calidad declarado**: `tsc --noEmit` con ~249 errores de base (deuda previa); plataforma valorada 7.2/10; "sin pagos en el portal, no desplegado".

## 3. Lo que NO existe todavía (no hay que "duplicar", hay que crear)

Cero código de Shopify. Stripe solo como entrada de catálogo de integraciones (12 %). No existen `commerce_*`, `activation_requests`, `billing_history`, `activation_audit_logs`, `saas_licenses`. Para licencias se **reutiliza `license_plans`** (no se crea `saas_licenses` duplicada; si hace falta, vista o columnas aditivas). Auditoría: se reutiliza `audit_logs` y se añade solo `activation_audit_logs` si se requiere traza específica inmutable.

## 4. Mapa de módulos comerciales (slugs internos reales)

`crm, ai_agents, analytics, integrations, automations, omni_accounting, omni_import_ai, whatsapp, omni_tax, omni_marketing, omni_ads, omni_leads, omni_diagnostics, omni_security, omni_docs, quotes, portal_cliente, knowledge_base` + `omni_time`, `a_medida`, taller/fleet/Ava según rutas. Estos slugs serán los identificadores comerciales (`commerce_products.module_slug`).

## 5. ⚠️ Bloqueo crítico: los precios existentes se contradicen

Pediste reutilizar los precios "ya definidos" exactamente. Hay **tres fuentes incompatibles**:

| Fuente | Fecha | Contenido |
|---|---|---|
| Memoria interna `module-system.md` | antigua | starter 99 €, professional 149 €, business 299 €, enterprise 1000 €+ |
| BD: `lib/db/drizzle/0008_omnicredits_commercial_v1.sql` (`credit_plans`) | v1, vigente en código | **Starter 149 €, Professional 349 €, Business 699 €, Enterprise a medida**; packs de créditos 29/89/199/599 € |
| Web pública `omnitech-core-info` (`DEPLOY-README.txt`, `/precios`) | 13-nov-2026 (la más reciente) | **Una única oferta "a medida desde 149 €/mes"**, sin planes cerrados, sin descuento anual, prueba 7 días, "no hay contratación automática" |

No voy a elegir ni inventar. Además, el modelo "a medida, previa propuesta" de la web pública choca con un checkout Shopify autoservicio: hay que decidir cómo se refleja en Shopify (ver §7).

## 6. Plan de integración propuesto (sin tocar lo existente)

1. **Servicio independiente `omnicommerce-bridge`** (nuevo paquete `artifacts/omnicommerce-bridge` o router aislado en api-server): Express + `rawBody`, validación HMAC `X-Shopify-Hmac-Sha256` (timing-safe), idempotencia por `X-Shopify-Webhook-Id` (índice único en `commerce_webhook_events`), reintentos con backoff, estados separados pedido / pago / suscripción.
2. **Migración aditiva e idempotente** (`0018_omnicommerce.sql` + registro en startup): `commerce_customers`, `commerce_products` (FK lógica a slug de módulo + plan), `commerce_orders`, `commerce_subscriptions`, `commerce_webhook_events`, `activation_requests`, `billing_history`, `activation_audit_logs`; índices únicos (shopify ids), CHECK de estados, FKs con `ON DELETE RESTRICT` hacia `organizations` (nunca borrar datos de empresa).
3. **Activación manual obligatoria**: el webhook solo escribe `activation_requests(status='pending')`. La aprobación es un endpoint de Control Center bajo `requireSuperAdmin` que, en una transacción, crea/vincula org, `license_plans`, `module_configs`, miembro owner y registra `audit_logs`; el email de bienvenida va después (Resend). Ninguna ruta del navegador ni del webhook toca licencias.
4. **Control Center → "OmniCommerce Control"**: 11 apartados reutilizando layout/guard existentes y OpenAPI/Orval.
5. **Suspensión/reactivación configurables** (periodo de gracia, política por plan) en tabla de ajustes; suspender = `license_plans.is_active=false` + `module_configs` restrictivos, nunca borrar.
6. **Tienda Shopify**: tema Online Store 2.0 (Liquid) + productos/metacampos con `omni_module_slug` y `omni_plan` + selling plans (suscripción mensual). Sincronización de catálogo desde fuente única de verdad (`commerce_products`).
7. **Pruebas**: batería de 15 escenarios con Vitest sobre rama Neon desechable, payloads Shopify simulados firmados con HMAC de prueba, cero cobros reales.

## 7. Lo que necesito del exterior (no se simula)

- **Shopify**: dominio `*.myshopify.com`, app personalizada (Dev Dashboard) con scopes `read_orders, read_customers, read_products, read_own_subscription_contracts, write_own_subscription_contracts`, **Admin API access token** y **API secret** (para HMAC), y confirmación del plan de Shopify (suscripciones requieren app de pagos compatible con Shopify Payments / Subscriptions API). No hay conector Shopify en este entorno.
- **Resend** con dominio verificado (`RESEND_API_KEY`, `EMAIL_FROM`) para el correo de bienvenida.
- **Base de datos de pruebas** (rama Neon desechable) y, para producción, acceso para aplicar la migración.
- **Permiso de escritura** sobre `omnitech-core-v1` (ahora solo lectura aquí).
