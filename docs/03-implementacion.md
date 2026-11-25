# 03 · Implementación v0.1 (desviaciones respecto a la arquitectura propuesta)

Decisiones tomadas para entregar algo funcional ya; todas reversibles.

| Propuesta (01) | Implementado | Motivo |
|---|---|---|
| Next.js PWA | HTML/JS/CSS estáticos servidos por FastAPI (instalable, `manifest`) | Menos piezas; mismo contrato REST, migrable |
| PostgreSQL + RLS | SQLite, aislamiento por hash de sesión | Cero infraestructura; esquema portable |
| Redis + workers | Análisis síncrono (≈ segundos) | Se añade cola cuando la carga lo pida |
| Cuentas + 2FA | Cuentas email/contraseña + sesiones; sesión anónima si no hay cuenta | Sin 2FA ni verificación de email (requiere proveedor de correo) |
| PDF | PDF nativo (reportlab) + informe HTML | Hecho |
| Suscripciones | Planes y cuotas internos; plan asignado por admin | Sin pasarela de pago: no se inventa una integración |
| API pública | Claves Bearer hasheadas sobre los mismos endpoints | Sin facturación por consumo |
| Proveedor de IA | OpenAI (`gpt-4o` por defecto, configurable) tras la interfaz `LLMProvider`; cambiar de proveedor no toca el motor | El coste real debe medirse |

## Seguridad implementada y probada
SSRF (IP pública validada en cada salto, petición fijada a la IP, puertos/esquemas/tamaño/redirecciones acotados), prompt injection
(datos aislados, salida estructurada con catálogo cerrado, puntuación fuera del LLM, citas verificadas contra el texto), imágenes
(formato real, recodificación, sin EXIF/GPS), CSP estricta, cookies HttpOnly/SameSite, límites por usuario/IP y presupuesto diario de IA,
auditoría, minimización (no se guarda texto ni imágenes de entrada), informe con escape HTML.

## Calidad medida (honesta)
Modo reglas sobre `eval/cases.jsonl` (48 casos **sintéticos**): recall 88 %, falsos positivos 0 %. **Optimista**: las reglas se
ajustaron mirando ese mismo conjunto y los pesos del motor son provisionales. Hace falta un conjunto real y separado para calibrar.
El rendimiento con IA no se ha medido (sin clave).

## Riesgos abiertos
Reglas de precio por marca = umbrales internos orientativos (siempre etiquetados como tales). Cumplimiento RGPD/AI Act y términos
legales pendientes de revisión jurídica antes de abrir al público.
