from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger


def configure_logging(output_dir: str | Path = "outputs/logs") -> Path:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    log_file = path / f"{datetime.now():%Y%m%d_%H%M%S}.log"
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")
    logger.add(log_file, level="DEBUG")
    return log_file
