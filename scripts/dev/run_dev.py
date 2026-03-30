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


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = PROJECT_ROOT / "frontend"


def resolve_project_python() -> str:
    """优先使用项目虚拟环境解释器，避免从系统 Python 启动后端时缺少依赖。"""

    if os.name == "nt":
        venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    else:
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"

    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def build_runtime_env(*, app_env: str) -> dict[str, str]:
    """为子进程构造接近“已激活虚拟环境”的运行环境。"""

    env = os.environ.copy()
    env["APP_ENV"] = app_env

    if os.name == "nt":
        venv_bin_dir = PROJECT_ROOT / ".venv" / "Scripts"
    else:
        venv_bin_dir = PROJECT_ROOT / ".venv" / "bin"

    if venv_bin_dir.exists():
        env["VIRTUAL_ENV"] = str(venv_bin_dir.parent)
        env["PATH"] = f"{venv_bin_dir}{os.pathsep}{env.get('PATH', '')}"

    return env


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start backend and frontend together.")
    parser.add_argument("--app-env", default=os.environ.get("APP_ENV", "development"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    # 前端开发服务默认监听 3000，和 `frontend/vite.config.ts` 保持一致，避免清理旧进程时遗漏真实端口。
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--reload", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--frontend-script", default="dev")
    parser.add_argument(
        "--sync-contracts",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export backend OpenAPI and regenerate frontend contracts before startup.",
    )
    parser.add_argument(
        "--stop-on-frontend-exit",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Stop backend too when frontend exits. Disabled by default to keep backend alive.",
    )
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
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            process.wait(timeout=5)
            return

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


def sync_contracts(*, backend_python: str, npm: str, env: dict[str, str]) -> int:
    """启动开发环境前同步 OpenAPI 与前端生成契约。"""

    print("[run_dev] Syncing backend OpenAPI schema...")
    export_result = subprocess.run(
        [backend_python, "scripts/contracts/export_openapi.py"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
    )
    if export_result.returncode != 0:
        print(f"[run_dev] OpenAPI export failed with code {export_result.returncode}.")
        return export_result.returncode

    print("[run_dev] Regenerating frontend contracts...")
    contract_result = subprocess.run(
        [npm, "run", "generate:contracts"],
        cwd=FRONTEND_ROOT,
        env=env,
        check=False,
    )
    if contract_result.returncode != 0:
        print(f"[run_dev] Frontend contract generation failed with code {contract_result.returncode}.")
        return contract_result.returncode

    return 0


def main() -> int:
    args = build_parser().parse_args()
    npm = resolve_npm()
    if not npm:
        raise SystemExit("npm was not found in PATH. Please install Node.js or configure PATH first.")

    backend_python = resolve_project_python()
    env = build_runtime_env(app_env=args.app_env)

    if args.sync_contracts:
        sync_code = sync_contracts(backend_python=backend_python, npm=npm, env=env)
        if sync_code != 0:
            return sync_code

    cleanup_stale_processes(backend_port=args.port, frontend_port=args.frontend_port)

    backend_command = [
        backend_python,
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

    print(f"[run_dev] Backend Python: {backend_python}")
    print(f"[run_dev] Backend auto reload: {'enabled' if args.reload else 'disabled'}")
    print(f"[run_dev] Frontend script: {args.frontend_script}")

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
            frontend_code = frontend_process.poll() if frontend_process is not None else None

            if backend_code is not None:
                print(f"[run_dev] Backend exited with code {backend_code}. Stopping launcher.")
                stop_process(frontend_process)
                frontend_process = None
                return backend_code

            if frontend_process is not None and frontend_code is not None:
                print(f"[run_dev] Frontend exited with code {frontend_code}.")
                if args.stop_on_frontend_exit:
                    print("[run_dev] --stop-on-frontend-exit is enabled; stopping backend too.")
                    stop_process(backend_process)
                    backend_process = None
                    return frontend_code

                print("[run_dev] Backend will keep running. Press Ctrl+C to stop it manually.")
                frontend_process = None

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
