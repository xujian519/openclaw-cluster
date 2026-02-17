"""
OpenClaw 集群系统 - 日志管理

提供结构化日志功能
"""
import sys
import logging
from typing import Any
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """JSON 格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON"""
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加异常信息
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # 添加额外字段
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)

        import json
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    format_type: str = "json",
    output: str = "./logs"
):
    """
    设置日志系统

    Args:
        level: 日志级别
        format_type: 格式类型 (json 或 text)
        output: 输出路径
    """
    # 创建日志目录
    from pathlib import Path
    Path(output).mkdir(parents=True, exist_ok=True)

    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除现有处理器
    root_logger.handlers.clear()

    # 创建格式化器
    if format_type == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 文件处理器
    log_file = f"{output}/openclaw.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    获取日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        日志记录器
    """
    return logging.getLogger(name)


class LoggerContext:
    """日志上下文管理器，用于添加额外字段"""

    def __init__(self, logger: logging.Logger, **extra_fields):
        self.logger = logger
        self.extra_fields = extra_fields

    def __enter__(self):
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.extra_fields = self.extra_fields
            return record

        logging.setLogRecordFactory(record_factory)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 恢复旧的记录工厂
        pass


# 自动设置日志（如果还没设置）
if not logging.getLogger().handlers:
    setup_logging()
