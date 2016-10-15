# -*- coding: utf-8 -*-

from enum import Enum

import struct
import asyncio
import socket

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
        self.i = 0

    async def __aiter__(self):
        return self

    async def __anext__(self):
        # Read data from the socket. When we have enough data to parse, parse
        # it and return the message. Until then keep reading from stream
        while True:
            try:
                if self.buffer:
                    message = self.parse()
                    if message:
                        return message
                logger.debug('I m stuck at reading from socket, buffer length: {}'.format(
                    len(self.buffer)))
                data = await asyncio.wait_for(self.reader.read(
                    PeerStreamIterator.CHUNK_SIZE), timeout=5)
                if data:
                    self.buffer += data
                    message = self.parse()
                    if message:
                        return message
            except ConnectionResetError:
                logger.debug('Connection closed by peer')
                raise StopAsyncIteration()
            except (CancelledError, EOFError, TimeoutError) as e:
                logger.error(e)
                raise StopAsyncIteration()
            except StopAsyncIteration as e:
                # Cath to stop logging
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
                return None
                logger.debug('Not enough in buffer in order to parse')
        return None


class BaseConnection:
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

        self.is_interested_msg_sent = False
        self.future = asyncio.ensure_future(self.start())

    async def handle_message(self, buffer):
        if not buffer:
            await self.send_interested()

        async for message in PeerStreamIterator(self.reader, buffer):
            if PeerState.Stopped.value in self.current_state:
                break

            if isinstance(message, NotInterestedMessage):
                try:
                    logger.debug('Remove interested state')
                    self.current_state.remove(PeerState.Interested.value)
                except ValueError:
                    pass
            elif isinstance(message, ChokeMessage):
                logger.debug('Received choke message')
                self.current_state.append(PeerState.Choked.value)
            elif isinstance(message, UnchokeMessage):
                logger.debug('Received unchoke message')
                try:
                    logger.debug('Remove choked state')
                    self.current_state.remove(PeerState.Choked.value)
                except ValueError:
                    pass
            elif isinstance(message, HaveMessage):
                self.download_manager.update_peer(self.remote_id,
                                               message.index)
                logger.debug('Received have message')
            elif isinstance(message, BitFieldMessage):
                logger.info('Received bit field message: {}'.format(message))
                if PeerState.Interested.value not in self.current_state:
                    await self.send_interested()
                    logger.debug('Sending interested')
                self.download_manager.add_peer(peer_id=self.remote_id,
                                               bitfield=message.bitfield)
            elif isinstance(message, PieceMessage):
                logger.debug('Received piece message')
                self.current_state.remove(PeerState.PendingRequest.value)
                self.on_block_complete(peer_id=self.remote_id,
                                       piece_index=message.index,
                                       block_offset=message.begin,
                                       data=message.block)

            await self.send_next_message()
        self.cancel()

    def can_request(self):
        return PeerState.Choked.value not in self.current_state \
          and PeerState.Interested.value in self.current_state  # NOQA

    def can_send_interested(self):
        return PeerState.Stopped.value not in self.current_state \
          and PeerState.Interested.value not in self.current_state

    async def send_next_message(self):
        if self.can_request():
            if PeerState.PendingRequest.value not in self.current_state:
                logger.debug('Sending download request {}'.format(
                    self.peer))
                self.current_state.append(PeerState.PendingRequest.value)
                await self.send_request()

    async def send_handshake(self):
        """
        Send the initial handshake to the remote peer and wait for the peer
        to respond with its handshake.
        """
        self.writer.write(
            HandshakeMessage(self.info_hash, self.peer_id).encode())
        await self.writer.drain()

        buf = b''
        while len(buf) < MessageLength.handshake.value:
            try:
                buf = await asyncio.wait_for(
                    self.reader.read(PeerStreamIterator.CHUNK_SIZE), timeout=5)
            except ConnectionResetError as e:
                logger.error(e)

        response = HandshakeMessage.decode(buf[:MessageLength.handshake.value])

        if not response:
            raise ProtocolError('Unable receive and parse a handshake. Received buffer: {}'.format(buf))
        if not response.info_hash == self.info_hash:
            raise ProtocolError('Handshake with invalid info_hash')

        # TODO: According to spec we should validate that the peer_id received
        # from the peer match the peer_id received from the tracker.
        self.remote_id = response.peer_id
        logger.info('Handshake with peer was successful {}'.format(
            self.peer))

        # We need to return the remaining buffer data, since we might have
        # read more bytes then the size of the handshake message and we need
        # those bytes to parse the next message.
        try:
            logger.debug('Remove choked state')
            self.current_state.remove(PeerState.Choked.value)
        except ValueError as e:
            pass

        return buf[MessageLength.handshake.value:]

    async def send_interested(self):
        self.current_state.append(PeerState.Interested.value)
        message = InterestedMessage()
        logger.debug('Sending interested message')
        self.writer.write(message.encode())
        await self.writer.drain()

    async def send_request(self):
        """Request peer to transfer the pieces.
        """
        block = self.download_manager.next_request(self.remote_id)
        if block:
            message = RequestMessage(block.piece, block.offset,
                                     block.length).encode()

            logger.debug('Requesting block {block} for {piece} of length '
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

        self.available_peers.task_done()

    def stop(self):
        self.current_state.append(PeerState.Stopped)
        if not self.future.done():
            self.future.cancel()


class UDPConnection(BaseConnection):
    async def start(self):
        await asyncio.sleep(0)
        while PeerState.Stopped.value not in self.current_state:
            self.peer = await self.available_peers.get()

            if self.peer[1] < 80:
                # Who runs torrent client on these ports? Rogue clients
                continue
            logger.info('got peer {}'.format(self.peer))
            self.sock_handler(self.peer)
            await asyncio.sleep(0)

    def sock_handler(self, addr):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while True:
                msg = HandshakeMessage(self.info_hash, self.peer_id).encode()
                sock.sendto(msg, addr)
                recv = sock.recv(1024)
                logger.info("recv: {}".format(recv))
                import ipdb;ipdb.set_trace()
                logger.info("Decode: {}".format(HandshakeMessage.decode(recv)))
                # if self.state == Actions.connect.value:
                #     msg = pack(UDP_CONN_INPUT_FORMAT, UDP_CONN_ID,
                #                Actions.connect.value, self.transaction_id)
                #     sock.sendto(msg, addr)
                #     recv = sock.recv(1024)
                #     logger.info("recv: {}".format(recv))
                #     action, transaction_id, conn_id = unpack(
                #         UDP_CONN_OUTPUT_FORMAT, recv)

                #     assert action == Actions.connect.value
                #     assert transaction_id == self.transaction_id

                #     self.connection_id = conn_id
                #     self.state = Actions.announce.value
                # elif self.state == Actions.announce.value:
                #     # TODO: Manage downloaded. left, uploaded
                #     msg = pack(UDP_ANNOUNCE_INPUT_FORMAT, self.connection_id,
                #          self.state, self.transaction_id, self.info_hash,
                #          self.client_id, 0, 0, 0, Events.started.value, 0,
                #          self.key, -1, 51413)
                #     sock.sendto(msg, self.host)
                #     recv = sock.recv(1024)
                #     logger.debug("Announce resp: {}".format(recv))

                #     assert len(recv) >= 20

                #     action, trans_id = unpack(UDP_ANNOUNCE_OUTPUT_FORMAT,
                #                               recv[:8])

                #     peers = recv[8:]
                #     logger.debug("Peers: {}".format(peers))
                #     self.state = Actions.scrape.value

                #     return self.parse_peers(peers)
                # else:
                #     break
        except socket.error as e:
            logger.error(e)

    
class PeerConnection(BaseConnection):
    async def start(self):
        while PeerState.Stopped.value not in self.current_state:
            try:
                self.peer = self.available_peers.get_nowait()

                if self.peer[1] < 80:
                    # Who runs torrent client on these ports? Rogue clients
                    continue
                logger.info('got peer {}'.format(self.peer))
                try:
                    fut = asyncio.open_connection(self.peer[0], self.peer[1])
                    self.reader, self.writer = await asyncio.wait_for(fut,
                        timeout=5)
                except CancelledError:
                    logger.info("Remote peer {} didn't respond".format(
                        self.peer))
                    continue
                except ConnectionRefusedError:
                    logger.info('Connection refused {}'.format(self.peer))
                    await asyncio.sleep(0.1)
                    continue
                except OSError as e:
                    await asyncio.sleep(0.1)
                    logger.error(e)
                    continue
                except KeyboardInterrupt as e:
                    logger.error(e)
                    break

                logger.debug('Remote connection with peer {}:{}'.format(
                *self.peer))

                logger.debug('Adding client to choke state')
                self.current_state.append(PeerState.Choked.value)

                # Do handshake and react accordingly
                buffer = await self.send_handshake()
                logger.debug('start')
                # buffer = await self.send_interested()

                # Parse the rest of the message and decide next step.
                return await self.handle_message(buffer)
            except (asyncio.TimeoutError, ProtocolError) as e:
                logger.debug(e)
