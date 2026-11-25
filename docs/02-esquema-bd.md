# 02 · Esquema de base de datos (borrador)

PostgreSQL 16. Todas las tablas de usuario llevan `user_id`/`org_id` con **Row Level Security**. Borrador de diseño; las migraciones reales se escribirán en M0.

```sql
-- Identidad
users(id uuid pk, email citext unique, password_hash text, email_verified_at timestamptz,
      status text, locale text default 'es', created_at, deleted_at)
orgs(id uuid pk, name text, created_at)
org_members(org_id fk, user_id fk, role text check (role in ('owner','admin','member')), primary key(org_id,user_id))
sessions(id uuid pk, user_id fk, token_hash text, ip inet, user_agent text, expires_at, revoked_at)

-- Planes y cuotas (la facturación real llega en Fase 4)
plans(code text pk, monthly_quota int, max_image_mb int, retention_days int)
subscriptions(id, user_id/org_id, plan_code fk, status, period_start, period_end, external_ref)
usage_events(id, user_id, analysis_id, kind text, units int, cost_micro_eur bigint, created_at)

-- Núcleo
analyses(id uuid pk, user_id fk, org_id fk null,
         kind text check (kind in ('url','text','conversation','screenshot','image','shop','product')),
         status text check (status in ('queued','running','done','failed','expired')),
         input_hash text,                     -- idempotencia y caché
         context jsonb,                       -- precio, marca anunciada, canal, descripción
         ruleset_version text, engine_version text,
         risk_score smallint check (risk_score between 0 and 100) null,
         risk_band text null, verdict text check (verdict in ('scored','indeterminate')) null,
         confidence real null,
         limitations jsonb, created_at, completed_at, expires_at, deleted_at)

analysis_files(id, analysis_id fk, storage_key text, mime text, bytes int, sha256 text, exif_stripped bool, expires_at, deleted_at)

signals(id, analysis_id fk, code text, category text,
        severity real, certainty real, weight_applied real, contribution real,
        verified bool, evidence jsonb, explanation text, recommendation text)

evidence_sources(id, analysis_id fk, source text,     -- 'rdap','dns','ocr','llm','user_input',...
                 retrieved_at, status text, raw_ref text, license_note text)

unverifiable_factors(id, analysis_id fk, factor text, reason text)

reports(id, analysis_id fk, storage_key text, generated_at, checksum text)

-- Configuración versionada del motor
rulesets(version text pk, definition jsonb, created_at, active bool)

-- Operación y cumplimiento
audit_log(id bigserial, actor_id, action text, target_type text, target_id uuid, ip inet, at timestamptz)  -- append-only
deletion_requests(id, user_id, scope text, requested_at, completed_at)
provider_calls(id, analysis_id, provider text, model text, tokens_in int, tokens_out int, cost_micro_eur bigint, latency_ms int, ok bool)
eval_cases(id, category text, label text check (label in ('fraud','legit')), input jsonb, source text, synthetic bool, notes text)  -- solo entorno de evaluación

-- Fase 4
api_keys(id, org_id, key_hash text, label, scopes text[], rate_limit int, revoked_at)
```

## Notas

- **Retención:** `expires_at` por plan/usuario; un job elimina fichero y fila de `analysis_files`; el expediente puede conservar solo señales y puntuación si el usuario lo decide.
- **No se guarda** el texto íntegro de conversaciones salvo que el usuario lo elija; por defecto, solo señales y fragmentos citados mínimos.
- **Reproducibilidad:** `ruleset_version` y `engine_version` en cada análisis permiten reconstruir por qué se obtuvo una puntuación.
- **Índices clave:** `analyses(user_id, created_at desc)`, `analyses(input_hash)`, `signals(analysis_id)`.
- **Cifrado:** disco/volumen cifrado + cifrado a nivel de aplicación de `context` y de `storage_key` sensibles cuando se defina el gestor de claves.
