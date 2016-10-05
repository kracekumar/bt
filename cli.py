# -*- coding: utf-8 -*-

import os
import logging
import sys
import asyncio
from concurrent.futures import CancelledError

import click
import bencodepy

from bt import Client, get_logger


@click.group()
def cli():
    pass


@click.command()
@click.option('--loglevel', default='info',
              help='info or debug. debug is enlightening')
@click.argument('path')
def download(loglevel, path):
    try:
        os.environ['loglevel'] = loglevel
        logger = get_logger()
        loop = asyncio.get_event_loop()
        client = Client()
        task = loop.create_task(client.download(path))
        try:
            loop.run_until_complete(task)
        except CancelledError:
            logging.warning('Event was cancelled')
        # finally:
        #     task.cancel()
        #     try:
        #         loop.run_until_complete(task)
        #     except Exception:
        #         pass 
        #     loop.close()
        # loop.run_forever()
        # loop.close()
        
    except (bencodepy.DecodingError,
            FileNotFoundError) as e:
        logger.error(e)


if __name__ == "__main__":
    cli.add_command(download)
    cli()
