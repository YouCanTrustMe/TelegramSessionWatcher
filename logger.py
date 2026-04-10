import logging
import os
from datetime import datetime
from config import LOGS_DIR


class DailyFileHandler(logging.Handler):
    """Writes to data/logs/YYYY/MM/YYYY-MM-DD.log, rotating at midnight."""

    def __init__(self, encoding="utf-8"):
        super().__init__()
        self.encoding = encoding
        self._current_date = None
        self._stream = None
        self.formatter = None

    def _get_stream(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            if self._stream:
                self._stream.close()
            now = datetime.now()
            log_dir = os.path.join(LOGS_DIR, str(now.year), f"{now.month:02d}")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{today}.log")
            self._stream = open(log_file, "a", encoding=self.encoding)
            self._current_date = today
        return self._stream

    def emit(self, record):
        try:
            msg = self.format(record)
            stream = self._get_stream()
            stream.write(msg + "\n")
            stream.flush()
            try:
                os.fsync(stream.fileno())
            except OSError:
                pass
        except Exception:
            self.handleError(record)

    def close(self):
        if self._stream:
            self._stream.close()
            self._stream = None
        super().close()


_shared_file_handler = None
_shared_console_handler = None


def get_logger(name: str) -> logging.Logger:
    global _shared_file_handler, _shared_console_handler

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    if _shared_file_handler is None:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        _shared_file_handler = DailyFileHandler()
        _shared_file_handler.setFormatter(formatter)
        _shared_console_handler = logging.StreamHandler()
        _shared_console_handler.setFormatter(formatter)

    logger.addHandler(_shared_file_handler)
    logger.addHandler(_shared_console_handler)

    return logger