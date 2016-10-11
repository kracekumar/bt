# -*- coding: utf-8 -*-

import socket
from collections import namedtuple
from struct import unpack

import bencodepy
import aiohttp
import requests

from .utils import generate_peer_id
from .logger import get_logger


logger = get_logger()

TrackerResponse = namedtuple('TrackerResponse',
                             ['complete', 'crypto_flags', 'incomplete',
                              'interval', 'peers'])


class BaseTracker:
    def __init__(self, url, size, info_hash):
        self.url = url.decode('utf-8')
        self.size = size
        self.info_hash = info_hash
        self.peer_id = generate_peer_id()

    def announce(self):
        """Contact tracker to receive information about 
        peers.
        """
        raise NotImplemented()


class UDPTracker:
    """UDP Tracker. Some sites like piratebay use udp tracker.
    """


class HTTPTracker(BaseTracker):
    def __init__(self, url, size, info_hash):
        super().__init__(url, size, info_hash)
        self.client = aiohttp.ClientSession()

    def close(self):
        self.client.close()

    async def announce(self):
        """
        """
        logger.debug('announce')
        params = self.build_params_for_announce()
        async with aiohttp.ClientSession() as session:
            async with session.get(self.url,
                                   params=params) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    return self.parse_tracker_response(content)

    def bye(self, uploaded, downloaded):
        params = self.build_params_for_announce(
            first=False, uploaded=0, downloaded=0, event='stopped')
        logger.info('Saying bye to tracker')
        res = requests.get(self.url, params=params)
        logger.info('{}'.format(res))

    def parse_tracker_response(self, content):
        resp = bencodepy.decode(content)
        split_peers = [resp[b'peers'][i:i+6]
                       for i in range(0, len(resp[b'peers']), 6)]

        peers = [(socket.inet_ntoa(p[:4]), _decode_port(p[4:]))
                for p in split_peers]
        return TrackerResponse(resp[b'complete'], resp.get(b'crypto_flags'),
                               resp.get(b'incomplete'), resp.get(b'interval'),
                               peers)

    def build_params_for_announce(self):
         return {'info_hash': self.info_hash,
                'peer_id': self.peer_id,
                'port': '51412',
                'uploaded': 0,
                'downloaded': 0,
                'left': self.size,
                'numwant': 80,
                'key': 'secret_key',
                'compact': 1,
                'supportcrypto': 1,
                'event': 'started'}

    async def connect(self, first, uploaded, downloaded, event=''):
        params = self.build_params_for_announce()
        params['uploaded'] = uploaded
        params['downloaded'] = downloaded
        params['left'] = self.size

        if not first:
            params.pop('event')

        if event != '':
            params['event'] = event

        logger.debug('Connecting tracker')

        async with self.client.get(self.url, params=params) as response:
            if not response.status == 200:
                raise Exception('Failed request; {}'.format(
                    await response.read()))
            data = await response.read()
            return self.parse_tracker_response(data)


def _decode_port(port):
    return unpack(">H", port)[0]
