# Database migration and existing-data safety

## Migration history

Versioned revisions live under `alembic/versions/`. The initial revision creates the universal schema in PostgreSQL's dedicated `collegehub` schema, stores Alembic's version table there, enables pgvector where needed, and seeds only fixed lookup values. The additive revision `b7c41e98f2ad` adds an `unknown` institution type so sourced records are not assigned an invented ownership classification. Its downgrade intentionally leaves the lookup value in place to avoid deleting data.

The current configured Neon schema is at `b7c41e98f2ad`. Its 38 application tables are separate from the pre-existing `public.playing_with_neon` table. The latest live Alembic metadata check found no pending schema changes.

## Safe workflow

1. Inspect the database URL without printing it.
2. Back up the target.
3. Inspect `alembic history`, `alembic current`, `alembic check`, and every pending revision.
4. Confirm the preflight targets `collegehub` and that no public or legacy SQLite objects are being migrated.
5. Apply only reviewed, additive revisions.
6. Re-check the revision and table inventory.

Alembic is never run automatically during application startup. Do not downgrade a production schema without a separately reviewed recovery plan. The initial downgrade removes the universal tables and therefore may remove data.

## SQLite safety

The default SQLite database is `instance/collegehub.sqlite3`, separate from `sample_colleges.db`. Alembic refuses to apply the universal schema to a legacy SQLite database containing conflicting application tables without its own Alembic version marker. No legacy database is automatically converted or overwritten.

Run local upgrade/downgrade coverage with:

```powershell
python -m pytest -q tests/test_universal_database.py
```

The legacy preservation test copies the bundled database to a temporary directory and compares its record counts before and after the migration refusal.

## Import safety

The Anna University directory importer writes only to the configured universal database. It records source URL, organisation, document title, fetched-page hash, collection date, job result, and pending provenance. It skips exact existing institution names rather than overwriting them. It does not import the fictional SQLite sample records, infer missing fields, or mark imported information verified.
