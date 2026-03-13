"""One-click launcher for backend and frontend in PyCharm."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start backend and frontend together.")
    parser.add_argument("--app-env", default=os.environ.get("APP_ENV", "development"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=3001)
    parser.add_argument("--reload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--frontend-script", default="dev")
    return parser


def resolve_npm() -> str:
    return shutil.which("npm.cmd") or shutil.which("npm") or ""


def creationflags() -> int:
    if os.name == "nt":
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def _list_listening_pids(port: int) -> set[int]:
    if os.name == "nt":
        result = _run_command(["netstat", "-ano", "-p", "tcp"])
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            if "LISTENING" not in line:
                continue
            if f":{port}" not in line:
                continue
            match = re.search(r"(\d+)\s*$", line)
            if match:
                pids.add(int(match.group(1)))
        return pids

    result = _run_command(["lsof", "-ti", f"tcp:{port}"])
    return {int(item) for item in result.stdout.splitlines() if item.strip().isdigit()}


def stop_pid(pid: int) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            return

        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def cleanup_stale_processes(*, backend_port: int, frontend_port: int | None = None) -> None:
    current_pid = os.getpid()
    stale_pids = {pid for pid in _list_listening_pids(backend_port) if pid != current_pid}
    if frontend_port is not None:
        stale_pids.update(pid for pid in _list_listening_pids(frontend_port) if pid != current_pid)

    for pid in stale_pids:
        stop_pid(pid)

    if stale_pids:
        time.sleep(1)


def stop_process(process: subprocess.Popen[bytes] | subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return

    try:
        if os.name == "nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()
        process.wait(timeout=5)
        return
    except Exception:
        pass

    try:
        process.terminate()
        process.wait(timeout=5)
        return
    except Exception:
        pass

    process.kill()
    process.wait(timeout=5)


def main() -> int:
    args = build_parser().parse_args()
    npm = resolve_npm()
    if not npm:
        raise SystemExit("npm was not found in PATH. Please install Node.js or configure PATH first.")

    env = os.environ.copy()
    env["APP_ENV"] = args.app_env

    cleanup_stale_processes(backend_port=args.port, frontend_port=args.frontend_port)

    backend_command = [
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
        backend_command.append("--reload")

    frontend_command = [npm, "run", args.frontend_script]

    backend_process: subprocess.Popen[str] | None = None
    frontend_process: subprocess.Popen[str] | None = None

    try:
        backend_process = subprocess.Popen(
            backend_command,
            cwd=PROJECT_ROOT,
            env=env,
            creationflags=creationflags(),
        )
        frontend_process = subprocess.Popen(
            frontend_command,
            cwd=FRONTEND_ROOT,
            env=env,
            creationflags=creationflags(),
        )

        while True:
            backend_code = backend_process.poll()
            frontend_code = frontend_process.poll()
            if backend_code is not None or frontend_code is not None:
                stop_process(frontend_process)
                stop_process(backend_process)
                return backend_code if backend_code is not None else frontend_code or 0
            time.sleep(1)
    except KeyboardInterrupt:
        stop_process(frontend_process)
        stop_process(backend_process)
        return 130
    finally:
        stop_process(frontend_process)
        stop_process(backend_process)


if __name__ == "__main__":
    raise SystemExit(main())
