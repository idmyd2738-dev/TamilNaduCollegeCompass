# CollegeHub deployment guide

## Current deployment status

The Flask entry point is `index.py`. No `vercel.json`, container definition, CI deployment workflow, or live deployment validation was found in the project root. A successful database check or local route test does not establish that the current deployment is compatible or updated.

## Required configuration

Configure these values in the deployment provider, not in source control:

- `COLLEGEHUB_SECRET_KEY`: a unique cryptographically strong Flask session secret. Deployed startup fails if it is missing.
- `DATABASE_URL`: persistent PostgreSQL using `postgresql+psycopg://...`. A deployed app must not rely on the local SQLite fallback.
- `COLLEGEHUB_SECURE_COOKIES=1` when deploying behind HTTPS outside production Vercel.
- `COLLEGEHUB_ADMIN_PASSWORD_HASH` (optional): a Werkzeug password hash to enable the single-administrator review console. Configure it only alongside the session secret and an operational access-control policy.

The demo-mode flag is intentionally ignored by read-only deployments. Do not deploy `COLLEGEHUB_DEMO_MODE=1`. Student authentication is unavailable. The database review console is disabled unless its password hash and session secret are configured; `COLLEGEHUB_READ_ONLY=1` disables the console.

Generate a password hash without echoing the password, then store only the resulting hash in the provider's secret manager:

```powershell
python -c "from getpass import getpass; from werkzeug.security import generate_password_hash; print(generate_password_hash(getpass()))"
```

## Database release steps

1. Back up the target PostgreSQL database.
2. Review the pending migration scripts and confirm that the target schema is the dedicated `collegehub` schema.
3. Apply migrations as an explicit release operation; application startup never migrates automatically.
4. Verify `alembic current`, `alembic check`, `/health`, and representative database-backed pages after release.
5. Confirm that `public.playing_with_neon` remains untouched.

The existing Neon connection was tested, and its dedicated schema is at revision `b7c41e98f2ad`. This does not prove a future deploy or another environment is connected.

## Public application behavior

With `DATABASE_URL` configured, the public explorer, profiles, comparison, recommendation candidate filtering, admission pages, and JSON APIs query the universal database. Empty database results are shown as unavailable information; they do not trigger a fallback to `sample_colleges.db`.

The health endpoint performs a database connection check. The chatbot and student accounts remain unavailable. With explicit credentials, `/admin` provides source registration, the bounded Anna University import, and provenance review. This is a shared-password single-admin console, not a complete user/role system; it lacks MFA, per-user identity, and application-level rate limiting. The legacy SQLite demo and its write routes are never enabled in read-only deployments.

## Before production use

- Validate the selected Python serverless/runtime configuration and static asset handling with a real staging deployment.
- Configure and smoke-test the deployment environment without sharing credentials.
- Add organizational identity, per-user roles, rate limiting, reviewer attribution, audit-log review, backups, and persistent document storage before treating administrative writes as production-ready. The current forms have CSRF checks and write verification history, but are deliberately limited.
- Collect and review more official institutional, programme, admission, fee, and placement data. Current imported records are pending verification and are not a complete statewide catalogue.
- Implement and test the LLM, embedding, document ingestion, retrieval, and citation pipeline before advertising an AI chatbot.

Do not push, merge, or deploy without explicit approval.


## AI chatbot configuration

To enable document indexing and AI answers, configure these server-side environment
variables in addition to the database/session settings:

- `COLLEGEHUB_AI_API_KEY`
- `COLLEGEHUB_AI_BASE_URL` (defaults to `https://api.openai.com/v1`)
- `COLLEGEHUB_AI_CHAT_MODEL`
- `COLLEGEHUB_AI_EMBEDDING_MODEL`
- `COLLEGEHUB_EMBEDDING_DIMENSIONS` (optional dimension assertion)

The provider must expose OpenAI-compatible `/embeddings` and `/chat/completions`
endpoints. Install the updated requirements, including `pypdf`, before enabling PDF
uploads. No API credentials belong in `.env.example` or source control. Document upload
is limited to 15 MB. Uploaded source files are not retained as binary objects; extracted
text/chunks and source metadata are stored in PostgreSQL.
