# -*- coding: utf-8 -*-

from enum import Enum

import struct
import asyncio

from concurrent.futures import CancelledError

from .logger import get_logger
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


class ProtocolError(BaseException):
    pass


class MessageLength(Enum):
    handshake = 49 + 19


class PeerState(Enum):
    Choked = 'choked'
    Interested = 'interested'
    Stopped = 'stopped'
    PendingRequest = 'pending_request'


class PeerStreamIterator:
    """
    The `PeerStreamIterator` is an async iterator that continuously reads from
    the given stream reader and tries to parse valid BitTorrent messages from
    off that stream of bytes.
    If the connection is dropped, something fails the iterator will abort by
    raising the `StopAsyncIteration` error ending the calling iteration.
    """
    CHUNK_SIZE = 10*1024

    def __init__(self, reader, initial=None):
        self.reader = reader
        self.buffer = initial if initial else b''

    async def __aiter__(self):
        return self

    async def __anext__(self):
        # Read data from the socket. When we have enough data to parse, parse
        # it and return the message. Until then keep reading from stream
        while True:
            try:
                data = await self.reader.read(PeerStreamIterator.CHUNK_SIZE)
                if data:
                    self.buffer += data
                    message = self.parse()
                    if message:
                        return message
                else:
                    logger.debug('No data read from stream')
                    if self.buffer:
                        message = self.parse()
                        if message:
                            return message
                    raise StopAsyncIteration()
            except ConnectionResetError:
                logger.debug('Connection closed by peer')
                raise StopAsyncIteration()
            except CancelledError:
                raise StopAsyncIteration()
            except StopAsyncIteration as e:
                # Cath to stop logger
                raise e
            except Exception:
                logger.exception('Error when iterating over stream!')
                raise StopAsyncIteration()
        raise StopAsyncIteration()

    def parse(self):
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
        header_length = 4

        if len(self.buffer) > 4:  # 4 bytes is needed to identify the message
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
                    logger.debug('Received BitField message')
                    _consume()
                    return BitFieldMessage.decode(data)
                elif message_id is MessageID.Interested.value:
                    _consume()
                    logger.debug('Received interested message')
                    return InterestedMessage()
                elif message_id is MessageID.NotInterested.value:
                    _consume()
                    logger.debug('Received not interested message')
                    return NotInterestedMessage()
                elif message_id is MessageID.Choke.value:
                    _consume()
                    logger.debug('Received choke message')
                    return ChokeMessage()
                elif message_id is MessageID.Unchoke.value:
                    _consume()
                    logger.debug('Received unchoke message')
                    return UnchokeMessage()
                elif message_id is MessageID.Have.value:
                    data = _data()
                    logger.debug('Received have message')
                    _consume()
                    return HaveMessage.decode(data)
                elif message_id is MessageID.Piece.value:
                    data = _data()
                    logger.info('Received piece message')
                    _consume()
                    return PieceMessage.decode(data)
                elif message_id is MessageID.Request.value:
                    data = _data()
                    logger.debug('Received request message')
                    _consume()
                    return RequestMessage.decode(data)
                elif message_id is MessageID.Cancel.value:
                    data = _data()
                    logger.debug('Received cancel message')
                    _consume()
                    return CancelMessage.decode(data)
                else:
                    logger.debug('Unsupported message!')
            else:
                # logger.debug('Not enough in buffer in order to parse')
                pass
        return None


