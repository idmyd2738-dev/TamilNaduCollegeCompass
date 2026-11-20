# CollegeHub implementation report

Date: 19 November 2026.

## Delivered

- Database-mode public pages now query the universal database instead of the fictional bundled SQLite database.
- Directory, institution profile, comparison, and typed admission-record pages use SQLAlchemy models and repository/service queries.
- Institution and programme APIs include total/limit/offset information; admission and placement APIs expose sourced data and verification status.
- Health status checks the configured database connection.
- Canned chat, student accounts, and legacy SQLite admin routes are disabled in database mode. An optional single-admin SQL-backed review console requires `COLLEGEHUB_ADMIN_PASSWORD_HASH` and `COLLEGEHUB_SECRET_KEY`; it includes CSRF-protected source registration, provenance review, and the bounded Anna University import.
- Added an additive `unknown` institution-type lookup migration.
- Added a restricted Anna University source-specific ingestion pipeline and imported 16 constituent-college directory entries as pending verification.
- Updated project, database, migration, deployment, and data-ingestion documentation.

## Live data evidence

The Anna University directory was fetched from `https://www.annauniv.edu/constituent_colleges.php`; all 16 numbered college rows and their linked websites were extracted. The Neon `collegehub` schema now records the source, fetched-content SHA-256 reference, one completed import job, and 16 pending institution/provenance rows. Districts, cities, programme details, fees, admissions, placement figures, and verification dates were not present in the extracted directory and remain null or absent.

TNEA, Tamil Nadu Medical Selection Committee, TANUVAS, TNAU, and TNGASA pages were also investigated. No additional facts were imported from them in this iteration. Further source findings and access limitations are in `docs/OFFICIAL_DATA_INGESTION.md`.

## Not delivered / not claimed

- Full statewide official coverage across all four categories.
- Complete source registry and generalized HTML/PDF/CSV ingestion or conflict resolution. The admin review console is limited to the supported factual record types and does not provide user roles, MFA, individual reviewer identity, or rate limiting.
- Admission-likelihood/recommendation engine, cutoff chart analytics, fee/placement datasets, or comparison of those unavailable values.
- AI chatbot, embeddings, RAG, or citation validation.
- Organizational admin identity and authorization, and student identity.
- Vercel compatibility, successful deployment, push, or deployment readiness.

These features remain explicitly unavailable rather than being represented by mock data or canned answers.

## Validation

- `.venv\Scripts\python.exe -m pytest -q tests`: 35 passed, 1 skipped, 20 subtests passed.
- Python compilation passed.
- The database admin login, CSRF guard, dashboard, and provenance-review flow passed an isolated SQLite test.
- Live `alembic check` passed at revision `b7c41e98f2ad`.
- Live Neon public-route and JSON API smoke tests passed against the 16 imported institution records.
- ORM CRUD and transaction rollback smoke test passed; no validation college records remain.
- The optional automated PostgreSQL compatibility suite was skipped because a separate test-only PostgreSQL database URL was not configured.
- No deployment or push was performed. `selenium_tests/` and `public.playing_with_neon` were not modified.
