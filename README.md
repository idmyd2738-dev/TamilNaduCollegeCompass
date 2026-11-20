# CollegeHub

CollegeHub is a Flask application backed by the universal SQLAlchemy database. With `DATABASE_URL` configured, public institution, programme, comparison, recommendation, and admission pages read from PostgreSQL; they do not fall back to `sample_colleges.db`. Without a URL, the same database layer uses the separate local `instance/collegehub.sqlite3` file.

## Current verified state

- Neon PostgreSQL 18.7, database `collegehub`, and pgvector 0.8.7 have been connected and tested.
- The dedicated `collegehub` schema is at Alembic revision `b7c41e98f2ad`; the unrelated `public.playing_with_neon` table is preserved.
- The schema has 38 application tables, 156 indexes, 83 foreign keys, 50 unique constraints, 3 JSONB columns, and 1 VECTOR column.
- Sixteen constituent-college names and the linked websites were extracted from Anna University's [official constituent-college directory](https://www.annauniv.edu/constituent_colleges.php) and imported with pending verification. The page does not provide the other profile fields, so those remain null.
- No programmes, admission/cutoff records, fees, placements, facilities, embeddings, or verified institution records have been imported.
- The AI/RAG chatbot and student authentication are not implemented. A basic single-administrator database review console is available only when explicitly configured with a password hash and session secret; it is not a multi-user or role-based production identity system.

See [docs/OFFICIAL_DATA_INGESTION.md](./docs/OFFICIAL_DATA_INGESTION.md) for the collector, evidence, and data limitations.

## Stack and structure

- Python, Flask, Jinja2, SQLAlchemy 2.x, Alembic, psycopg 3, pgvector, SQLite, pytest, and vanilla JavaScript/CSS.
- `app.py` provides database-backed public pages and JSON APIs. The earlier SQLite demonstration pages are reachable only during tests or with an explicit local `COLLEGEHUB_DEMO_MODE=1`; read-only deployments cannot enable that mode.
- `models.py`, `database.py`, `repositories.py`, and `services.py` define the universal data layer.
- `ingestion/anna_university.py` contains a bounded, repeatable importer for the official Anna University constituent-college page.
- `alembic/` contains reviewed migrations. Application import does not run migrations.
- `index.py` exports the Flask application. No deployment has been run from this checkout.

## Local setup (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set `DATABASE_URL` to a **local development database** before applying migrations. Do not use a production URL for tests or local schema experimentation.

```powershell
$env:DATABASE_URL = "sqlite:///instance/collegehub-dev.sqlite3"
python -m alembic upgrade head
python app.py
```

For a local legacy UI demonstration only, set `COLLEGEHUB_DEMO_MODE=1`. This uses the bundled `sample_colleges.db`, which contains fictional records and is not used as a fallback in database mode. Do not enable this option in a deployed environment.

The app loads `.env` for local development through `python-dotenv`. Never commit `.env` or expose its values.

To configure the database review console, set `COLLEGEHUB_SECRET_KEY` and `COLLEGEHUB_ADMIN_PASSWORD_HASH` in the deployment environment. Generate a hash without echoing the password:

```powershell
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass()))"
```

The console supports source registration, the bounded Anna University directory import, and provenance status review. It does not provide user management, individual reviewer identities, rate limiting, or MFA. `COLLEGEHUB_READ_ONLY=1` disables the console. Do not configure this shared-password console as a substitute for an organization identity provider.

## Official-data ingestion

The collector checks the source's `robots.txt`, uses a bounded HTTP request, validates the source host and content type, parses only numbered directory rows, records a SHA-256 reference and import job, and imports records as `pending`. It skips existing institution names rather than overwriting them.

```powershell
python -m ingestion.anna_university
```

The command uses the configured `DATABASE_URL` and requires the migrations to be current. See the ingestion guide for what it does and does not establish.

## Tests

Run the non-Selenium project suite:

```powershell
python -m compileall -q app.py init_db.py index.py ingestion tests
python -m pytest -q tests
```

The optional PostgreSQL compatibility test requires a dedicated test database via `TEST_POSTGRESQL_DATABASE_URL`. Do not point that variable at production. Tests in `tests/` use isolated temporary databases or the test-only demo mode; `selenium_tests/` is separate and was not changed.

## Limitations

- The imported 16-name directory is not a statewide engineering catalogue. TNEA did not expose a public structured institution/seat/course export in the pages examined.
- Public college search is database-backed, but recommendations require eligibility and comparable admission data that is not yet available. Cutoff analytics has no records to chart.
- The chatbot interface honestly reports that RAG and an LLM provider are not available. No API credentials, embeddings, or fake answers are included.
- Student authentication is disabled. The database review console is a limited single-admin workflow; the legacy demo portal is not authentication or production admin functionality.
- Deployment compatibility and the live deployment have not been tested. See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md).


## AI chatbot and official-document indexing

The database-mode `/chat` page now has a provider-configurable RAG integration. Configure
`COLLEGEHUB_AI_API_KEY`, `COLLEGEHUB_AI_BASE_URL`, `COLLEGEHUB_AI_CHAT_MODEL`, and
`COLLEGEHUB_AI_EMBEDDING_MODEL` in the server environment. The provider must implement
OpenAI-compatible `/embeddings` and `/chat/completions` endpoints. No key is bundled.

Register an official source in `/admin`, then upload a PDF, HTML, CSV, TXT, or Markdown
document from the same dashboard. The app extracts text, splits it into chunks, generates
embeddings, and stores chunks/vectors in the existing `documents`, `document_versions`,
`document_chunks`, and `embeddings` tables. The original uploaded binary is not retained;
the extracted text and source metadata are stored in the database. PDF extraction requires
`pypdf` (included in requirements).

The chatbot refuses to answer when the AI provider is not configured or no relevant
indexed document is found. Citations show the registered source URL, title, academic year,
and verification status. Documents uploaded through this workflow are marked pending in
chunk metadata; this is not a substitute for reviewing the source or verifying extracted
facts. The current retrieval implementation ranks stored vectors in application memory;
for a large corpus, use a PostgreSQL pgvector distance query and an appropriate vector
index before scaling.

This adds the RAG execution path, not statewide official coverage. You still need to
collect, upload, and review current official prospectuses, seat matrices, cutoff PDFs,
fee schedules, and institution documents. AI provider usage may incur charges.


### TNGASA 2026 directory import

The administrator dashboard includes a bounded importer for the official TNGASA 2026
college-information PDF. It extracts the seven-digit college code, college name, and
district; it stores available NAAC grades as pending accreditation records. The source's
2025 admit percentage, NIRF label and male/female seat-availability text are retained in
provenance notes only. They are deliberately not treated as cutoff marks or programme
seat matrices. The parser fails closed if it cannot extract a plausible statewide list.

Run manually after current migrations:

```powershell
python -m ingestion.tngasa_2026
```

The importer skips existing official college codes and does not overwrite records. New
institutions and accreditation facts remain pending administrator review.
