"""Apply migrations/NNN_*.sql in order. Each file runs in autocommit (continuous aggregates
cannot be created inside a transaction). Applied files are tracked in public.schema_migrations."""
from pathlib import Path

import psycopg

from app.config import get_settings

MIGRATIONS = Path(__file__).parent / "migrations"


def main() -> None:
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS public.schema_migrations (name text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
        done = {r[0] for r in conn.execute("SELECT name FROM public.schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            print(f"applying {path.name}")
            conn.execute(path.read_text())
            conn.execute("INSERT INTO public.schema_migrations (name) VALUES (%s)", (path.name,))
    print("migrations up to date")


if __name__ == "__main__":
    main()
