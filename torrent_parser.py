"""Parses .torrent files and extracts metadata."""

import hashlib
import bencodepy


def parse_torrent(filepath: str) -> dict:
    with open(filepath, "rb") as f:
        data = bencodepy.decode(f.read())

    info = data[b"info"]
    info_encoded = bencodepy.encode(info)
    info_hash = hashlib.sha1(info_encoded).digest()

    # Trackers
    trackers = []
    if b"announce" in data:
        trackers.append(data[b"announce"].decode())
    if b"announce-list" in data:
        for tier in data[b"announce-list"]:
            for url in tier:
                url = url.decode()
                if url not in trackers:
                    trackers.append(url)

    # Files
    name = info[b"name"].decode()
    piece_length = info[b"piece length"]
    pieces_raw = info[b"pieces"]
    piece_hashes = [pieces_raw[i:i+20] for i in range(0, len(pieces_raw), 20)]

    if b"files" in info:
        # Multi-file torrent
        files = []
        total_length = 0
        for f in info[b"files"]:
            path = [p.decode() for p in f[b"path"]]
            length = f[b"length"]
            files.append({"path": path, "length": length, "offset": total_length})
            total_length += length
    else:
        # Single-file torrent
        total_length = info[b"length"]
        files = [{"path": [name], "length": total_length, "offset": 0}]

    return {
        "name": name,
        "info_hash": info_hash,
        "trackers": trackers,
        "piece_length": piece_length,
        "piece_hashes": piece_hashes,
        "files": files,
        "total_length": total_length,
        "num_pieces": len(piece_hashes),
    }
