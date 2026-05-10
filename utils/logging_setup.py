import logging
import sys
from pathlib import Path

_LOGGING_CONFIGURED = False


def setup_logging() -> logging.Logger:
    global _LOGGING_CONFIGURED
    logger = logging.getLogger("nba_chatbot")

    if _LOGGING_CONFIGURED:
        return logger
    _LOGGING_CONFIGURED = True

    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console)

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(
        str(log_dir / "nba_chatbot.log"), mode="a", encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s",
        )
    )
    logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("nba_chatbot")
