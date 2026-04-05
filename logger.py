import logging
import os
from datetime import datetime
from config import LOGS_DIR

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    now = datetime.now()
    log_dir = os.path.join(LOGS_DIR, str(now.year), f"{now.month:02d}")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{now.strftime('%Y-%m-%d')}.log")

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger