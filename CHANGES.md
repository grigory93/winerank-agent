-- Unreleased

## Alembic: single initial schema (dev)

- All migrations were squashed into one revision: `1cff6e8d6528_initial_schema`.
- Removed revisions: `399b50454181`, `a1b2c3d4e5f6`, `b3e1f9a72c04`.
- **If your dev DB was already migrated** with the old chain, update the stored revision once:
  - `psql "$WINERANK_DATABASE_URL" -c "UPDATE alembic_version SET version_num = '1cff6e8d6528';"`
  - Or drop and recreate the database, then run `alembic upgrade head`.