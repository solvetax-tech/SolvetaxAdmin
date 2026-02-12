import logging
import os
from logging.handlers import RotatingFileHandler


class ContextFilter(logging.Filter):
    def filter(self, record):
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        if not hasattr(record, "emp_id"):
            record.emp_id = "-"
        return True


def initialize_logger() -> logging.Logger:
    log_folder = "logs"
    os.makedirs(log_folder, exist_ok=True)

    log_file = os.path.join(log_folder, "application.log")

    logger = logging.getLogger("FastAPIApp")
    logger.setLevel(logging.INFO)

    log_format = (
        "%(asctime)s | %(levelname)s | "
        "request_id=%(request_id)s | "
        "emp_id=%(emp_id)s | "
        "%(message)s"
    )

    formatter = logging.Formatter(log_format)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addFilter(ContextFilter())
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.propagate = False

    return logger


logger = initialize_logger()
