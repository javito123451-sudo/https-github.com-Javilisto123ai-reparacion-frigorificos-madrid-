# OMNI REVIEW BOT — Fase 1: auditoría técnica y plan de implementación

Fecha: 2026-11-25 · Estado: **auditoría completada, implementación NO iniciada** (a la espera de las decisiones de la sección 6).

## 0. Alcance y método

- Auditoría **solo de lectura**, sobre clones superficiales (`--depth 1`). No se ha instalado nada, ni ejecutado `tsc`, ni tests, ni la aplicación. Todo lo que sigue procede de leer código y los ficheros `.agents/memory/*` del propio repo.
- Se ha auditado `javito123451-sudo/omnitech-core-v1` (commit `dc668ef`, 2026-11-21).

## 1. Hallazgo bloqueante: dónde vive OmniTech-Core

| Repositorio | Estado |
|---|---|
| `…/reparacion-frigorificos-madrid-` (esta sesión) | Solo `README.md`. **No contiene OmniTech-Core.** |
| `omnitech-core-v1` (público) | Monorepo vivo y más reciente (`dc668ef`, nov 2026). Incluye módulos que la otra copia no tiene (A Medida, OmniSeller, email adapter, smoke tests, `.github`, `.env.example`). |
| `OmniTech-Core` (privado) | Copia anterior (`4d8482b`, sep 2026). Diverge de v1; es un ancestro desfasado. |
| `omnitech-core-info` | No auditado (parece web informativa). |

Se ha tomado **v1 como base**. Hay que confirmarlo (sección 6). Además, esta sesión solo puede escribir en el repo vacío; en v1 solo tiene lectura.

## 2. Arquitectura actual (verificada en código)

- **Monorepo pnpm** (Node 24, TS 5.9): `artifacts/api-server` (Express 5, bundle esbuild CJS), `artifacts/omniflow` (frontend React 19 + Vite + wouter + TanStack Query + Tailwind v4), `lib/db` (Drizzle + PostgreSQL), `lib/api-spec` (OpenAPI + Orval → `api-client-react`, `api-zod`).
- **Auth**: Clerk. `requireAuth → resolveOrg → resolvePermissions` (`middlewares/auth.ts`). Soporta multi-workspace (`x-active-workspace`) y modo soporte de SUPER_ADMIN (`x-ws-override`) con auditoría.
- **Multi-tenancy**: aislamiento por fila con `org_id` (FK a `organizations`) en cada query. **No hay RLS en Postgres**: el aislamiento depende de que cada consulta filtre por `orgId`.
- **Módulos/planes**: `requireModule(slug)` consulta `module_configs` (caché 2 min). `routes/auth.ts` expone `ALL_MODULE_SLUGS` y plan→módulos; el catálogo del Control Center está en `routes/control-center.ts` (~línea 635). Un slug nuevo debe añadirse en **cuatro** sitios: auth.ts, FIX-AB (seed), CATALOG del Control Center, sidebar. (Ya ocurrió un bug por olvidar uno: `omni_leads`, commit `d7fea9a`.)
- **Permisos**: `middlewares/permissions.ts`; en uso hay patrones como `workspace.view/edit`, `omniseller.read/write`, `a_medida.read/write`.
- **Migraciones**: doble vía — `lib/db/drizzle/*.sql` (0000–0009) y `utils/startupMigrations.ts` (SQL crudo, secuencia FIX-A…FIX-AF; siguiente letra libre según memoria: **FIX-AG o posterior, comprobar**). Gotchas documentados: guardar IDs de org en prod, cast `::text` en parámetros `sql\`\``, el scheduler debe arrancar tras migraciones.
- **Jobs programados**: `node-cron`/`setInterval` en proceso (Render, proceso persistente). Existe `routes/internalCron.ts` (protegido por `CRON_SECRET`) y un workflow de GitHub Actions **desactivado a propósito** para no duplicar ejecuciones. **No hay cola de tareas** (BullMQ/pg-boss/etc.).
- **Hosting**: backend en Render; `vercel.json` también presente (legado).

## 3. Módulos con los que hay que integrarse

