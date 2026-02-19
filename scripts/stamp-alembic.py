#!/usr/bin/env python3
"""One-time script to stamp alembic_version to the consolidated initial schema."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from winerank.config import get_settings
from winerank.common.db import get_engine

TARGET_REVISION = "1cff6e8d6528"


def main():
    """Update alembic_version table to point to the single initial revision."""
    settings = get_settings()
    engine = get_engine()
    
    # Convert SQLAlchemy URL to psycopg format if needed
    connection_string = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    
    import psycopg
    
    with psycopg.connect(connection_string) as conn:
        with conn.cursor() as cur:
            # Check current version
            cur.execute("SELECT version_num FROM alembic_version")
            current = cur.fetchone()
            if current:
                current_rev = current[0]
                print(f"Current Alembic revision: {current_rev}")
                
                if current_rev == TARGET_REVISION:
                    print(f"Already at target revision {TARGET_REVISION}. No update needed.")
                    return
                
                # Update to target revision
                cur.execute(
                    "UPDATE alembic_version SET version_num = %s WHERE version_num = %s",
                    (TARGET_REVISION, current_rev)
                )
                conn.commit()
                print(f"✅ Updated Alembic revision from {current_rev} to {TARGET_REVISION}")
            else:
                # No version recorded, insert it
                cur.execute(
                    "INSERT INTO alembic_version (version_num) VALUES (%s)",
                    (TARGET_REVISION,)
                )
                conn.commit()
                print(f"✅ Set Alembic revision to {TARGET_REVISION}")


if __name__ == "__main__":
    main()
