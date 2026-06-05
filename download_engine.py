"""Orchestrates downloading: tracker → peers → pieces."""

import threading
import time
from typing import Callable

from torrent_parser import parse_torrent
from tracker import get_peers, PEER_ID
from piece_manager import PieceManager
from peer import Peer

MAX_PEERS = 30


class DownloadEngine:
    def __init__(self, torrent_path: str, download_dir: str,
                 on_progress: Callable[[int, int, float], None] | None = None,
                 on_status: Callable[[str], None] | None = None):
        self.torrent = parse_torrent(torrent_path)
        self.download_dir = download_dir
        self.on_progress = on_progress  # (downloaded_pieces, total_pieces, speed_bytes)
        self.on_status = on_status
        self.piece_manager = PieceManager(self.torrent, download_dir)
        self.running = False
        self._peers: list[Peer] = []
        self._speed = 0.0
        self._speed_lock = threading.Lock()

    def start(self):
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False
        for p in self._peers:
            p.stop()

    def _update_speed(self, speed: float):
        with self._speed_lock:
            self._speed = speed

    def _run(self):
        self._emit("Getting peers from tracker...")
        peers = get_peers(self.torrent)
        self._emit(f"Found {len(peers)} peers. Connecting...")

        connected = 0
        for ip, port in peers[:MAX_PEERS]:
            if not self.running:
                break
            p = Peer(ip, port, self.torrent["info_hash"], PEER_ID,
                     self.piece_manager, self._update_speed)
            p.start()
            self._peers.append(p)
            connected += 1

        self._emit(f"Connected to {connected} peers. Downloading...")

        while self.running and not self.piece_manager.is_complete:
            if self.on_progress:
                with self._speed_lock:
                    spd = self._speed
                self.on_progress(
                    self.piece_manager.downloaded,
                    self.piece_manager.num_pieces,
                    spd
                )
            time.sleep(0.5)

        if self.piece_manager.is_complete:
            self._emit("Download complete!")
            if self.on_progress:
                self.on_progress(self.piece_manager.num_pieces,
                                 self.piece_manager.num_pieces, 0.0)

    def _emit(self, msg: str):
        if self.on_status:
            self.on_status(msg)

    @property
    def name(self) -> str:
        return self.torrent["name"]

    @property
    def total_length(self) -> int:
        return self.torrent["total_length"]