class PeerConnection:
    def __init__(self, info_hash, peer_id, available_peers, download_manager,
                 on_block_complete):
        """
        :param peer: (source_ip, port)
        """
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.available_peers = available_peers
        self.download_manager = download_manager
        self.on_block_complete = on_block_complete
        self.peer = None
        self.current_state = []
        self.remote_id = None
        self.writer = None
        self.reader = None

        self.future = asyncio.ensure_future(self.start())

    async def start(self):
        while PeerState.Stopped.value not in self.current_state:
            try:
                self.peer = await self.available_peers.get()
                self.reader, self.writer = await asyncio.open_connection(
                    self.peer[0], self.peer[1])
                logger.info('Remote connection with peer {}:{}'.format(
                *self.peer))

                # Do handshake and react accordingly
                buffer = await self.send_handshake()

                logger.info('Adding client to choke state')
                self.current_state.append(PeerState.Choked.value)

                # Then send interested message
                buffer = await self.send_interested()

                self.current_state.append(PeerState.Interested.value)

                # Parse the rest of the message and decide next step.
                return await self.handle_message(buffer)
            except (asyncio.TimeoutError, ProtocolError) as e:
                logger.debug(e)

    async def handle_message(self, buffer):
        async for message in PeerStreamIterator(self.reader, buffer):
            if PeerState.Stopped.value in self.current_state:
                break
            if isinstance(message, InterestedMessage):
                logger.debug('Received interested message')
                self.current_state.append(PeerState.Interested.value)
            elif isinstance(message, NotInterestedMessage):
                logger.debug('Received choke message')
                try:
                    self.current_state.remove(PeerState.Interested.value)
                except ValueError:
                    pass
            elif isinstance(message, ChokeMessage):
                logger.debug('Received choke message')
                self.current_state.append(PeerState.Choked.value)
            elif isinstance(message, UnchokeMessage):
                logger.debug('Received unchoke message')
                try:
                    self.current_state.remove(PeerState.Choked.value)
                except ValueError:
                    pass
            elif isinstance(message, HaveMessage):
                # self.piece_manager.update_peer(self.remote_id,
                #                                        message.index)
                logger.info('Received have message')
            elif isinstance(message, BitFieldMessage):
                logger.info('Received bit field message: {}'.format(message))
                self.download_manager.add_peer(peer_id=self.remote_id,
                                               bitfield=message.bitfield)
            elif isinstance(message, PieceMessage):
                logger.debug('Received piece message')
                self.current_state.remove(PeerState.PendingRequest.value)
                self.on_block_complete(peer_id=self.remote_id,
                                       piece_index=message.index,
                                       block_offset=message.begin,
                                       data=message.block)
            elif isinstance(message, RequestMessage):
                logger.debug('Received request message')
                # TODO: Implement uploading data
            elif isinstance(message, CancelMessage):
                logger.debug('Received request message')
                # TODO: Implement cancel data

            if self.can_request():
                if PeerState.PendingRequest.value not in self.current_state:
                    logger.info('Sending download request')
                    self.current_state.append(PeerState.PendingRequest.value)
                    await self.send_request()

        self.cancel()

    def can_request(self):
        return PeerState.Choked.value not in self.current_state \
          and PeerState.Interested.value in self.current_state  # NOQA

    async def send_handshake(self):
        """
        Send the initial handshake to the remote peer and wait for the peer
        to respond with its handshake.
        """
        self.writer.write(HandshakeMessage(self.info_hash, self.peer_id).encode())
        await self.writer.drain()

        buf = b''
        while len(buf) < MessageLength.handshake.value:
            buf = await self.reader.read(PeerStreamIterator.CHUNK_SIZE)

        response = HandshakeMessage.decode(buf[:MessageLength.handshake.value])
        if not response:
            raise ProtocolError('Unable receive and parse a handshake. Received buffer: {}'.format(buf))
        if not response.info_hash == self.info_hash:
            raise ProtocolError('Handshake with invalid info_hash')

        # TODO: According to spec we should validate that the peer_id received
        # from the peer match the peer_id received from the tracker.
        self.remote_id = response.peer_id
        logger.info('Handshake with peer was successful')

        # We need to return the remaining buffer data, since we might have
        # read more bytes then the size of the handshake message and we need
        # those bytes to parse the next message.
        return buf[MessageLength.handshake.value:]

    async def send_interested(self):
        message = InterestedMessage()
        logger.info('Sending interested message')
        self.writer.write(message.encode())
        await self.writer.drain()

    async def send_request(self):
        """Request peer to transfer the pieces.
        """
        block = self.download_manager.next_request(self.remote_id)
        logger.info("block: {}".format(block))
        if block:
            message = RequestMessage(block.piece, block.offset,
                                     block.length).encode()

            logger.info('Requesting block {block} for {piece} of length '
                         '{length} byte from peer {peer}'.format(
                             piece=block.piece, block=block.offset,
                             length=block.length, peer=self.remote_id))
            self.writer.write(message)
            await self.writer.drain()

    def cancel(self):
        if not self.future.done():
            self.future.cancel()
        if self.writer:
            self.writer.close()

        self.available_peers.done()

    def stop(self):
        self.current_state.append(PeerState.Stopped)
        if not self.future.done():
            self.future.cancel()
