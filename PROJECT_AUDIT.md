# CollegeHub project audit

Audit scope: checked the tracked Flask application, bundled SQLite database, templates, static assets, tests, entry point, README, and visible top-level deployment files on 2026-11-19. The existing untracked `selenium_tests/` tree was preserved. The linked live homepage rendered during the initial audit; this does not verify a deployment of local changes.

## Existing architecture

- Single Flask application in `app.py`; Jinja templates in `templates/`; vanilla CSS and JavaScript in `static/`.
- `index.py` exports the Flask app. No `vercel.json`, container definition, or deployment pipeline is present in the project root.
- SQLite in `sample_colleges.db`; `init_db.py` adds tables, columns, and indexes using additive/idempotent SQLite DDL and data inserts.
- Public database connections are read-only. Local demonstration admin handlers open a writable SQLite connection; writes are disabled on Vercel/read-only environments.
- Requirements contain Flask only. There is no PostgreSQL driver or adapter.

## Existing functionality

- Home, stream overview/guidance, college directory and profile, comparison, FAQ/chat, demo student portal, demo admin CRUD/verification, and a health endpoint.
- Directory search/filtering, browser-local favorites and comparisons, and pagination.
- SQL data values are generally parameterized. Admin record table/field names are selected from a fixed server-side mapping.
- Verification metadata and source links exist for several record types.
- Existing UI already has responsive layouts, keyboard focus styling, reduced-motion handling, empty states, and a shared CollegeHub theme.

## Database snapshot

The bundled database contains 8 college rows, 10 course rows, and 14 facility rows. At audit time, fee, cutoff, hostel, information-source, and verification-record tables had zero rows. The sample college and course values are explicitly described as fictional in the README and UI. Therefore verified fee/cutoff charts are expected to be empty until sourced records are entered.

Existing tables include streams, colleges, courses, facilities, fees, cutoffs, hostel information, information sources, verification records, guidance, FAQs, academic years, districts, demo student profiles, and feedback.

## Problems and risks

- Student/admin access is a demo flow: submitted admin credentials are not authenticated, and student passwords are not stored or checked. This is not a production identity system.
- Local admin form handlers do not currently use CSRF tokens. Admin is now denied on Vercel/read-only deployments, but the local admin remains demo-only.
- A development fallback session key existed. Deployed environments now fail fast unless `COLLEGEHUB_SECRET_KEY` is configured; cookie HttpOnly/SameSite settings are enabled, and Secure is enabled for production Vercel or explicit secure-cookie configuration. Flask's interactive debugger is no longer enabled by default.
- SQLite writes on serverless filesystems cannot provide durable persistence. No PostgreSQL integration or provider configuration exists.
- There is no dedicated activity log table/workflow. Independent source CRUD is incomplete; verification actions create source metadata.
- Chat is deterministic and is not an LLM/RAG system. No current verified cutoff or fee datasets are present.
- Directory fees previously could include unverified/nonannual rows; this audit's implementation now restricts fee ranges and fee sorting/comparison to verified annual-labelled fee rows.
- Some source or data records may be absent, stale, or unverified. A source URL alone does not establish that a record is accurate.
- No complete automated deployment check or live release verification is available from the local checkout.

## Implemented in this change

- Added preference-based recommendation ranking with per-preference reasons and explicit unknown-data explanations.
- Added cutoff record filters and an accessible bar visualization restricted to verified records with source, year, verification date, and numeric cutoff.
- Added facility filtering and verified annual-fee sorting/filtering to the directory; these filters persist through pagination.
- Restricted deployed admin endpoints and login to read-only behavior, added cookie flags, and required a configured secret for deployed sessions.
- Added audit, deployment, and implementation documentation plus a blank-secret `.env.example`.

## Proposed improvements and remaining work

1. Replace demo student/admin flows with a tested authentication provider, role-based authorization, CSRF protection, and account lifecycle controls before any production use.
2. Introduce a PostgreSQL-backed repository/connection layer, explicit migrations, and a persistent provider before allowing production edits.
3. Add independently managed sources and durable administrative activity logs.
4. Validate and curate official college, course, fee, hostel, cutoff, and eligibility data with owner-approved sources.
5. Add workflow/authorization/integration tests for any future persistent user data and administrative workflows.
6. Add a verified live deployment pipeline and test the deployed version separately from a Git push.

## Deployment limitations

The current Vercel entry point is `index.py`; the bundled database is suitable only as read-only demo content. Vercel environment variables must include a strong `COLLEGEHUB_SECRET_KEY` or the new app will intentionally fail during import. The live URL was observed rendering before local changes, but this checkout has not been deployed and the live site does not contain these local changes. No persistent database provider, PostgreSQL adapter, or end-to-end deployment configuration is included.
