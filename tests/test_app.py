"""Tests for T10 database, TSR zip extraction, PERC log parsing, and Flask endpoints."""

import io
import zipfile
import pytest

from app import app
from t10_db import T10Database
from log_parser import extract_logs_from_bytes, parse_storage_logs


def test_t10_db_loads_asc_entries(tmp_path):
    db_file = tmp_path / "test_sense.db"
    db = T10Database(db_path=str(db_file))
    assert db_file.exists()
    res = db.search()
    assert res["total_asc_loaded"] > 500
    asc = db.get_asc_ascq("11", "00")
    assert asc["found"] is True
    assert "UNRECOVERED READ ERROR" in asc["description"]

    sk = db.get_sense_key("3")
    assert sk["code"] == "3h"
    assert sk["name"] == "MEDIUM ERROR"

    # Second call on the same day should skip rebuild
    assert db.ensure_daily_update(timeout=0.5) is False


def test_t10_search_by_triple_code():
    db = T10Database()
    res = db.search(query="3/11/00")
    assert len(res["sense_keys"]) == 1
    assert res["sense_keys"][0]["code"] == "3h"
    assert any(a["code"] == "11h/00h" for a in res["asc_entries"])


def test_tsr_zip_extraction_and_parsing():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("tsr/viewer/ignore.html", "<html></html>")
        zf.writestr(
            "tsr/raw/perc_tty.log",
            "07/14/26 10:12:01: Unexpected sense: PD 04(e0x20/s4), CDB: 28 00 04 12, Sense: 3/11/00\n"
            "07/14/26 10:15:00: Sense Data: 70 00 05 00 00 00 00 0A 00 00 00 00 24 00 00 00\n"
            "07/14/26 10:16:00: Disk 0:0:1 Sense key: 2 Sense code: 4 Sense qualifier: 1\n",
        )
    logs, all_files = extract_logs_from_bytes("TSR_TEST.zip", buf.getvalue())
    assert len(logs) == 1
    assert logs[0]["path"] == "tsr/raw/perc_tty.log"

    db = T10Database()
    parsed = parse_storage_logs(logs, db)
    assert parsed["total_occurrences"] == 3
    assert parsed["unique_sense_codes"] == 3
    keys = {s["key"] for s in parsed["summary"]}
    assert "3/11/00" in keys
    assert "5/24/00" in keys
    assert "2/04/01" in keys


def test_flask_endpoints():
    client = app.test_client()

    r = client.get("/")
    assert r.status_code == 200

    r = client.get("/api/sample")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_occurrences"] == 11
    assert data["unique_sense_codes"] >= 8

    r = client.get("/api/t10/search?q=24/00")
    assert r.status_code == 200
    assert any(a["code"] == "24h/00h" for a in r.get_json()["asc_entries"])

    # Test multipart upload
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("lsi_export.log", "Controller 0 SK=06 ASC=29 ASCQ=00 Reset occurred\n")
    buf.seek(0)
    r = client.post(
        "/api/upload",
        data={"file": (buf, "my_tsr.zip")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    up = r.get_json()
    assert up["total_occurrences"] == 1
    assert up["summary"][0]["key"] == "6/29/00"
