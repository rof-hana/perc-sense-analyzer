"""Flask local web server for Dell PERC Storage Log Sense Key Search & Analyzer."""

from __future__ import annotations

import io
import zipfile
from flask import Flask, jsonify, render_template, request

from log_parser import SAMPLE_LSI_LOG, SAMPLE_TTY_LOG, extract_logs_from_bytes, parse_storage_logs
from t10_db import T10Database

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256 MB max upload

t10_db = T10Database(auto_update=True)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/t10/sense-keys", methods=["GET"])
def api_sense_keys():
    return jsonify({"sense_keys": t10_db.list_sense_keys()})


@app.route("/api/t10/search", methods=["GET"])
def api_t10_search():
    q = request.args.get("q", "")
    sk = request.args.get("sk", "")
    limit = min(int(request.args.get("limit", "200")), 1000)
    return jsonify(t10_db.search(query=q, sk_filter=sk, limit=limit))


@app.route("/api/t10/detail", methods=["GET"])
def api_t10_detail():
    sk = request.args.get("sk", "0")
    asc = request.args.get("asc")
    ascq = request.args.get("ascq", "00")
    return jsonify(t10_db.get_detail(sk=sk, asc=asc, ascq=ascq))


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "ファイルが選択されていません。"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "ファイル名が空です。"}), 400

    raw_bytes = f.read()
    if not raw_bytes:
        return jsonify({"error": "ファイルが空です。"}), 400

    logs, all_files = extract_logs_from_bytes(f.filename, raw_bytes)
    if not logs:
        return jsonify({
            "error": "ストレージログ (tty / lsi / perc 等) またはテキストログがZIP内に見つかりませんでした。",
            "archive_files_count": len(all_files),
            "archive_files_sample": all_files[:30],
        }), 404

    result = parse_storage_logs(logs, t10_db)
    result["filename"] = f.filename
    result["archive_files_count"] = len(all_files)
    return jsonify(result)


@app.route("/api/sample", methods=["GET"])
def api_sample():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("tsr/raw/perc_tty.log", SAMPLE_TTY_LOG)
        zf.writestr("tsr/raw/lsi_20260714.log", SAMPLE_LSI_LOG)
        zf.writestr("tsr/viewer/index.html", "<html><body>Sample TSR</body></html>")

    logs, all_files = extract_logs_from_bytes("TSR_SAMPLE_POWEREDGE.zip", buf.getvalue())
    result = parse_storage_logs(logs, t10_db)
    result["filename"] = "TSR_SAMPLE_POWEREDGE.zip"
    result["archive_files_count"] = len(all_files)
    return jsonify(result)


if __name__ == "__main__":
    t10_db.ensure_daily_update()
    app.run(host="127.0.0.1", port=5002, debug=False)
