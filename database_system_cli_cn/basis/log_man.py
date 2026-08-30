"""Pure-Python reconstruction of ``basis.log_man``."""

import multiprocessing
import os
import time

from loguru import logger

from basis.constant import ts2db_config


timestamp = time.strftime("%Y%m%d-%H-%M-%S")
process_name = multiprocessing.current_process().name
logger_file = (
    f"{ts2db_config.log_path}/running_log_{timestamp}"
    f"_pid_{os.getpid()}_{process_name}.log"
)
logger.add(
    logger_file,
    rotation="100MB",
    retention="365 days",
    encoding="utf-8",
    enqueue=True,
)
logging = logger


class Start_loggings:
    __instance = None

    def __new__(cls, *args, **kwargs):
        del args, kwargs
        if cls.__instance is None:
            cls.__instance = super().__new__(cls)
        return cls.__instance

    @staticmethod
    def info(msg):
        logger.info(msg)

    @staticmethod
    def debug(msg):
        logger.debug(msg)

    @staticmethod
    def warning(msg):
        logger.warning(msg)

    @staticmethod
    def error(msg):
        logger.error(msg)

    @staticmethod
    def success(msg):
        logger.success(msg)
