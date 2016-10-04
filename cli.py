# -*- coding: utf-8 -*-

import sys
import asyncio
from concurrent.futures import CancelledError

import click
import bencodepy

from bt import Client, get_logger
logger = get_logger()


@click.group()
def cli():
    pass


@click.command()
@click.argument('path')
def download(path):
    try:
        loop = asyncio.get_event_loop()
        client = Client()
        task = loop.create_task(client.download(path))
        try:
            loop.run_until_complete(task)
        except CancelledError:
            logging.warning('Event was cancelled')
        except Exception as e:
            print(e)
            raise(e)
        # finally:
        #     task.cancel()
        #     try:
        #         loop.run_until_complete(task)
        #     except Exception:
        #         pass 
        #     loop.close()
        # loop.run_forever()
        # loop.close()
        # import ipdb;ipdb.set_trace()
        
    except (bencodepy.DecodingError,
            FileNotFoundError) as e:
        logger.error(e)


if __name__ == "__main__":
    cli.add_command(download)
    cli()