| Módulo | Qué hay realmente | Implicación |
|---|---|---|
| **Omni CRM** | tablas `clients`, `appointments`, `pipeline`; `clients.commercial_status='no_contactar'` | Fuente de contactos y de bajas. |
| **Omni Marketing Hub** (`omni_marketing`, `routes/marketing.ts`, 606 líneas) | CRUD de campañas + `launch` con bucle de envío por WhatsApp **en el propio request** (responde pronto y sigue en memoria), `campaign_send_logs`. Sin cola durable, sin reintentos, sin consentimiento, sin límite de tasa por proveedor; la memoria del repo reconoce "marketing sends nothing" de cara a email. | **No es base válida para miles de contactos.** Reutilizar tablas/UX no; el motor debe ser nuevo y propio de reseñas. |
| **Ava Omni** | `ava-core`, `ai-gateway` (OpenAI/Claude/Gemini, coste, caché), `credits/` (OmniCredits), agentes con propuestas/aprobación (`agents/proposalStore.ts`) | Reutilizar `ai-gateway` para redacción/sentimiento/respuestas y el patrón de propuesta+aprobación para "revisar antes de publicar". |
| **Omni Notifications** | `services/notificationService.ts` → `hub/IntegrationManager` → adapters | Canal interno de alertas (reseña negativa). |
| **Integration Hub** | `hub/` con adapters `whatsapp`, `email`, `telegram`, `genericDeliveryWebhook`; credenciales cifradas (`utils/integrationCreds.ts`, `INTEGRATION_ENCRYPTION_KEY`) | Punto de entrada correcto para WhatsApp/email. Falta un adapter Google y SMS. |
| **Outreach (OmniSeller)** | `outreachGuard.ts` (cooldown, máx. intentos, supresiones), `outreach_suppressions`, webhooks Resend con firma Svix, follow-ups | **Muy reutilizable**: lista de supresión, cooldown, webhooks de estado. Hoy ligado a `lead_contacts`, no a clientes finales. |
| **Control Center** | Workspaces, módulos, auditoría, AI Center, integraciones | Alta del módulo, supervisión global, auditoría (`logAudit`). |
| **Event bus / Action Engine** | `aie/` (`emitAieEvent`), `action-engine/` | Emisión de eventos del módulo. |
| **Facturación / planes** | `credits/` (planes, packs, suscripciones), planes starter/professional/business/enterprise | No inventar precios; solo registrar límites/consumo. |

## 4. Brechas frente al encargo (lo que NO existe hoy)

1. **Nada de reseñas / Google Business Profile** en todo el código (solo el booleano `has_google_business` de OmniLeads). Integración Google completa desde cero.
2. **Cola de tareas durable y envío por lotes** con límites por proveedor.
3. **Consentimiento/base jurídica** por contacto y proveedor (RGPD/LSSI), más allá de la lista de supresión de Outreach.
4. **Plantillas WhatsApp**: hoy solo envío de plantillas fijas por variables de entorno (`approvedWhatsAppTemplates.ts`); no hay gestión de plantillas (listar/crear/estado) ni estados de entrega.
5. **SMS**: sin proveedor.
6. **Importación CSV/Excel de contactos con validación y deduplicación**: existe `omni_import_ai` (GPT-4o/xlsx) orientado a otra cosa; reutilizar `xlsx`/`multer`, no el flujo.
7. **Política de conservación de datos** y exportación/borrado RGPD.

## 5. Riesgos y conflictos detectados

- **Deuda de tipos**: la memoria del repo indica que `tsc --noEmit` pasó de 184 a **249 errores** tras un commit sin typecheck. No lo he re-medido. Antes de tocar código hay que fijar el *baseline* para no atribuirnos errores previos.
- **Aislamiento sin RLS**: cada query nueva debe filtrar por `orgId`; las pruebas de aislamiento (Fase 11) son obligatorias, no opcionales.
- **Fail-open en `requireModule`** ante error de BD/caché (`catch → next()`): para un módulo que envía mensajes a terceros conviene fail-closed en las rutas de envío.
- **Dos fuentes de migración** y orden de arranque (ver §2).
- **Dos `scheduler`s** posibles (node-cron vs endpoint cron): usar solo el vigente (en proceso) y no reactivar el workflow, o se duplican envíos.
- **Divergencia v1 ↔ OmniTech-Core privado**: elegir un único destino evita doble mantenimiento.
- **Cumplimiento (diseño, no negociable)**: el encargo exige campañas a *todos* los clientes elegibles sin filtrar por satisfacción, sin incentivos y sin reseñas generadas. Se implementa como reglas del motor (sin campo "satisfacción" como filtro de envío; texto de plantilla validado contra fórmulas de incentivo).
- **Google**: la Business Profile API exige **solicitud de acceso y aprobación de Google** y OAuth del propietario de la ficha. El enlace directo para reseñas (`https://search.google.com/local/writereview?placeid=…`) no requiere API, solo el Place ID. Hasta tener aprobación, la lectura de reseñas **no se puede declarar funcional**.
- **WhatsApp**: iniciar conversación fuera de la ventana de 24 h exige plantilla aprobada por Meta (categoría y política propias) y opt-in. Sin cuenta WABA de prueba no se pueden hacer "envíos reales en entorno autorizado".

