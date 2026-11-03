"""The verification sender speaks SMTP with STARTTLS, which is what Resend expects."""

import base64
import logging
import socket
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

import auth


class _FakeSmtp:
    def __init__(self, directory: Path, port: int):
        cert = directory / "cert.pem"
        key = directory / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-nodes",
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self._context = context
        self.port = port
        self.bound_port = 0
        self.events: list[str] = []
        self.implicit_tls = False
        self.username = ""
        self.password = ""
        self.data = ""
        self.error = ""
        self._ready = threading.Event()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(5), self.error or "fake SMTP server did not bind"

    def finish(self) -> None:
        self._thread.join(timeout=10)
        if self.error:
            raise AssertionError(self.error)

    def _serve(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind(("127.0.0.1", self.port))
            server.listen(1)
            server.settimeout(10)
            self.bound_port = server.getsockname()[1]
            self._ready.set()
            connection, _address = server.accept()
        except Exception as exc:
            self.error = str(exc)
            self._ready.set()
            self._done.set()
            server.close()
            return
        try:
            connection.settimeout(10)
            self._handle(connection)
        except Exception as exc:
            self.error = str(exc)
        finally:
            connection.close()
            server.close()
            self._done.set()

    def _handle(self, connection: socket.socket) -> None:
        # A STARTTLS client waits for the banner. An implicit-SSL client sends
        # a handshake immediately. Peek briefly before greeting so those differ.
        connection.settimeout(0.3)
        try:
            peeked = connection.recv(1, socket.MSG_PEEK)
        except TimeoutError:
            peeked = b""
        connection.settimeout(10)
        if peeked[:1] == b"\x16":
            self.implicit_tls = True
            self.events.append("implicit-tls")
            return

        pending = bytearray()

        def send(line: str) -> None:
            connection.sendall((line + "\r\n").encode("ascii"))

        def readline() -> str:
            while b"\r\n" not in pending:
                chunk = connection.recv(4096)
                if not chunk:
                    return ""
                pending.extend(chunk)
            line, rest = bytes(pending).split(b"\r\n", 1)
            pending.clear()
            pending.extend(rest)
            return line.decode("utf-8", "replace")

        send("220 localhost ESMTP")
        tls_on = False
        while True:
            line = readline()
            if not line:
                break
            parts = line.split(" ")
            command = parts[0].upper()
            self.events.append(command)
            if command in {"EHLO", "HELO"}:
                if tls_on:
                    send("250-localhost")
                    send("250 AUTH PLAIN LOGIN")
                else:
                    send("250-localhost")
                    send("250-STARTTLS")
                    send("250 AUTH PLAIN LOGIN")
            elif command == "STARTTLS":
                if tls_on:
                    send("554 already encrypted")
                    continue
                send("220 Ready")
                connection = self._context.wrap_socket(connection, server_side=True)
                tls_on = True
            elif command == "AUTH":
                mechanism = parts[1].upper() if len(parts) > 1 else ""
                if mechanism == "PLAIN" and len(parts) > 2:
                    decoded = base64.b64decode(parts[2])
                    _empty, username, password = decoded.split(b"\0", 2)
                    self.username = username.decode()
                    self.password = password.decode()
                    send("235 OK")
                elif mechanism == "LOGIN":
                    send("334 VXNlcm5hbWU6")
                    self.username = base64.b64decode(readline()).decode()
                    send("334 UGFzc3dvcmQ6")
                    self.password = base64.b64decode(readline()).decode()
                    send("235 OK")
                else:
                    send("504 unsupported")
            elif command == "DATA":
                send("354 End data with <CR><LF>.<CR><LF>")
                lines: list[str] = []
                while True:
                    data_line = readline()
                    if data_line == ".":
                        break
                    lines.append(data_line)
                self.data = "\n".join(lines)
                send("250 OK")
            elif command == "QUIT":
                send("221 Bye")
                break
            else:
                send("250 OK")


def test_smtp_delivery_uses_starttls_not_implicit_ssl(tmp_path, monkeypatch, caplog):
    # Port 587 is the Resend port. This sandbox rejects binding it, so the
    # protocol check uses an ephemeral port. test_sender_defaults_to_port_587
    # locks the port the sender uses when SMTP_PORT is unset.
    server = _FakeSmtp(tmp_path, 0)
    server.start()
    api_key = "resend-test-key"
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(server.bound_port))
    monkeypatch.setenv("SMTP_USERNAME", "resend")
    monkeypatch.setenv("SMTP_PASSWORD", api_key)
    monkeypatch.setenv("SMTP_FROM", "GSB Chef <no-reply@yourdomain.com>")
    monkeypatch.setenv("SMTP_TLS", "true")
    caplog.set_level(logging.DEBUG)
    link = "http://localhost:3000/verify#token=example-token"

    try:
        assert auth.send_verification_email("cook@example.com", link) == "smtp"
    finally:
        server.finish()

    assert server.implicit_tls is False
    assert server.events[:4] == ["EHLO", "STARTTLS", "EHLO", "AUTH"]
    assert "MAIL" in server.events and "DATA" in server.events
    assert server.username == "resend"
    assert server.password == api_key
    assert "no-reply@yourdomain.com" in server.data
    assert link in server.data
    assert api_key not in caplog.text
    assert api_key not in server.data


def test_empty_smtp_host_logs_the_link(monkeypatch, caplog):
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_PASSWORD", "resend-test-key")
    caplog.set_level(logging.INFO, logger="gsb.auth")
    link = "http://localhost:3000/verify#token=example-token"

    assert auth.send_verification_email("cook@example.com", link) == "log"

    assert link in caplog.text
    assert "resend-test-key" not in caplog.text


def test_sender_defaults_to_port_587(monkeypatch):
    captured: dict[str, object] = {}

    class Boom(Exception):
        pass

    def fake_smtp(host, port, timeout=30):
        captured["host"] = host
        captured["port"] = port
        raise Boom()

    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("SMTP_TLS", raising=False)
    monkeypatch.setattr(auth.smtplib, "SMTP", fake_smtp)
    monkeypatch.setattr(auth.smtplib, "SMTP_SSL", lambda *args, **kwargs: pytest.fail("implicit SSL"))

    with pytest.raises(Boom):
        auth.send_verification_email("cook@example.com", "http://localhost:3000/verify#token=x")

    assert captured == {"host": "smtp.resend.com", "port": 587}
