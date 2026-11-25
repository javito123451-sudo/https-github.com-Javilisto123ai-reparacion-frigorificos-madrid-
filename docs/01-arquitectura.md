# 01 · Arquitectura y decisiones técnicas

Estado: **propuesta para aprobación**. No hay código. Nombre en clave: `fraudguard`.

## 1. Principios

1. **El LLM extrae, el código decide.** Los modelos convierten contenido no estructurado en señales tipadas; la puntuación sale de un motor determinista, testeable y explicable.
2. **Honestidad epistémica.** Cada resultado distingue: evidencia verificada / indicio / no verificable. "Indeterminado" es un resultado válido.
3. **Mínimo dato, mínima retención.**
4. **Proveedores intercambiables** tras interfaces propias.
5. **Monolito modular primero**; separar servicios solo cuando la carga lo justifique.

## 2. Stack recomendado (con alternativas)

| Capa | Recomendación | Por qué | Alternativa |
|---|---|---|---|
| Frontend | **Next.js (React, TypeScript) como PWA** | Una base para landing SEO + app; cámara vía `getUserMedia`/`<input capture>`; sin pasar por tiendas de apps en MVP | Vite + React (más simple si la landing es aparte) |
| Backend API | **Python 3.12 + FastAPI** | Mejor ecosistema para imagen/OCR/ML, tipado con Pydantic, OpenAPI automático para la API pública | NestJS (TS de punta a punta: menos contexto, peor ecosistema ML) |
| Base de datos | **PostgreSQL 16** (+ `pgcrypto`, Row Level Security) | Relacional, RLS para aislamiento, JSONB para evidencias | — |
| Cola / tareas | **Redis + worker (Dramatiq o Arq)** | Análisis asíncronos, reintentos, sin sobrecarga de Celery | Cola en Postgres (`pgmq`) para evitar Redis en MVP |
| Almacenamiento | **Objeto compatible S3, región UE, cifrado en reposo, URLs firmadas de corta vida** | Separar binarios de la BD | — |
| IA | Interfaz `LLMProvider` (visión + texto, salida JSON con esquema) con adaptadores | Sin dependencia exclusiva (R11) | Modelos locales/abiertos para OCR |
| OCR | Primero el modelo de visión; **Tesseract/PaddleOCR** como respaldo barato/offline | Coste | — |
| Auth | Sesiones con cookies `HttpOnly` + argon2id, email verificado, 2FA opcional; OIDC (Google) después | Seguridad simple; evita construir demasiado | Servicio gestionado (Auth0/Clerk): coste y datos fuera |
| PDF | Generación en servidor (WeasyPrint) desde plantilla HTML | Control del contenido | — |
| Observabilidad | Logs JSON + OpenTelemetry + Sentry (UE) + métricas de coste por análisis | Requisito de calidad §13 | — |
| CI | GitHub Actions: lint, tipos, tests, SAST, escaneo de dependencias | — | — |

Criterio de decisión: coste de operación, mantenibilidad por un equipo pequeño y seguridad por defecto, no moda. La opción más discutible es **dos lenguajes** (TS + Python); se acepta por el ecosistema ML/imagen del backend.

## 3. Vista de componentes

```
 PWA (Next.js) ──HTTPS──▶ API (FastAPI)
                            │  auth · cuotas · validación · rate limit
                            ├─▶ PostgreSQL (RLS por usuario)
                            ├─▶ Object storage (EU, URLs firmadas)
                            └─▶ Redis ──▶ Workers
                                          ├─ Ingesta/sanitizado de ficheros (EXIF fuera, antivirus, re-encode)
                                          ├─ Extractor URL (anti-SSRF, pasivo)
                                          ├─ OCR / Visión → LLMProvider
                                          ├─ Extractor de señales (LLM → JSON tipado)
                                          ├─ Reputación (RDAP, DNS, fuentes licenciadas)
                                          └─ FRAUD RISK ENGINE (determinista)
                                                      │
                                              Expediente (analysis + signals + evidence) ─▶ PDF
```

