"""Tracks which pieces have been downloaded and verifies hashes."""

import os
import hashlib
import threading


class PieceManager:
    def __init__(self, torrent: dict, download_dir: str):
        self.torrent = torrent
        self.download_dir = download_dir
        self.piece_length = torrent["piece_length"]
        self.num_pieces = torrent["num_pieces"]
        self.total_length = torrent["total_length"]
        self.piece_hashes = torrent["piece_hashes"]

        self.have = bytearray(self.num_pieces)  # 1 = have, 0 = need
        self.in_progress = set()
        self.lock = threading.Lock()

        self._file_handles: dict[str, object] = {}
        self._prepare_files()
        self._check_existing()

    def _prepare_files(self):
        for file_info in self.torrent["files"]:
            path_parts = [self.torrent["name"]] + file_info["path"][:-1] if len(file_info["path"]) > 1 else []
            dir_path = os.path.join(self.download_dir, *path_parts) if path_parts else self.download_dir
            os.makedirs(dir_path, exist_ok=True)
            full_path = os.path.join(self.download_dir, self.torrent["name"], *file_info["path"]) \
                if len(self.torrent["files"]) > 1 else \
                os.path.join(self.download_dir, file_info["path"][0])
            self._file_handles[full_path] = file_info

    def _check_existing(self):
        """Resume: check which pieces we already have."""
        for i in range(self.num_pieces):
            data = self._read_piece(i)
            if data and self._verify_piece(i, data):
                self.have[i] = 1

    def _piece_size(self, index: int) -> int:
        if index == self.num_pieces - 1:
            remainder = self.total_length % self.piece_length
            return remainder if remainder else self.piece_length
        return self.piece_length

    def _read_piece(self, index: int) -> bytes | None:
        try:
            offset = index * self.piece_length
            size = self._piece_size(index)
            data = bytearray(size)
            pos = 0
            for fpath, finfo in self._file_handles.items():
                fstart = finfo["offset"]
                fend = fstart + finfo["length"]
                if offset + size <= fstart or offset >= fend:
                    continue
                overlap_start = max(offset, fstart)
                overlap_end = min(offset + size, fend)
                foffset = overlap_start - fstart
                doffset = overlap_start - offset
                chunk_len = overlap_end - overlap_start
                if not os.path.exists(fpath):
                    return None
                with open(fpath, "rb") as f:
                    f.seek(foffset)
                    chunk = f.read(chunk_len)
                    data[doffset:doffset+chunk_len] = chunk
            return bytes(data)
        except Exception:
            return None

    def _verify_piece(self, index: int, data: bytes) -> bool:
        return hashlib.sha1(data).digest() == self.piece_hashes[index]

    def write_piece(self, index: int, data: bytes) -> bool:
        if not self._verify_piece(index, data):
            return False
        offset = index * self.piece_length
        for fpath, finfo in self._file_handles.items():
            fstart = finfo["offset"]
            fend = fstart + finfo["length"]
            if offset + len(data) <= fstart or offset >= fend:
                continue
            overlap_start = max(offset, fstart)
            overlap_end = min(offset + len(data), fend)
            foffset = overlap_start - fstart
            doffset = overlap_start - offset
            chunk = data[doffset:doffset+(overlap_end - overlap_start)]
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "r+b" if os.path.exists(fpath) else "w+b") as f:
                f.seek(foffset)
                f.write(chunk)
        with self.lock:
            self.have[index] = 1
            self.in_progress.discard(index)
        return True

    def next_piece(self, peer_bitfield: bytearray | None = None) -> int | None:
        with self.lock:
            for i in range(self.num_pieces):
                if self.have[i] or i in self.in_progress:
                    continue
                if peer_bitfield is None or self._peer_has(peer_bitfield, i):
                    self.in_progress.add(i)
                    return i
        return None

    def release_piece(self, index: int):
        with self.lock:
            self.in_progress.discard(index)

    @staticmethod
    def _peer_has(bitfield: bytearray, index: int) -> bool:
        byte = index // 8
        bit = 7 - (index % 8)
        if byte >= len(bitfield):
            return False
        return bool(bitfield[byte] & (1 << bit))

    @property
    def downloaded(self) -> int:
        return sum(self.have)

    @property
    def is_complete(self) -> bool:
        return all(self.have)

    def close(self):
        pass
