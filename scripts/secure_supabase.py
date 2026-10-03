"""Apply the reviewed Data API protection SQL only with an explicit flag."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Revoke browser access and enable RLS on Career tables"
    )
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "deploy" / "supabase-security.sql"
    if not args.apply:
        print(
            "Preview only: deploy/supabase-security.sql; add --apply after reviewing the dedicated project target."
        )
        return
    from career.db import engine

    if engine.dialect.name != "postgresql":
        raise SystemExit("This protection applies only to PostgreSQL/Supabase.")
    try:
        with engine.connect() as connection:
            # The reviewed SQL body contains PostgreSQL format('%I', ...), not
            # DBAPI bind placeholders. Omit parameters so psycopg preserves it.
            connection.exec_driver_sql(
                path.read_text(encoding="utf-8"), execution_options={"no_parameters": True},
            )
            connection.commit()
    except Exception as error:
        raise SystemExit("Protection failed: " + type(error).__name__) from None
    print("Career table browser access revoked; RLS enabled. Application rows unchanged.")


if __name__ == "__main__":
    main()
