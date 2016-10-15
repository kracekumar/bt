# -*- coding: utf-8 -*-

import os
import logging

logger = None

def get_loglevel():
    loglevel = os.environ.get('loglevel', 'info')
    if loglevel.lower() == 'info':
        return logging.INFO
    elif loglevel.lower() == 'debug':
        return logging.DEBUG
    # TODO: Warn user
    return logging.INFO

class Logger:
    def info(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

def get_logger():
    global logger
    if logger:
        level = get_loglevel()
        logger.setLevel(level)
        return logger
    logger = logging.getLogger()
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    level = get_loglevel()
    logger.setLevel(level)
    return logger
    return Logger()
