#!/usr/bin/env python3
"""THROWAWAY POC: a userspace L2 hub for QEMU `-netdev socket,connect=`.

macOS doesn't loop QEMU multicast between processes, and `socket,listen` is
point-to-point. This relays QEMU's stream framing (4-byte big-endian length +
raw Ethernet frame) between N connected VMs on loopback = a real multi-port
hub/switch. Frames (including 802.1Q tags) are forwarded verbatim to all peers.
"""
import socket, struct, threading, sys

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 10032
clients = []                      # list of [sock, send_lock]
clients_lock = threading.Lock()


def recvall(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            return None
        buf += c
    return buf


def handle(sock):
    entry = [sock, threading.Lock()]
    with clients_lock:
        clients.append(entry)
    try:
        while True:
            hdr = recvall(sock, 4)
            if hdr is None:
                break
            (ln,) = struct.unpack(">I", hdr)
            payload = recvall(sock, ln)
            if payload is None:
                break
            frame = hdr + payload
            with clients_lock:
                others = [c for c in clients if c[0] is not sock]
            for s, lk in others:
                try:
                    with lk:
                        s.sendall(frame)
                except Exception:
                    pass
    finally:
        with clients_lock:
            if entry in clients:
                clients.remove(entry)
        try:
            sock.close()
        except Exception:
            pass


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(16)
    print(f"cm_hub listening {HOST}:{PORT}", flush=True)
    while True:
        c, _ = srv.accept()
        c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        threading.Thread(target=handle, args=(c,), daemon=True).start()


if __name__ == "__main__":
    main()
