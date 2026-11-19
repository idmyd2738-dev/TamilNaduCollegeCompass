# CollegeHub

CollegeHub is a Flask/Jinja2/SQLite prototype for exploring Tamil Nadu college streams, sample records, and general admission guidance. College and course records are fictional demo data; the site is not an official admissions authority and does not provide production authentication.

## Features

- College directory with search, stream, district, course, category, ownership, facility, hostel, and verified annual-fee filters; sorting and pagination.
- College profiles and browser-local shortlist/comparison.
- Preference recommendations with an explainable data-match score (not admission probability).
- Cutoff record filters and a chart limited to sourced, dated, verified numeric records.
- Deterministic FAQ/chat responses with official links where available; no AI or RAG integration.
- Local-only demo admin CRUD and source/verification workflows.

## Technology and structure

- Python 3.12, Flask, Jinja2, SQLite, vanilla JavaScript, and CSS.
- `app.py` contains routes, read-only public data access, and local demo admin handlers.
- `init_db.py` applies idempotent, additive SQLite schema updates.
- `index.py` exports the Flask application for the existing deployment entry point.
- `templates/`, `static/`, and `tests/` contain UI, assets, and unit/integration tests.

## Local setup (Windows PowerShell)

Run from the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python init_db.py
python app.py
```

Open http://127.0.0.1:5000. The local sample admin portal is a demo, not an authenticated administrator system. Do not enter real credentials or personal information.

## Environment variables

See [.env.example](./.env.example). For local development, the application retains a development-only fallback session key. For Vercel/read-only deployments, set a unique `COLLEGEHUB_SECRET_KEY` in the provider's environment settings; the application fails at startup if it is missing. Set `COLLEGEHUB_SECURE_COOKIES=1` when serving over HTTPS outside Vercel. Set `COLLEGEHUB_DEBUG=1` only for local debugging.

## Database and deployment

The bundled `sample_colleges.db` is opened read-only by public routes. The local admin portal can write to SQLite only outside read-only deployments. Admin access is disabled when `VERCEL`, `VERCEL_ENV`, or `COLLEGEHUB_READ_ONLY=1` is set. Serverless local-file writes are not persistent; the current project does not have a PostgreSQL adapter or database provider configured. Do not use this deployment for persistent production data.

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for deployment settings and limitations. `init_db.py` makes additive changes and preserves existing sample records; it does not run automatically during app import.

## Verification and sample-data policy

Verified records require a source, academic year, and last-verified date. Annual-fee filters use only verified fee records explicitly labelled annual, yearly, or per annum. Cutoff charts require a verified source and numeric value. Missing and unverified values are not fabricated; an empty verified chart is expected until evidence is entered.

## Run tests

From the project directory:

```powershell
python -m compileall -q app.py init_db.py index.py tests
python -m pytest -q
```

`tests/test_app.py` covers routes, filters, comparison, recommendations, cutoff verification, migration idempotence, and local admin CRUD. Selenium checks in `selenium_tests/` are separate browser-level tests and may require a running app and browser driver.

## Known limitations

- Student/admin forms are demo flows; there are no persistent user accounts, password authentication, role management, or production-ready authorization.
- Local admin write forms do not yet have CSRF tokens. The demo admin is disabled on read-only deployments, but the application must not be used as a production admin system.
- PostgreSQL support, a migration framework, server-persisted student data, activity logs, and RAG/LLM integration are not implemented.
- Sample records are fictional and do not provide verified current fees, cutoffs, facilities, or hostel information.
