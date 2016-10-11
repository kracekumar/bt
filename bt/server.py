# -*- coding: utf-8 -*-

import os
import asyncio
import struct

from .logger import get_logger
from .protocol import PeerStreamIterator

from .message import (MessageID,
                      InterestedMessage,
                      HandshakeMessage,
                      BitFieldMessage,
                      NotInterestedMessage,
                      ChokeMessage,
                      UnchokeMessage,
                      HaveMessage,
                      RequestMessage,
                      PieceMessage,
                      CancelMessage,
                      KeepAliveMessage)

logger = get_logger()


class SourceFileReader:
    def __init__(self, torrent):
        self.torrent = torrent
        self.fd = os.open(self.torrent.name, os.O_RDONLY)

    def read(self, begin, index, length):
        pos = index * self.torrent.info.piece_length
        os.lseek(self.fd, pos, os.SEEK_SET)
        return os.read(self.fd, length)

    def has_all_pieces(self):
        """Check the size on the disk is equal or greater than 
        (piece_length - 1) * piece_length.

        The assumption is clients wrote the last piece to disk 
        after checking integrating
        Returns True or False.
        """
        
        min_length = (len(self.torrent.info.pieces) - 1) * self.torrent.info.piece_length
        return os.path.getsize(self.torrent.name) > min_length

    def calculate_have_pieces(self):
        pass

    def get_have_pieces(self):
        """Get all have pieces
        Returns list of all bool values with size of piece+1.
        The last element in the list is False and other positions contains
        True or False.

        Available piece is represented as True and missing piece 
        is represented as False.
        """
        if self.has_all_pieces():
            pieces_availability = [True] * len(self.torrent.info.pieces)
            pieces_availability.append(False)
            return pieces_availability
        return self.calculate_have_pieces()


class RequestHandler:
    def __init__(self, torrent):
        self.torrent = torrent
        self.file_reader = SourceFileReader(torrent=self.torrent)

    def parse(self, buffer):
        """
        Tries to parse protocol messages if there is enough bytes read in the
        buffer.
        :return The parsed message, or None if no message could be parsed
        """
        # Each message is structured as:
        #     <length prefix><message ID><payload>
        #
        # The `length prefix` is a four byte big-endian value
        # The `message ID` is a decimal byte
        # The `payload` is the value of `length prefix`
        #
        # The message length is not part of the actual length. So another
        # 4 bytes needs to be included when slicing the buffer.
        self.buffer = buffer
        header_length = 4
        if len(self.buffer) == 68:
            return HandshakeMessage.decode(self.buffer)
        elif len(self.buffer) > 4:  # 4 bytes is needed to identify the message
            message_length = struct.unpack('>I', self.buffer[0:4])[0]

            if message_length == 0:
                return KeepAliveMessage()

            if len(self.buffer) >= message_length:
                message_id = struct.unpack('>b', self.buffer[4:5])[0]

                def _consume():
                    """Consume the current message from the read buffer"""
                    self.buffer = self.buffer[header_length + message_length:]

                def _data():
                    """"Extract the current message from the read buffer"""
                    return self.buffer[:header_length + message_length]

                if message_id is MessageID.BitField.value:
                    data = _data()
                    _consume()
                    return BitFieldMessage.decode(data)
                elif message_id is MessageID.Interested.value:
                    _consume()
                    return InterestedMessage()
                elif message_id is MessageID.NotInterested.value:
                    _consume()
                    return NotInterestedMessage()
                elif message_id is MessageID.Choke.value:
                    _consume()
                    return ChokeMessage()
                elif message_id is MessageID.Unchoke.value:
                    _consume()
                    return UnchokeMessage()
                elif message_id is MessageID.Have.value:
                    data = _data()
                    _consume()
                    return HaveMessage.decode(data)
                elif message_id is MessageID.Piece.value:
                    data = _data()
                    _consume()
                    return PieceMessage.decode(data)
                elif message_id is MessageID.Request.value:
                    data = _data()
                    _consume()
                    return RequestMessage.decode(data)
                elif message_id is MessageID.Cancel.value:
                    data = _data()
                    _consume()
                    return CancelMessage.decode(data)
                else:
                    logger.debug('Unsupported message!')
            else:
                #import ipdb;ipdb.set_trace()
                return None
                logger.debug('Not enough in buffer in order to parse')
        return None

    def get_piece(self, begin, index, length):
        data = self.file_reader.read(begin=begin, index=index, length=length)
        return PieceMessage(begin=begin, index=index, block=data)

    def handle_message(self, buffer):
        message = self.parse(buffer)
        if isinstance(message, NotInterestedMessage):
            logger.debug('Remove interested state')
        elif isinstance(message, HandshakeMessage):
            logger.debug('Received Handshake')
        elif isinstance(message, ChokeMessage):
            logger.debug('Received choke message')
            self.current_state.append(PeerState.Choked.value)
        elif isinstance(message, UnchokeMessage):
            logger.debug('Received unchoke message')
        elif isinstance(message, HaveMessage):
            logger.debug('Received have message')
        elif isinstance(message, BitFieldMessage):
            logger.debug('Received bit field message: {}'.format(message))
        elif isinstance(message, PieceMessage):
            pass
        elif isinstance(message, InterestedMessage):
            return BitFieldMessage(val=self.file_reader.get_have_pieces())
        elif isinstance(message, RequestMessage):
            return self.get_piece(begin=message.begin, index=message.index,
                           length=message.length)
        elif isinstance(message, CancelMessage):
            # TODO: Implement cancel data
            pass
        return message


class TorrentServer(asyncio.Protocol):
    def __init__(self, torrent):
        self.torrent = torrent
        super().__init__()

    def __call__(self):
        self.connections = set([])
        self.request_handler = RequestHandler(torrent=self.torrent)
        logger.debug('Init server')
        return self

    def connection_made(self, transport):
        self.transport = transport
        peer = transport.get_extra_info('peername')
        self.connections.add(peer)

    def data_received(self, data):
        message = self.request_handler.handle_message(data)
        logger.debug(message)
        if message:
            logger.info('Serving {}'.format(message))
            self.transport.write(message.encode())

    def eof_received(self):
        logger.debug('eof received')

    def connection_lost(self, exc):
        logger.debug('connectin lost')


async def run_server(port, torrent):
    """Run a server to respond to all clients
    """
    logger.info('Starting server in port {}'.format(port))
    loop = asyncio.get_event_loop()
    server = await loop.create_server(
        TorrentServer(torrent), host='127.0.0.1', port=port)
    return server