Flujo de un análisis: `POST /analyses` → 202 + id → worker ejecuta pipeline → el cliente consulta por polling/SSE → expediente. Todo análisis es **idempotente por hash de entrada** (caché y control de coste).

## 4. Fraud Risk Engine (diseño)

**Entradas:** señales tipadas `Signal{code, category, severity(0-1), certainty(0-1), evidence_ref, verified: bool}` más contexto (precio, categoría, canal).

**Catálogo de señales (ejemplos MVP):** `PRICE_FAR_BELOW_EXPECTED`, `PAYMENT_OFF_PLATFORM`, `URGENCY_PRESSURE`, `ADVANCE_PAYMENT_REQUESTED`, `SENSITIVE_DATA_REQUESTED`, `URL_SHORTENER`, `DOMAIN_AGE_LT_30D` (solo si verificado por RDAP), `LOOKALIKE_DOMAIN`, `CONTACT_INCONSISTENT`, `OFF_CHANNEL_MOVE` (pasar a WhatsApp), `STOCK_PHOTO_SUSPECTED` (solo con búsqueda inversa real, si se integra).

**Cálculo:**
- Cada señal tiene un peso base `w` en configuración versionada (`ruleset_version`).
- Contribución = `w × severity × certainty`; las señales no verificadas se atenúan.
- Agregación con saturación (tipo *noisy-OR* o suma con tope) para no premiar acumular señales débiles; **señales atenuantes** (p. ej. plataforma con pago protegido usada correctamente) restan.
- Puntuación 0-100 mapeada a las bandas del documento maestro.
- **Confianza** independiente = cobertura de factores verificables (qué comprobaciones se pudieron hacer).
- **Indeterminado** si confianza < umbral o entrada insuficiente.
- La puntuación **no es una probabilidad** (se indica en UI/PDF); los pesos se calibrarán con el dataset de evaluación, no a ojo.
- Salida explicable: lista de señales con su contribución, factores no verificados y recomendaciones por señal.

**Guardarraíles de equidad:** lista cerrada de señales permitidas; ninguna deriva de rasgos personales del vendedor (apariencia, origen, nacionalidad); test automático que falla si aparece una señal fuera del catálogo.

## 5. Seguridad y privacidad (diseño desde el inicio)

| Amenaza | Control |
|---|---|
| SSRF | Egress solo desde workers aislados; resolver DNS y validar IP tras cada salto; bloquear loopback/privadas/link-local/metadata; máx. redirecciones y tamaño; sin esquemas distintos de http(s) |
| URLs maliciosas | Nunca abrir en el dispositivo del usuario; MVP = petición pasiva sin ejecutar JS; renderizado en sandbox es Fase 3 |
| Prompt injection | Contenido del usuario en canal de datos delimitado; salida JSON validada con esquema; el LLM no tiene herramientas ni acceso a red; la puntuación no depende de texto libre del LLM |
| Subida de ficheros | Tipo por magic bytes, límites de tamaño/píxeles, re-encode, eliminar EXIF/GPS, antivirus |
| Aislamiento | RLS en Postgres por `user_id`/`org_id`; tests de acceso cruzado obligatorios |
| Secretos | Variables de entorno / gestor de secretos; nunca en cliente ni en repositorio; rotación |
| Abuso | Rate limit por usuario/IP/API key, cuotas por plan, presupuesto de IA con corte |
| Auditoría | `audit_log` append-only de accesos, exportaciones y borrados |
| RGPD | Base jurídica y RAT documentados, DPA con proveedores, región UE, retención por defecto corta (propuesta: ficheros 30 días, configurable), derecho de acceso/borrado, DPIA previa al lanzamiento (hay imágenes y datos de terceros) |
| AI Act (UE) | Clasificación previa: se prevé riesgo limitado (transparencia: informar de que es IA); confirmar con asesor jurídico |

## 6. Alcance del MVP (Fase 1) — propuesta concreta

Se divide en incrementos verticales; cada uno se entrega funcionando y con tests.

