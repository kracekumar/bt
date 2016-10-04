# -*- coding: utf-8 -*-

import sys
import hashlib
from collections import namedtuple

import bencodepy
import binascii

from .logger import get_logger

logger = get_logger()


File = namedtuple('File', ['length', 'path'])


class Info(namedtuple('Info', ['files', 'name',
                               'length',
                               'piece_length',
                               'pieces', 'bin_pieces'])):
    __slots__ = ()

    def __str__(self):
        return "Info(files: {}, name: {}, piece_length: {})".format(
            self.files, self.name,
            self.piece_length)


class Torrent:
    """
    Contents of a torrent file represented as Object.
    """
    def __init__(self, announce, announce_list, comment,
                 created_by, created_at, url_list, info):
        self.announce = announce
        self.announce_list = announce_list
        self.comment = comment
        self.created_by = created_by
        self.created_at = created_at
        self.url_list = url_list
        self.raw_info = info
        self._parse_info(info)

    @property
    def name(self):
        return self.info.name

    @property
    def files(self):
        return self.info.files
    
    @property
    def hash(self):
        m = hashlib.sha1()
        m.update(bencodepy.encode(self.raw_info))
        logger.info(m.digest())
        return m.digest()

    def print_all_info(self):
        logger.info("All torrent info")
        logger.info("Announce: {}".format(self.announce))
        logger.info("Announce list: {}".format(self.announce_list))
        logger.info("Comment: {}".format(self.comment))
        logger.info("Created by: {}".format(self.created_by))
        logger.info("Created At: {}".format(self.created_at))
        logger.info("URL List: {}".format(self.url_list))
        logger.info("Info: {}".format(self.info))

    def _parse_info(self, info):
        bin_pieces = info.get(b'pieces')
        pieces = get_pieces_hashes(bin_pieces)
        if info.get(b'files'):
            files = [File(file[b'length'], file[b'path'])
                    for file in info.get(b'files')]
        else:
            files = []
        self.info = Info(files, info[b'name'],
                    info.get(b'length'),
                    info[b'piece length'],
                    pieces, bin_pieces)


def get_pieces_hashes(pieces):
    res = binascii.hexlify(pieces)
    return  [res[i*40: (i*40) + 40] for i in range(0, int(len(res)/40))]


def parse(path):
    """Parse the given torrent file and return `Torrent` object.
    """
    logger.info('Started parsing .torrent file')
    res = bencodepy.decode_from_file(path)
    # import ipdb;ipdb.set_trace()
    return Torrent(announce=res[b'announce'],
                   announce_list=res.get(b'announce-list', []),
                   comment=res.get(b'comment', ''),
                   created_by=res.get(b'created by', ''),
                   created_at=res.get(b'creation date'),
                   url_list=res.get(b'url-list'),
                   info=res.get(b'info'))


if __name__ == "__main__":
    if len(sys.argv) == 2:
        try:
            torrent = parse(sys.argv[1])
            torrent.print_all_info()
        except (bencodepy.DecodingError,
                FileNotFoundError) as e:
            print(e)
    else:
        print("Pass torrent file as an argument")
        exit(1)
        
