# CollegeHub deployment guide

## Current deployment model

The existing application entry point is `index.py`, which exports `app` from `app.py`. The application reads `sample_colleges.db` as a bundled, read-only demo database for public pages. It is not safe to use local SQLite writes as durable storage in Vercel serverless functions. The current repository does not include PostgreSQL integration or a configured persistent database provider.

## Required environment settings

Configure these values in the deployment provider, not in source control:

- `COLLEGEHUB_SECRET_KEY`: required for Vercel/deployed app startup. Generate a unique random secret for each environment and store it in the provider's secret settings.
- `COLLEGEHUB_READ_ONLY=1`: optional outside Vercel to disable all local SQLite admin writes.
- `COLLEGEHUB_SECURE_COOKIES=1`: enable Secure session cookies when the app is served over HTTPS outside production Vercel.

Never commit a real `.env` file or secret. `.env.example` contains blank placeholders only.

## Vercel

1. Import the existing Git repository and preserve its Python entry point.
2. Set `COLLEGEHUB_SECRET_KEY` in Vercel project settings before deploying. Without it, the application intentionally raises a startup error.
3. Keep the application read-only. The sample SQLite file is demo content and serverless filesystem changes are not durable.
4. Deploy and inspect build/runtime logs.
5. Separately smoke-test `/`, `/colleges`, `/recommendations`, `/cutoffs`, `/health`, and confirm `/admin` returns service unavailable. A successful Git push alone does not confirm deployment.

## Before production use

- Integrate a persistent PostgreSQL provider and an application database adapter; no such integration exists yet.
- Implement real identity, authorization, CSRF protection, audit logging, and backups.
- Curate and independently verify college and admission records. Do not mark records verified without a source, academic year, and verification date.
- Re-test the deployed instance, including session behavior across serverless instances and all database paths.

## Local development

Follow the Windows PowerShell instructions in `README.md`. `python init_db.py` performs additive SQLite schema updates for the local demo. The admin portal is intentionally local-only and is not a secure production admin system.

## Current release note

The linked live page was reachable when the local audit began. The working-tree changes described in `IMPLEMENTATION_REPORT.md` have not been deployed by this guide; deployment status for those changes must be confirmed after a future deployment.
