import json
import logging

from backend.utils import logger as logger_module
from backend.utils.logger import StructuredFormatter


def test_structured_formatter_keeps_standard_logging_extra_fields():
    record = logging.getLogger("test.logger").makeRecord(
        name="test.logger",
        level=logging.INFO,
        fn=__file__,
        lno=12,
        msg="structured message",
        args=(),
        exc_info=None,
        extra={
            "request_id": "req-1",
            "conversation_id": "conv-1",
            "message_id": "msg-1",
        },
    )

    payload = json.loads(StructuredFormatter().format(record))

    assert payload["message"] == "structured message"
    assert payload["request_id"] == "req-1"
    assert payload["conversation_id"] == "conv-1"
    assert payload["message_id"] == "msg-1"


def test_get_logger_manager_reads_logging_contract_from_config(monkeypatch, tmp_path):
    class StubConfigManager:
        def get_business_config(self, section=None, default=None):
            if section == "logging":
                return {
                    "level": "DEBUG",
                    "format": "json",
                    "output": ["file"],
                    "file": {
                        "directory": str(tmp_path),
                        "rotation": "time",
                        "backup_count": 3,
                        "max_bytes": 2048,
                        "when": "H",
                    },
                }
            return default

    monkeypatch.setattr("backend.core.config_manager.get_config_manager", lambda: StubConfigManager())
    monkeypatch.setattr(logger_module, "_logger_manager", None)

    manager = logger_module.get_logger_manager()

    assert manager.enable_structured is True
    assert manager.enable_console is False
    assert manager.enable_file is True
    assert manager.rotation_type == "time"
    assert manager.backup_count == 3
    assert manager.max_bytes == 2048
    assert manager.when == "H"
    assert manager.log_dir == tmp_path
