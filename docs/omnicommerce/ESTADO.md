# Estado de OmniCommerce (2026-11-25)

Código en `javito123451-sudo/omnitech-core-v1`, rama `claude/omnicommerce-bridge` (sin tocar `main`). Detalle en `docs/omnicommerce/` de esa rama.

**Precios confirmados** (mensual, sin IVA): Starter 149 € (promo lanzamiento 99 €, desactivada), Professional 249 €, Enterprise 1.000 €. Módulos (complemento mensual, no se venden sueltos): sin IA 25 €, IA ligera 35 €, IA pesada 45 €; CRM incluido. Stripe no es fuente (solo existió un 99 € + IVA antiguo, descartado).

Hecho: Fase 2 (migración aditiva) y Fase 4 (Bridge) y backend de Fase 5; Fase 6 parcial con 20/20 pruebas en BD real.
Pendiente: tema/productos Shopify (Fase 3), pantallas React de OmniCommerce Control, pruebas con Shopify real, puesta en producción.

**Decidido (25-nov):** el plan Business no se comercializa (mismo acceso que Enterprise; competiría con él). Se conserva en BD como plan heredado. `credit_plans` (Professional 349 €, Business 699 €) es configuración interna de créditos IA y no alimenta la tienda; no se ha tocado. Si quieres alinear Professional a 249 € ahí también, es un cambio de datos de una línea que haré cuando lo pidas.

**Fase 3 (tienda Shopify) — borrador completo en `shopify/`:** tema OS2.0, catálogo y sincronizador (dry-run probado). Pendiente de credenciales para aplicar/probar en tienda real. Ver `shopify/README.md`.

**Cambio de flujo (25-nov):** primero se capta → autoriza un admin → se puede contratar → se activa manualmente tras el pago. Implementado en `omnitech-core-v1` (28/28 pruebas) y en el tema (`/pages/solicitar`). **Actualizado:** pagado + autorizado ⇒ activación automática (ajuste configurable, activo por defecto; 35/35 pruebas).

**Business desactivado (25-nov):** `credit_plans.business.active=false` al desplegar, solo si ninguna empresa/licencia activa lo usa (si no, se avisa y no se toca). Verificado en BD local, 37/37 pruebas. **Comprobar en producción antes de desplegar** si hay empresas en Business.
