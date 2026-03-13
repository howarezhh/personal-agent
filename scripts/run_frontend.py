"""PyCharm-friendly frontend launcher."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def resolve_npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the Vite frontend dev server.")
    parser.add_argument("--script", default="dev")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    npm = resolve_npm()
    if not npm:
        raise SystemExit("npm was not found in PATH. Please install Node.js or configure PATH first.")

    command = [npm, "run", args.script]
    return subprocess.run(command, cwd=FRONTEND_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
