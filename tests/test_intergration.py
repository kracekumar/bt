# -*- coding: utf-8 -*-

import os
import asyncio

from bt import Client


def test_torrent_download():
    client = Client()
    loop = asyncio.get_event_loop()
    task = loop.create_task(client.download(
        path='tom.torrent',
        savedir=b''))
    loop.run_until_complete(task)

    assert os.path.getsize('flag.jpg') == 1277987
