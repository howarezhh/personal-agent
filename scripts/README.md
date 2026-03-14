# Scripts Layout

统一后的脚本目录如下：

- `scripts/dev/`
  - 本地开发启动脚本
  - `run_backend.py`
  - `run_frontend.py`
  - `run_dev.py`
- `scripts/contracts/`
  - 契约导出脚本
  - `export_openapi.py`
- `scripts/validation/`
  - 工程治理校验脚本
  - `check_openapi_drift.py`
  - `check_import_cycles.py`
  - `check_migration_guard.py`
  - `run_quality_gate.py`

约束：

- `scripts/` 目录只存放可执行脚本源码
- 运行产物不得落在 `scripts/` 下
- 日志应写入根目录 `logs/` 或 `.alogs/`
- 数据产物应写入根目录 `data/`
- 缓存文件应写入项目级缓存目录，不得写入 `scripts/__pycache__/` 以外的自定义位置
- 当前 `scripts/.alogs/`、`scripts/logs/`、`scripts/data/` 属于历史遗留运行产物，不属于脚本源码目录
