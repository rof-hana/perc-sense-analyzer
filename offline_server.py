"""Zero-dependency offline local web server (Python 3 standard library only).

Use this when running in a completely offline / air-gapped environment
where Flask cannot be installed via pip.
"""

from __future__ import annotations

import io
import json
import mimetypes
import os
import urllib.parse
import zipfile
from email.parser import BytesParser
from email.policy import default as email_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

from log_parser import SAMPLE_LSI_LOG, SAMPLE_TTY_LOG, extract_logs_from_bytes, parse_storage_logs
from t10_db import T10Database

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
t10_db = T10Database(auto_update=True)


def _parse_multipart_file(content_type: str, body: bytes) -> Optional[Tuple[str, bytes]]:
    header_bytes = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    msg = BytesParser(policy=email_policy).parsebytes(header_bytes + body)
    if not msg.is_multipart():
        return None
    for part in msg.iter_parts():
        cd = part.get("Content-Disposition", "")
        if "form-data" in cd and part.get_param("name", header="content-disposition") == "file":
            filename = part.get_filename() or "upload.zip"
            payload = part.get_payload(decode=True) or b""
            return filename, payload
    return None


class OfflineHandler(BaseHTTPRequestHandler):
    server_version = "PERCSenseOffline/1.0"

    def _send_json(self, data: object, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_file(self, filepath: str) -> None:
        if not os.path.isfile(filepath):
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        ctype, _ = mimetypes.guess_type(filepath)
        if ctype is None:
            ctype = "application/octet-stream"
        if ctype.startswith("text/") or ctype == "application/javascript":
            ctype += "; charset=utf-8"
        with open(filepath, "rb") as f:
            raw = f.read()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/":
            self._send_file(os.path.join(BASE_DIR, "templates", "index.html"))
            return

        if path.startswith("/static/"):
            rel = os.path.normpath(path.lstrip("/"))
            if rel.startswith("static" + os.sep) or rel.startswith("static/"):
                self._send_file(os.path.join(BASE_DIR, rel))
                return

        if path == "/api/t10/sense-keys":
            self._send_json({"sense_keys": t10_db.list_sense_keys()})
            return

        if path == "/api/t10/search":
            q = qs.get("q", [""])[0]
            sk = qs.get("sk", [""])[0]
            try:
                limit = min(int(qs.get("limit", ["200"])[0]), 1000)
            except ValueError:
                limit = 200
            self._send_json(t10_db.search(query=q, sk_filter=sk, limit=limit))
            return

        if path == "/api/t10/detail":
            sk = qs.get("sk", ["0"])[0]
            asc = qs.get("asc", [None])[0]
            ascq = qs.get("ascq", ["00"])[0]
            self._send_json(t10_db.get_detail(sk=sk, asc=asc, ascq=ascq))
            return

        if path == "/api/sample":
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("tsr/raw/perc_tty.log", SAMPLE_TTY_LOG)
                zf.writestr("tsr/raw/lsi_20260714.log", SAMPLE_LSI_LOG)
                zf.writestr("tsr/viewer/index.html", "<html><body>Sample TSR</body></html>")
            logs, all_files = extract_logs_from_bytes("TSR_SAMPLE_POWEREDGE.zip", buf.getvalue())
            result = parse_storage_logs(logs, t10_db)
            result["filename"] = "TSR_SAMPLE_POWEREDGE.zip"
            result["archive_files_count"] = len(all_files)
            self._send_json(result)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/upload":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        content_type = self.headers.get("Content-Type", "")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0

        if length <= 0:
            self._send_json({"error": "ファイルが空です。"}, status=HTTPStatus.BAD_REQUEST)
            return

        body = self.rfile.read(length)
        parsed_file = _parse_multipart_file(content_type, body)
        if not parsed_file:
            self._send_json({"error": "ファイルが選択されていません。"}, status=HTTPStatus.BAD_REQUEST)
            return

        filename, raw_bytes = parsed_file
        if not raw_bytes:
            self._send_json({"error": "ファイルが空です。"}, status=HTTPStatus.BAD_REQUEST)
            return

        logs, all_files = extract_logs_from_bytes(filename, raw_bytes)
        if not logs:
            self._send_json(
                {
                    "error": "ストレージログ (tty / lsi / perc 等) またはテキストログがZIP内に見つかりませんでした。",
                    "archive_files_count": len(all_files),
                    "archive_files_sample": all_files[:30],
                },
                status=HTTPStatus.NOT_FOUND,
            )
            return

        result = parse_storage_logs(logs, t10_db)
        result["filename"] = filename
        result["archive_files_count"] = len(all_files)
        self._send_json(result)


def main() -> None:
    host = "127.0.0.1"
    port = 5002
    t10_db.ensure_daily_update()
    server = ThreadingHTTPServer((host, port), OfflineHandler)
    print(f"Offline local server running at http://{host}:{port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