## 6. Plan de implementación propuesto (aditivo; no se modifica lo operativo)

Módulo nuevo `omni_review` (slug independiente, como `a_medida`/`omni_seller`), permisos `review.read/write/admin`. Código en `artifacts/api-server/src/review/` y `artifacts/omniflow/src/pages/review/`; tablas con prefijo `review_`.

| Fase | Entregable | Reutiliza | Se puede verificar sin credenciales externas |
|---|---|---|---|
| A. Base | Esquema `review_*` (establecimientos, contactos, consentimientos, campañas, envíos, reseñas, plantillas, eventos), migración idempotente, alta del módulo en los 4 sitios, permisos, auditoría | `organizationsTable`, `logAudit`, `requireModule` | Sí (BD de pruebas) |
| B. Motor de campañas | Importación CSV/XLSX, validación (E.164/email), dedupe, segmentación, consentimiento, cola en BD (`FOR UPDATE SKIP LOCKED`), lotes, límites por proveedor, reintentos con backoff, bajas, historial | patrón de `outreachGuard`, `outreach_suppressions` | Sí, con proveedor simulado **etiquetado como tal** en tests |
| C. Canales | Adapter WhatsApp Cloud (plantillas, estados vía webhook con HMAC), email (Resend ya existente), SMS (proveedor por decidir) | `hub/`, `integrationCreds` | Parcial: envío real requiere credenciales |
| D. Google | Enlaces de reseña por Place ID; OAuth + Business Profile API tras aprobación de Google | — | Enlaces sí; API **no** hasta aprobación |
| E. Ava | Redacción, sentimiento, temas recurrentes, respuestas sugeridas con aprobación, alertas | `ai-gateway`, `proposalStore`, `notificationService` | Con clave de IA |
| F. Dashboard | Panel, campañas, reseñas; separar *enviadas / entregadas / clics / reseñas confirmadas* | componentes de `marketing.tsx`/`ads/` | Sí |
| G. SaaS | límites por plan, consumo, costes, hooks a `credits/` sin tocar precios | `credits/` | Sí |
| H. Pruebas y docs | Tests de aislamiento, permisos, rendimiento (5.000 contactos), recuperación; OpenAPI; guía de configuración; lista de credenciales pendientes | Vitest ya configurado | Sí |

Orden: A → B → F(mínimo) → C → E → D → G → H. Cada fase termina con `tsc` (comparado con baseline) y sus tests antes de seguir.

## 7. Decisiones que necesito del propietario

1. **Repositorio destino**: ¿`omnitech-core-v1` (recomendado, es el vivo)? Requiere concederme acceso de escritura a esa sesión/repo; hoy solo tengo lectura. Alternativa: construir el módulo en este repo vacío como paquete aparte (peor: no queda "integrado").
2. **Rama/entorno**: confirmar que se trabaja en una rama (no producción) y si hay BD de desarrollo/Neon rama de pruebas disponible.
3. **Proveedor SMS** (p. ej. Twilio, otro) o dejarlo fuera de la primera entrega.
4. **Credenciales/permisos externos** (nada de esto lo invento): cuenta WABA + plantilla de reseñas aprobada; proyecto Google Cloud con acceso aprobado a Business Profile API y cliente OAuth; clave de IA para Ava; `INTEGRATION_ENCRYPTION_KEY` (ya existe); `META_APP_SECRET` (pendiente según memoria del repo).
