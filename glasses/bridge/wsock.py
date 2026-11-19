"""A small server-side WebSocket (RFC 6455) on a socket that an http.server handler hands over after the upgrade.
Text and close frames, ping and pong, masked frames from the client, fragments joined. No extensions."""
import base64
import hashlib
import json
import socket
import struct
import threading

GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key.strip() + GUID).encode()).digest()).decode()


def frame(opcode, data=b''):
    n = len(data)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([n])
    elif n < 65536:
        head += bytes([126]) + struct.pack('!H', n)
    else:
        head += bytes([127]) + struct.pack('!Q', n)
    return head + data


class Closed(Exception):
    pass


class WebSocket:
    def __init__(self, sock, rfile):
        self.sock = sock
        self.rfile = rfile
        self.send_lock = threading.Lock()
        self.closed = False

    def _read(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                raise Closed()
            buf += chunk
        return buf

    def send_text(self, text):
        self._send(0x1, text.encode('utf-8'))

    def send_json(self, obj):
        self.send_text(json.dumps(obj, ensure_ascii=False))

    def ping(self):
        self._send(0x9, b'ka')

    def _send(self, opcode, data):
        if self.closed:
            raise Closed()
        with self.send_lock:
            try:
                self.sock.sendall(frame(opcode, data))
            except OSError:
                self.closed = True
                raise Closed()

    def close(self, code=1000):
        if not self.closed:
            try:
                self._send(0x8, struct.pack('!H', code))
            except Closed:
                pass
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def receive(self, max_size=1 << 20):
        """The next text message (str), or raises Closed. Answers pings; skips pongs and binary messages."""
        parts, kind = [], None
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            masked, n = b2 & 0x80, b2 & 0x7F
            if n == 126:
                n = struct.unpack('!H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('!Q', self._read(8))[0]
            if n > max_size:
                self.close(1009)
                raise Closed()
            mask = self._read(4) if masked else b''
            data = self._read(n)
            if masked:
                data = bytes(c ^ mask[i % 4] for i, c in enumerate(data))
            if opcode == 0x8:
                self.close()
                raise Closed()
            if opcode == 0x9:
                self._send(0xA, data)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2):
                kind, parts = opcode, [data]
            elif opcode == 0x0:
                parts.append(data)
            if fin and kind is not None:
                msg = b''.join(parts)
                if kind == 0x1:
                    return msg.decode('utf-8', 'replace')
                parts, kind = [], None
