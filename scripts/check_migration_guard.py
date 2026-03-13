"""Guard schema/model changes with SQL migrations."""

from __future__ import annotations

import os
import subprocess
import sys


def git_diff_names(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fallback = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"], capture_output=True, text=True)
        return [line.strip() for line in fallback.stdout.splitlines() if line.strip()]
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    base_ref = os.environ.get("MIGRATION_BASE", os.environ.get("GITHUB_BASE_REF", "HEAD~1"))
    changed = git_diff_names(base_ref)
    schema_related = [
        path for path in changed
        if path.startswith("backend/models/")
        or path.startswith("backend/database/schemas/")
        or path.startswith("backend/database/repositories/")
    ]
    migrations = [path for path in changed if path.startswith("backend/database/migrations/") and path.endswith(".sql")]

    if schema_related and not migrations:
        print("Schema/model changes detected without SQL migration file:")
        for path in schema_related:
            print(f" - {path}")
        print("Add a file under backend/database/migrations/*.sql")
        return 1

    print("Migration guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
