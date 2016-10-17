# -*- coding: utf-8 -*-

import os
import curio

from bt import Client


def test_tom_torrent_download():
    client = Client()
    curio.run(client.download(
        path='tom.torrent',
        savedir=b''))

    assert os.path.getsize('flag.jpg') == 1277987


def test_ubuntu_torrent_download():
    client = Client()
    curio.run(client.download(
        path='ubuntu-16.04.1-desktop-amd64.iso.torrent',
        savedir=b''))

    assert os.path.getsize('ubuntu-16.04.1-desktop-amd64.iso') == 1277987
