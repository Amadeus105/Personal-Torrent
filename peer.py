"""BitTorrent peer wire protocol implementation."""

import socket
import struct
import time
import threading

from piece_manager import PieceManager

BLOCK_SIZE = 16 * 1024  # 16 KB
HANDSHAKE_PSTR = b"\x13BitTorrent protocol"


class Peer(threading.Thread):
    def __init__(self, ip: str, port: int, info_hash: bytes, peer_id: bytes,
                 piece_manager: PieceManager, on_speed: callable = None):
        super().__init__(daemon=True)
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.peer_id = peer_id
        self.piece_manager = piece_manager
        self.on_speed = on_speed

        self.sock: socket.socket | None = None
        self.bitfield: bytearray | None = None
        self.choked = True
        self.running = True
        self._downloaded_bytes = 0
        self._speed_time = time.time()

    def run(self):
        try:
            self._connect()
            self._handshake()
            self._send_interested()
            self._message_loop()
        except Exception:
            pass
        finally:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect((self.ip, self.port))

    def _handshake(self):
        hs = HANDSHAKE_PSTR + b"\x00" * 8 + self.info_hash + self.peer_id
        self.sock.sendall(hs)
        resp = self._recv_exact(68)
        if resp[28:48] != self.info_hash:
            raise ValueError("Info hash mismatch")

    def _send_interested(self):
        self._send_message(2)  # interested

    def _send_message(self, msg_id: int, payload: bytes = b""):
        msg = struct.pack("!IB", 1 + len(payload), msg_id) + payload
        self.sock.sendall(msg)

    def _send_request(self, index: int, begin: int, length: int):
        payload = struct.pack("!III", index, begin, length)
        self._send_message(6, payload)

    def _recv_exact(self, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _read_message(self) -> tuple[int, bytes]:
        raw_len = self._recv_exact(4)
        length = struct.unpack("!I", raw_len)[0]
        if length == 0:
            return -1, b""  # keep-alive
        msg_id = struct.unpack("!B", self._recv_exact(1))[0]
        payload = self._recv_exact(length - 1) if length > 1 else b""
        return msg_id, payload

    def _message_loop(self):
        current_piece = None
        blocks: dict[int, bytes] = {}
        num_blocks = 0
        self.sock.settimeout(30)

        while self.running and not self.piece_manager.is_complete:
            msg_id, payload = self._read_message()

            if msg_id == 0:  # choke
                self.choked = True
                if current_piece is not None:
                    self.piece_manager.release_piece(current_piece)
                    current_piece = None

            elif msg_id == 1:  # unchoke
                self.choked = False

            elif msg_id == 4:  # have
                idx = struct.unpack("!I", payload)[0]
                if self.bitfield is None:
                    nbytes = (self.piece_manager.num_pieces + 7) // 8
                    self.bitfield = bytearray(nbytes)
                byte_idx = idx // 8
                if byte_idx < len(self.bitfield):
                    self.bitfield[byte_idx] |= 1 << (7 - idx % 8)

            elif msg_id == 5:  # bitfield
                self.bitfield = bytearray(payload)

            elif msg_id == 7:  # piece
                idx, begin = struct.unpack("!II", payload[:8])
                data = payload[8:]
                if idx == current_piece:
                    blocks[begin] = data
                    self._downloaded_bytes += len(data)
                    now = time.time()
                    if now - self._speed_time >= 1.0:
                        speed = self._downloaded_bytes / (now - self._speed_time)
                        if self.on_speed:
                            self.on_speed(speed)
                        self._downloaded_bytes = 0
                        self._speed_time = now

                    if len(blocks) == num_blocks:
                        piece_data = b"".join(blocks[b] for b in sorted(blocks))
                        if self.piece_manager.write_piece(idx, piece_data):
                            pass
                        current_piece = None
                        blocks = {}

            if not self.choked and current_piece is None:
                current_piece = self.piece_manager.next_piece(self.bitfield)
                if current_piece is not None:
                    piece_size = self.piece_manager._piece_size(current_piece)
                    num_blocks = (piece_size + BLOCK_SIZE - 1) // BLOCK_SIZE
                    blocks = {}
                    for i in range(num_blocks):
                        begin = i * BLOCK_SIZE
                        length = min(BLOCK_SIZE, piece_size - begin)
                        self._send_request(current_piece, begin, length)
