# -*- coding: utf-8 -*-

import os
import logging
import sys
import asyncio
import warnings
from concurrent.futures import CancelledError

import click
import bencodepy

from bt import Client, get_logger, run_server


def manage_event_loop_for_download(path, savedir):
    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    client = Client()
    task = loop.create_task(client.download(path, savedir))
    try:
        loop.run_until_complete(task)
    except CancelledError:
        logging.warning('Event was cancelled')
    finally:
        task.cancel()
        try:
            loop.run_until_complete(task)
        except Exception:
            pass 
        loop.close()


@click.group()
def cli():
    pass


@click.command()
@click.option('--loglevel', default='info',
              help='info or debug. debug is enlightening')
@click.option('--savedir', default='.',
              help='Destination to save the downloaded file')
@click.argument('path')
def download(loglevel, savedir, path):
    try:
        os.environ['loglevel'] = loglevel
        logger = get_logger()

        if savedir == '.':
            savedir = b''
        elif os.path.exists(savedir):
            savedir = bytes(savedir.encode('utf-8'))
        else:
            logger.info("Directory {} doesn't exist".format(savedir))
            exit(1)

        manage_event_loop_for_download(path, savedir)
    except (bencodepy.DecodingError,
            FileNotFoundError) as e:
        logger.error(e)


@click.command()
@click.option('--loglevel', default='info',
              help='info or debug. debug is enlightening')
@click.argument('path')
def upload(loglevel, path):
    try:
        os.environ['loglevel'] = loglevel
        logger = get_logger()
        loop = asyncio.get_event_loop()
        loop.set_debug(True)
        # loop.slow_callback_duration = 0.001
        # warnings.simplefilter('always', ResourceWarning)
        client = Client()
        client.parse(path)
        task = loop.create_task(client.upload())
        server = run_server(port=51213, torrent=client.torrent)
        server_task = loop.create_task(server)

        try:
            loop.run_until_complete(
                asyncio.wait([task, server_task]))
            loop.run_forever()
        except CancelledError:
            logging.warning('Event was cancelled')
        except Exception as e:
            logging.info(e)
        except KeyboardInterrupt:
            logging.info('Received key board interrupt')
        finally:
            task.cancel()
            server_task.cancel()
            try:
                logger.info('Smothly disconnecting')
                client.close()
            except Exception:
                pass
            loop.close()

    except (bencodepy.DecodingError,
            FileNotFoundError) as e:
        logger.error(e)

if __name__ == "__main__":
    cli.add_command(download)
    cli.add_command(upload)
    cli()
