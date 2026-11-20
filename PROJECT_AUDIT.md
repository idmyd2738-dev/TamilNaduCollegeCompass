# CollegeHub project audit

Audit date: 19 November 2026. Scope: application modules, SQLAlchemy metadata, Alembic revisions, repositories/services, templates/static assets, tests, bundled SQLite database, and visible deployment files. `.env` values were not included in this report. `selenium_tests/` was not modified.

## Architecture

- Flask/Jinja application entry point: `index.py` exports `app` from `app.py`.
- Universal database: SQLAlchemy 2.x, Alembic, psycopg 3, SQLite for local development, PostgreSQL for Neon, and pgvector.
- Application tables and the Alembic version table use the dedicated PostgreSQL `collegehub` schema. The pre-existing `public.playing_with_neon` relation and sequence are outside the migration scope.
- `models.py`, `database.py`, `repositories.py`, `services.py`, and `alembic/` contain the persistence layer, read paths, and migrations.
- `sample_colleges.db` is a legacy SQLite prototype containing fictional records. It remains preserved and is accessible only in tests or explicit non-deployed `COLLEGEHUB_DEMO_MODE=1`; public database-mode routes do not fall back to it.
- No `vercel.json`, container definition, CI deployment workflow, or verified deployment configuration was found.

## Live Neon status

- PostgreSQL 18.7; database `collegehub`; pgvector 0.8.7.
- Alembic revision `b7c41e98f2ad`; live `alembic check` passes.
- 38 application tables, 156 indexes, 83 foreign keys, 50 unique constraints, 3 JSONB columns, 1 VECTOR column.
- 16 Anna University constituent-college records were collected from its official directory. Each is pending verification, with only the listed name and linked institution website populated.
- No program, admission/cutoff, fee, placement, facility, embedding, or verified institution records are available.
- The source page, source hash reference, and import-job status are recorded in the universal schema.

## Implemented in this iteration

- Database-mode public home, category/stream, institution directory, institution profile, compare, recommendation candidate, and admission-record pages.
- Database-backed institution and program APIs with filters, limit/offset metadata, plus admission and placement APIs.
- `/health` performs an actual database connection check.
- Canned chat, student accounts, and legacy SQLite admin routes are disabled in database mode. A limited SQL-backed admin review console is available only with an explicit password hash and session secret.
- A bounded, idempotent Anna University HTML collector registers source/document/import-job provenance and imports the 16 observed directory rows as pending.
- Additive lookup migration for a neutral unknown institution type.

## Important limitations

- The full statewide source coverage, program/seat extraction, medical/agriculture/arts ingestion, PDF/CSV ingestion, conflict resolution, and complete admin workflow are unfinished. The current review console supports source registration, one fixed importer, and status review; it has no user roles, MFA, individual reviewer identity, or rate limiting.
- Recommendation results are not admission predictions and the real eligibility/cutoff-based engine is not yet implemented. Current imported data is insufficient for recommendations.
- The cutoff page shows typed admission records but has no verified records or interactive chart data.
- The chatbot is not an AI/RAG service. No LLM/embedding provider, citation validation, or document chunk/embedding pipeline is implemented.
- Student accounts and organizational admin identity are unavailable. The optional shared-password admin console is limited and is not a production identity system. The old local demo admin is not production authentication.
- Vercel/runtime compatibility and live deployment have not been tested; no deployment was performed.

## Validation

- `.venv\Scripts\python.exe -m pytest -q tests`: 35 passed, 1 skipped, 20 subtests passed.
- Python compilation passed for app, models, repositories, services, ingestion, migrations, and tests. The updated app has no Pylance diagnostics.
- Live official-page parser fetched and extracted all 16 numbered Anna University rows.
- Live Neon database-backed route/API smoke tests previously passed; no new live admin login was attempted because no admin hash was configured or tested against Neon.
- Live CRUD checks use rollback-only transactions; no fictional test institution persisted.
- The automated PostgreSQL compatibility test was skipped because a separate PostgreSQL test database URL was not configured. Separate live Neon connection/schema checks were performed.
