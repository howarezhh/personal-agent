import types

from backend.utils import logger as logger_module


class _FakeStream:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kwargs):
        self.calls.append(kwargs)


def test_ensure_utf8_stdio_reconfigures_streams(monkeypatch):
    stdout = _FakeStream()
    stderr = _FakeStream()
    monkeypatch.setattr(logger_module.sys, 'stdout', stdout)
    monkeypatch.setattr(logger_module.sys, 'stderr', stderr)

    logger_module._ensure_utf8_stdio()

    assert stdout.calls == [{'encoding': 'utf-8', 'errors': 'replace'}]
    assert stderr.calls == [{'encoding': 'utf-8', 'errors': 'replace'}]


def test_ensure_windows_utf8_code_page_sets_console_code_pages(monkeypatch):
    calls = []

    class _FakeKernel32:
        def SetConsoleOutputCP(self, code_page):
            calls.append(('output', code_page))

        def SetConsoleCP(self, code_page):
            calls.append(('input', code_page))

    fake_ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(kernel32=_FakeKernel32()))

    monkeypatch.setattr(logger_module.os, 'name', 'nt')
    monkeypatch.setitem(__import__('sys').modules, 'ctypes', fake_ctypes)

    logger_module._ensure_windows_utf8_code_page()

    assert calls == [('output', 65001), ('input', 65001)]
