-- Unreleased

## Wine entity and schema (initial)

- **Wine** model and `wines` table now include:
  - **list_identifier** – internal wine ID from the list (e.g. bin number, SKU, list code).
  - **designation** – special title (Reserve, Estate Bottled, Grand Cru, Grand Vin, etc.).
  - **region** – meaning clarified: broad area (e.g. California, Bordeaux).
  - **sub_region** – nested area (e.g. Sonoma County).
  - **appellation** – legal geographic designation, AVA/AOC/DOC (e.g. Russian River Valley).
- No new Alembic revision: changes are in the single initial schema `1cff6e8d6528`.
- If your database was already created with the previous schema and you have no wines: either run `alembic downgrade base` then `alembic upgrade head` to recreate all tables with the new Wine columns, or drop and recreate the database and run `alembic upgrade head`.

## Alembic: single initial schema (dev)

- All migrations were squashed into one revision: `1cff6e8d6528_initial_schema`.
- Removed revisions: `399b50454181`, `a1b2c3d4e5f6`, `b3e1f9a72c04`.
- **If your dev DB was already migrated** with the old chain, update the stored revision once:
  - `uv run winerank db stamp` (recommended), or
  - `psql "$WINERANK_DATABASE_URL" -c "UPDATE alembic_version SET version_num = '1cff6e8d6528';"`
  - Or drop and recreate the database, then run `alembic upgrade head`.
- **`winerank db stamp`** – New CLI command to set `alembic_version` to head without running migrations; documented in README (Database Management).