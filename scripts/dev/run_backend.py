"""PyCharm-friendly backend launcher."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start the FastAPI backend with uvicorn.")
    parser.add_argument("--app-env", default=os.environ.get("APP_ENV", "development"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env = os.environ.copy()
    env["APP_ENV"] = args.app_env

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:app",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]
    if args.reload:
        command.append("--reload")

    return subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
