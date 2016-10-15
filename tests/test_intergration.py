# -*- coding: utf-8 -*-

import os
import asyncio

from bt import Client


def test_tom_torrent_download():
    client = Client()
    loop = asyncio.get_event_loop()
    task = loop.create_task(client.download(
        path='tom.torrent',
        savedir=b''))
    loop.run_until_complete(task)

    assert os.path.getsize('flag.jpg') == 1277987


def test_ubuntu_torrent_download():
    client = Client()
    loop = asyncio.get_event_loop()
    task = loop.create_task(client.download(
        path='ubuntu-16.04.1-desktop-amd64.iso.torrent',
        savedir=b''))
    loop.run_until_complete(task)

    assert os.path.getsize('ubuntu-16.04.1-desktop-amd64.iso') == 1277987
