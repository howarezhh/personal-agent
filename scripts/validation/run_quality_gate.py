"""Run the project validation checks from a single entrypoint."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def run_command(command: list[str], *, cwd: Path | None = None) -> int:
    print(f"[RUN] {' '.join(command)}")
    completed = subprocess.run(command, cwd=cwd or PROJECT_ROOT, check=False)
    return completed.returncode


def resolve_npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run project quality gates.")
    parser.add_argument("--skip-backend-tests", action="store_true")
    parser.add_argument("--skip-frontend-typecheck", action="store_true")
    parser.add_argument("--skip-frontend-lint", action="store_true")
    parser.add_argument("--skip-openapi-drift", action="store_true")
    parser.add_argument("--skip-import-cycles", action="store_true")
    parser.add_argument("--skip-migration-guard", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    npm = resolve_npm()

    checks: list[tuple[str, list[str], Path]] = []
    if not args.skip_openapi_drift:
        checks.append(("OpenAPI drift", [sys.executable, "scripts/validation/check_openapi_drift.py"], PROJECT_ROOT))
    if not args.skip_import_cycles:
        checks.append(("Import cycles", [sys.executable, "scripts/validation/check_import_cycles.py"], PROJECT_ROOT))
    if not args.skip_migration_guard:
        checks.append(("Migration guard", [sys.executable, "scripts/validation/check_migration_guard.py"], PROJECT_ROOT))
    if not args.skip_backend_tests:
        checks.append(("Backend tests", [sys.executable, "-m", "pytest", "backend/tests", "-q"], PROJECT_ROOT))
    if not args.skip_frontend_typecheck:
        checks.append(("Frontend typecheck", [npm, "exec", "--", "tsc", "-p", "tsconfig.json", "--noEmit"], FRONTEND_ROOT))
    if not args.skip_frontend_lint:
        checks.append(("Frontend lint", [npm, "run", "lint"], FRONTEND_ROOT))

    if (not args.skip_frontend_typecheck or not args.skip_frontend_lint) and not npm:
        raise SystemExit("npm was not found in PATH. Please install Node.js or configure PATH first.")

    failures: list[str] = []
    for label, command, cwd in checks:
        print(f"\n== {label} ==")
        if run_command(command, cwd=cwd) != 0:
            failures.append(label)

    if failures:
        print("\nQuality gate failed:")
        for label in failures:
            print(f" - {label}")
        return 1

    print("\nQuality gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
