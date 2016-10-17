# -*- coding: utf-8 -*-

import socket
import enum
import asyncio
from collections import namedtuple
from struct import unpack, pack

import bencodepy
import aiohttp
import requests

from .utils import generate_peer_id
from .logger import get_logger


logger = get_logger()

TrackerResponse = namedtuple('TrackerResponse',
                             ['complete', 'crypto_flags', 'incomplete',
                              'interval', 'peers'])


UDP_CONN_ID = 0x41727101980
UDP_CONN_INPUT_FORMAT = '>QI4s'
UDP_CONN_OUTPUT_FORMAT = '>I4sQ'
UDP_ANNOUNCE_INPUT_FORMAT = '>QI4s20s20sQQQII4siH'
UDP_ANNOUNCE_OUTPUT_FORMAT = '>I4s'


class Actions(enum.Enum):
    connect = 0
    announce = 1
    scrape = 2
    error = 3


class Events(enum.Enum):
    none = 0
    completed = 1
    started = 2
    stopped = 3


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

    def parse_tracker_response(self, content):
        resp = bencodepy.decode(content)
        split_peers = [resp[b'peers'][i:i+6]
                       for i in range(0, len(resp[b'peers']), 6)]

        peers = [(socket.inet_ntoa(p[:4]), _decode_port(p[4:]))
                for p in split_peers]
        return TrackerResponse(resp.get(b'complete'), resp.get(b'crypto_flags'),
                               resp.get(b'incomplete'), resp.get(b'interval'),
                               peers)


class UDPConnection:
    def __init__(self):
        self.state = None

    def __call__(self):
        return self

    def connection_made(self, transport):
        self.transport = transport

        if self.state == None:
            msg = pack(UDP_CONN_INPUT_FORMAT, UDP_CONN_ID,
                       Actions.connect.value,
                       self.transaction_id, str(uuid.uuid4())[:4])
            self.transport.write(msg)

    def datagram_received(self, data, addr):
        logger.info('Received {}'.format(data))

    def error_received(self, exc):
        pass

    def connection_lost(self, exc):
        pass


class UDPTracker(BaseTracker):
    """UDP Tracker. Some sites like piratebay use udp tracker.
    """
    def __init__(self, url, info_hash, size=None):
        super().__init__(url, size, info_hash)
        self.uuid = generate_peer_id()
        self.transaction_id = bytes(self.uuid[:4])
        self.key = bytes(self.uuid[4:8])
        self.client_id = bytes(self.uuid[8:18])
        self.connection_id = UDP_CONN_ID
        self.connected = False
        self.state = Actions.connect.value
        self.host = self._resolve(url)

    def _resolve(self, url):
        loop = asyncio.get_event_loop()
        self.loop = loop
        parts = self.url.split(':')
        port = parts[-1]
        name = parts[1][2:]
        res = socket.getaddrinfo(host=name, port=port)
        return res[1][-1]

    def announce(self):
        logger.info('Connecting to host: {}'.format(
            self.host))
        # TODO: Use asyncio kid!
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while True:
                if self.state == Actions.connect.value:
                    msg = pack(UDP_CONN_INPUT_FORMAT, UDP_CONN_ID,
                               Actions.connect.value, self.transaction_id)
                    sock.sendto(msg, self.host)
                    recv = sock.recv(1024)
                    logger.info("recv: {}".format(recv))
                    action, transaction_id, conn_id = unpack(
                        UDP_CONN_OUTPUT_FORMAT, recv)

                    assert action == Actions.connect.value
                    assert transaction_id == self.transaction_id

                    self.connection_id = conn_id
                    self.state = Actions.announce.value
                elif self.state == Actions.announce.value:
                    # TODO: Manage downloaded. left, uploaded
                    msg = pack(UDP_ANNOUNCE_INPUT_FORMAT, self.connection_id,
                         self.state, self.transaction_id, self.info_hash,
                         self.client_id, 0, 0, 0, Events.started.value, 0,
                         self.key, -1, 51413)
                    sock.sendto(msg, self.host)
                    recv = sock.recv(1024)
                    logger.debug("Announce resp: {}".format(recv))

                    assert len(recv) >= 20

                    action, trans_id = unpack(UDP_ANNOUNCE_OUTPUT_FORMAT,
                                              recv[:8])

                    peers = recv[8:]
                    logger.debug("Peers: {}".format(peers))
                    self.state = Actions.scrape.value

                    return self.parse_peers(peers)
                else:
                    break
        except socket.error as e:
            logger.error(e)

    def parse_peers(self, peers_raw):
        if len(peers_raw) % 6 != 0:
            raise ValueError('size of byte_string host/port pairs must be'
                            'a multiple of 6')
        peers = (peers_raw[i:i+6] for i in range(0, len(peers_raw), 6))
        hosts_ports = [(socket.inet_ntoa(peer[0:4]),
                        unpack('>H', peer[4:6])[0]) for peer in peers]
        return hosts_ports


class HTTPTracker(BaseTracker):
    def __init__(self, url, size, info_hash):
        super().__init__(url, size, info_hash)
        self.client = requests.Session()

    def close(self):
        self.client.close()

    def announce(self):
        """
        """
        logger.debug('announce')
        params = self.build_params_for_announce()
        resp = self.client.get(self.url, params=params)
        if resp.status_code == 200:
            content = resp.content
            return self.parse_tracker_response(content)

    def bye(self, uploaded, downloaded):
        params = self.build_params_for_announce(
            first=False, uploaded=0, downloaded=0, event='stopped')
        logger.info('Saying bye to tracker')
        res = requests.get(self.url, params=params)
        logger.info('{}'.format(res))


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


def _decode_port(port):
    return unpack(">H", port)[0]