| Incremento | Contenido | Criterio de salida |
|---|---|---|
| **M0 Cimientos** | Monorepo, CI, Postgres+migraciones, auth, cuotas, logging, `LLMProvider` con doble de test | Registro/login funcional; tests de aislamiento entre usuarios |
| **M1 Texto** | Analizar mensaje/conversación pegada → señales → riesgo → expediente | Evaluación sobre dataset: FP y FN medidos por categoría |
| **M2 URL** | Extractor pasivo anti-SSRF, RDAP/DNS, lookalike, señales de tienda | Suite SSRF superada; dominios verificados vs. no verificados diferenciados |
| **M3 Imagen/captura** | Subida segura, OCR/visión → pasa a M1/M2 | Captura de anuncio produce el mismo tipo de expediente |
| **M4 Historial e informes** | Listado, PDF, borrado, retención | Borrado verificable; PDF con limitaciones |

**Fuera del MVP:** escáner en directo, autenticidad de productos, estimación de precio de mercado, audio, pagos, API pública, app nativa.

**Por qué el escáner presencial se pospone:** es el diferencial, pero es también el riesgo R1/R4. Se hará en Fase 2 con un experimento previo: dataset propio etiquetado + medición de qué se puede afirmar realmente. Se entregará lo que los datos sostengan (guía de comprobación por categoría, extracción de modelo/serie/etiquetas por OCR, coherencia precio-contexto), no un detector milagroso.

## 7. Estrategia de pruebas y calidad

- **Dataset de evaluación versionado** en `eval/`: casos fraudulentos *y legítimos* (incl. chollos reales y vendedores honestos), etiquetados, con licencia/anonimización. Se necesita **fuentes reales y legales**: no usaré datos ficticios como si fueran verificación; los sintéticos se marcarán como tales.
- Pirámide: unitarios del motor (puros, deterministas) → contrato de proveedores con dobles → integración API+BD → e2e del flujo principal.
- Métricas por categoría: precisión, recall, FP rate; umbrales de CI que bloquean regresiones del `ruleset`.
- Pruebas de seguridad: SSRF, inyección de prompts, subida de ficheros, acceso cruzado.
- Coste: test que registra tokens/€ por análisis; alerta si supera presupuesto.

## 8. Modelo comercial (hipótesis, sin precios)

Los precios no se fijan hasta medir coste real por análisis (tokens de visión, OCR, consultas externas, almacenamiento, soporte). Esquema: B2C freemium con cuota + suscripción; B2B por asientos; API por consumo; "Premium" = más cuota, informes ampliados, funciones avanzadas. Fórmula de margen: `precio − (coste IA + consultas externas + almacenamiento·retención + soporte + pasarela de pago)`.

## 9. Roadmap

1. **Fase 0** (actual): auditoría, arquitectura, esquema BD, plan → *aprobación tuya*.
2. **Fase 1** MVP M0-M4.
3. **Fase 2** Escáner presencial, precedido de experimento de viabilidad (R1).
4. **Fase 3** Conversaciones avanzadas, audio, verificación de dominios en profundidad, alertas, segundo proveedor de IA.
5. **Fase 4** Suscripciones, panel B2B, API pública, nativo, integraciones (incl. OmniTech-Core opcional), internacionalización.

## 10. Registro de decisiones (ADR resumidas)

| ID | Decisión | Estado |
|---|---|---|
| ADR-1 | Producto independiente, repo propio | Propuesta (pendiente confirmar repo) |
| ADR-2 | Monolito modular + workers | Propuesta |
| ADR-3 | FastAPI + Next.js PWA + PostgreSQL + Redis | Propuesta |
| ADR-4 | El LLM extrae señales; puntuación determinista | **Recomendada firmemente** |
| ADR-5 | Escáner presencial en Fase 2 tras experimento de viabilidad | Propuesta |
| ADR-6 | Región UE, retención corta por defecto | Propuesta |
| ADR-7 | Sin navegador headless ni ejecución de JS en MVP | Propuesta |

## 11. Despliegue

Sin despliegue ni gasto sin tu autorización explícita. Desarrollo local con `docker compose` (Postgres, Redis, MinIO). Instrucciones de despliegue se redactan en M0 y se ejecutan solo con tu OK.
