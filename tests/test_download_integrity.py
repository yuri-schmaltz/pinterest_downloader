"""Real local HTTP streams: interrupted responses must never be published."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from pinterest_board_dl import _is_media_already_downloaded, download_media


@pytest.fixture
def media_server():
    class Handler(BaseHTTPRequestHandler):
        attempts = 0

        def do_GET(self):
            type(self).attempts += 1
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            if self.path == "/broken" or (self.path == "/retry" and self.attempts == 1):
                self.send_header("Content-Length", "100000")
                self.end_headers()
                self.wfile.write(b"p" * 40000)
                self.close_connection = True
            else:
                data = b"complete image" if self.path != "/empty" else b""
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_interrupted_response_is_not_published(tmp_path, media_server):
    base, _ = media_server
    with requests.Session() as session:
        assert not download_media(f"{base}/broken", str(tmp_path), session, "42.jpg", max_retries=0)
    assert list(tmp_path.iterdir()) == []
    assert not _is_media_already_downloaded(str(tmp_path), "42")


def test_retry_writes_complete_response(tmp_path, media_server, monkeypatch):
    base, handler = media_server
    monkeypatch.setattr("pinterest_board_dl.DOWNLOAD_RETRY_DELAY", 0)
    with requests.Session() as session:
        assert download_media(f"{base}/retry", str(tmp_path), session, "42.jpg", max_retries=1)
    assert handler.attempts == 2
    assert (tmp_path / "42.jpg").read_bytes() == b"complete image"
    assert len(list(tmp_path.iterdir())) == 1


def test_empty_response_is_not_published(tmp_path, media_server):
    base, _ = media_server
    with requests.Session() as session:
        assert not download_media(f"{base}/empty", str(tmp_path), session, "42.jpg", max_retries=0)
    assert list(tmp_path.iterdir()) == []


def test_cache_ignores_partials_and_other_pin_ids(tmp_path):
    (tmp_path / "420.jpg").write_bytes(b"other pin")
    (tmp_path / "42.jpg.part").write_bytes(b"partial")
    assert not _is_media_already_downloaded(str(tmp_path), "42")
    (tmp_path / "42.jpg").write_bytes(b"complete")
    assert _is_media_already_downloaded(str(tmp_path), "42")
