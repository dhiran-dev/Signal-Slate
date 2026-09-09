"""Standalone CLI for database connection verification."""

import sys

from signal_slate.db import check_database_connection


def main() -> int:
    result = check_database_connection()
    if result["status"] == "ok":
        print(
            f"[OK] Database connection verified: {result['version']} "
            f"(db: {result['database']}, user: {result['user']})"
        )
        return 0
    else:
        print(f"[FAIL] Database connection failed: {result.get('message', 'Unknown error')}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
