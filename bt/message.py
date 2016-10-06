# -*- coding: utf-8 -*-

import struct
from enum import Enum

import bitstring

from .logger import get_logger
from .mixins import ReprMixin


logger = get_logger()

REQUEST_SIZE = 2 ** 14


class MessageID(Enum):
    Choke = 0
    Unchoke = 1
    Interested = 2
    NotInterested = 3
    Have = 4
    BitField = 5
    Request = 6
    Piece = 7
    Cancel = 8
    Port = 9


class BasePeerMessage:
    """Base class of all message received and sent to peers
    """
    def encode(self):
        raise NotImplementedError

    def decode(self):
        raise NotImplementedError


class HandshakeMessage(BasePeerMessage):
    """
    Format:
        <pstrlen><pstr><reserved><info_hash><peer_id>
    In version 1.0 of the BitTorrent protocol:
        pstrlen = 19
        pstr = "BitTorrent protocol".
    Thus length is:
        49 + len(pstr) = 68 bytes long.
    """
    def __init__(self, info_hash, peer_id):
        self.info_hash = info_hash
        self.peer_id = peer_id

    def encode(self):
        """
        :param info_hash: 20 byte SHA-1 of info value in metainfo torrent file.
        :param peer_id: Unique ID of the peer.
        """
        # Single Byte, 19 character string, 8 byte padding, 20 byte info _hash, 20 byte peer_id  # NOQA
        format = '>B19s8x20s20s'
        return struct.pack(
            format,
            19,
            b'BitTorrent protocol',
            self.info_hash,
            self.peer_id)

    @classmethod
    def decode(cls, data):
        """Decode the Handshake response returned by peer.
        """
        logger.debug('Decoding Handshake of length: {length}'.format(
            length=len(data)))
        if len(data) < (49 + 19):
            return None
        parts = struct.unpack('>B19s8x20s20s', data)
        return cls(info_hash=parts[2], peer_id=parts[3])


class InterestedMessage(BasePeerMessage):
    """
    Format:
       <len=0001><id=2>
    """
    def encode(self):
        return struct.pack('>Ib', 1, MessageID.Interested.value)


class BitFieldMessage(BasePeerMessage, ReprMixin):
    """
    Format: <len=0001+X><id=5><bitfield>
    """
    __repr_fields__ = ['bitfield']

    def __init__(self, data):
        self.bitfield = bitstring.BitArray(bytes=data)

    def encode(self):
        bit_length = len(self.bitfield)
        return struct.pack('>Ib'+ str(bit_length) + 's',
                           1 + bit_length,
                           MessageID.BitField.value,
                           self.bitfield)

    @classmethod
    def decode(cls, data):
        length = struct.unpack('>I', data[:4])[0]
        logger.debug('Decoding bitfield message of length: {}'.format(length))

        parts = struct.unpack('>Ib' + str(length - 1) + 's',
                              data)
        return cls(parts[2])


class NotInterestedMessage(BasePeerMessage):
    """
    Format: <len=0001><id=3>
    """


class ChokeMessage(BasePeerMessage):
    """
    Format: <len=0001><id=0>
    """


class UnchokeMessage(BasePeerMessage):
    """
    Format: <len=0001><id=1>
    """


class HaveMessage(BasePeerMessage):
    """
    Format: <len=0005><id=4><pieceindex>

    Message represents client successfully downloaded a piece.
    """
    def __init__(self, index):
        self.index = index

    def encode(self):
        return struct.pack('>IbI',
                           5, MessageID.Have.value, self.index)

    @classmethod
    def decode(cls, data):
        logger.debug("Decoding have message of length: {}".format(len(data)))
        parts = struct.unpack('>IbI', data)
        return cls(index=parts[-1])


class RequestMessage(BasePeerMessage):
    """This message is used to request partial data from remote peer.
    
    Format: <len=0013><id=6><index><begin><length>
    
    All the requested pieces is of equal size except last one. Last piece will be smaller than rest of the request size.
    """
    def __init__(self, index, begin, length=REQUEST_SIZE):
        self.index = index
        self.begin = begin
        self.length = length

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           MessageID.Request.value,
                           self.index,
                           self.begin,
                           self.length)

    @classmethod
    def decode(cls, data):
        logger.debug("Decoding request message of length: {}".format(
            len(data)))
        parts = struct.unpack('>IbIII', data)
        return cls(parts[2], parts[3], parts[4])


class PieceMessage(BasePeerMessage):
    """This is the message which carries actual data :D

    Format: <len=0009+X><id=7><index><begin><block>
    X: length of the block
    """
    def __init__(self, index, begin, block):
        self.index = index
        self.begin = begin
        self.block = block

    def encode(self):
        length = 9 + len(self.block)
        format = '>IbII' + str(len(self.block)) + 's'
        return struct.pack(format, length,
                           MessageID.Piece.value,
                           self.index,
                           self.begin,
                           self.block)

    @classmethod
    def decode(cls, data):
        #import ipdb;ipdb.set_trace()
        logger.debug("Decoding PieceMessage of length: {}".format(len(data)))
        length = struct.unpack('>I', data[:4])[0]
        try:
            parts = struct.unpack(
                '>IbII' + str(length - 9) + 's',
                data[:length+4])
            return cls(parts[2], parts[3], parts[4])
        except struct.error:
             return None


class CancelMessage(BasePeerMessage):
    """
    Format: <len=0013><id=8><index><begin><length>
    """
    def __init__(self, index, begin, block):
        self.index = index
        self.begin = begin
        self.block = block

    def encode(self):
        return struct.pack('>IbIII',
                           13,
                           MessageID.Cancel.value,
                           self.index,
                           self.begin,
                           self.block)

    @classmethod
    def decode(cls, data):
        logger.debug('Decoding cancel message of length:{}'.format(len(data)))
        part = struct.unpack('>IbIII',
                             data)
        return cls(parts[2], parts[3], parts[4])


class KeepAliveMessage(BasePeerMessage):
    """
    Format: <len=0000>
    """
    pass



class PortMessage(BasePeerMessage):
    pass
