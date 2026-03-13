from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)


def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: run test in asyncio event loop")


def pytest_pyfunc_call(pyfuncitem):
    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None

    funcargs = {
        name: pyfuncitem.funcargs[name]
        for name in pyfuncitem._fixtureinfo.argnames
        if name in pyfuncitem.funcargs
    }
    asyncio.run(pyfuncitem.obj(**funcargs))
    return True
