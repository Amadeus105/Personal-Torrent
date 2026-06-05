"""Communicates with HTTP/UDP trackers to get a list of peers."""

import struct
import socket
import random
import urllib.parse
import urllib.request


PEER_ID = b"-AI0001-" + bytes(random.randint(0, 255) for _ in range(12))


def get_peers(torrent: dict, port: int = 6881) -> list[tuple[str, int]]:
    peers = []
    for tracker_url in torrent["trackers"]:
        try:
            if tracker_url.startswith("http"):
                result = _http_tracker(tracker_url, torrent, port)
            elif tracker_url.startswith("udp"):
                result = _udp_tracker(tracker_url, torrent, port)
            else:
                continue
            peers.extend(result)
            if peers:
                break
        except Exception:
            continue
    return list(set(peers))


def _http_tracker(url: str, torrent: dict, port: int) -> list[tuple[str, int]]:
    params = {
        "info_hash": torrent["info_hash"],
        "peer_id": PEER_ID,
        "port": port,
        "uploaded": 0,
        "downloaded": 0,
        "left": torrent["total_length"],
        "compact": 1,
        "event": "started",
        "numwant": 80,
    }
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": "AiTorrent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        import bencodepy
        data = bencodepy.decode(resp.read())
    return _decode_compact_peers(data.get(b"peers", b""))


def _decode_compact_peers(raw: bytes) -> list[tuple[str, int]]:
    peers = []
    for i in range(0, len(raw), 6):
        ip = ".".join(str(b) for b in raw[i:i+4])
        port = struct.unpack("!H", raw[i+4:i+6])[0]
        if port > 0:
            peers.append((ip, port))
    return peers


def _udp_tracker(url: str, torrent: dict, port: int) -> list[tuple[str, int]]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    tracker_port = parsed.port or 80

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5)

    # Connect request
    conn_id = 0x41727101980
    transaction_id = random.randint(0, 0xFFFFFFFF)
    packet = struct.pack("!qii", conn_id, 0, transaction_id)
    sock.sendto(packet, (host, tracker_port))
    resp, _ = sock.recvfrom(16)
    _, _, received_tid, conn_id = struct.unpack("!iiqq", resp[:16])[:4]
    # Fix: unpack 16 bytes as action(i), transaction_id(i), connection_id(q) = 4+4+8 = 16
    action, tid, conn_id = struct.unpack("!iiQ", resp)
    if tid != transaction_id:
        return []

    # Announce request
    transaction_id = random.randint(0, 0xFFFFFFFF)
    key = random.randint(0, 0xFFFFFFFF)
    packet = struct.pack(
        "!QiI20s20sQQQiIiH",
        conn_id, 1, transaction_id,
        torrent["info_hash"], PEER_ID,
        0, torrent["total_length"], 0,
        2, 0, key, 80, port
    )
    sock.sendto(packet, (host, tracker_port))
    resp, _ = sock.recvfrom(2048)
    if len(resp) < 20:
        return []
    peers_data = resp[20:]
    sock.close()
    return _decode_compact_peers(peers_data)
