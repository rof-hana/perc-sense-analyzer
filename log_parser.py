"""Dell TSR ZIP extractor and PERC TTY/LSI storage log Sense Key parser."""

from __future__ import annotations

import gzip
import io
import os
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from t10_db import T10Database

SAMPLE_TTY_LOG = """\
T0: 07/14/26 10:12:01: EVT#01001-07/14/26 10:12:01: 113=Unexpected sense: PD 04(e0x20/s4) Path 5000c500a1b2c3d4, CDB: 28 00 04 12 34 00 00 00 80 00, Sense: 3/11/00
T0: 07/14/26 10:12:04: EVT#01002-07/14/26 10:12:04: 113=Unexpected sense: PD 04(e0x20/s4) Path 5000c500a1b2c3d4, CDB: 28 00 04 12 34 80 00 00 80 00, Sense: 3/11/00
T0: 07/14/26 10:12:09: EVT#01003-07/14/26 10:12:09: 113=Unexpected sense: PD 04(e0x20/s4) Path 5000c500a1b2c3d4, CDB: 28 00 04 12 35 00 00 00 80 00, Sense: 3/11/0B
T0: 07/14/26 10:15:22: EVT#01004-07/14/26 10:15:22: 113=Unexpected sense: PD 02(e0x20/s2) Path 5000c50011223344, CDB: 28 00 00 00 10 00 00 00 08 00, Sense: 1/17/01
T0: 07/14/26 10:18:45: EVT#01005-07/14/26 10:18:45: 113=Unexpected sense: PD 00(e0x20/s0) Path 5000c50099887766, CDB: 1a 00 1c 00 40 00, Sense: 5/24/00
T0: 07/14/26 10:19:00: EVT#01006-07/14/26 10:19:00: 113=Unexpected sense: PD 00(e0x20/s0) Path 5000c50099887766, CDB: 4d 00 4d 00 00 00 00 00 20 00, Sense: 5/20/00
T0: 07/14/26 10:21:11: EVT#01007-07/14/26 10:21:11: 113=Unexpected sense: PD 07(e0x20/s7) Path 5000c50055667788, CDB: 00 00 00 00 00 00, Sense: 2/04/01
T0: 07/14/26 10:21:30: EVT#01008-07/14/26 10:21:30: 113=Unexpected sense: PD 07(e0x20/s7) Path 5000c50055667788, CDB: 00 00 00 00 00 00, Sense: 6/29/00
"""

SAMPLE_LSI_LOG = """\
2026-07-14T10:25:01Z Controller 0 (PERC H740P Mini) Disk 0:0:4 SCSI sense data: Sense key: 3 Sense code: 11 Sense qualifier: 0
2026-07-14T10:26:15Z Controller 0 (PERC H740P Mini) Disk 0:0:6 Sense Data: 70 00 04 00 00 00 00 0A 00 00 00 00 44 00 00 00 00 00
2026-07-14T10:27:02Z Controller 0 (PERC H740P Mini) VD 0 SK=0B ASC=4B ASCQ=00 Command aborted due to data phase error
"""

STORAGE_NAME_KEYWORDS = (
    "tty",
    "lsi",
    "perc",
    "raid",
    "megaraid",
    "stor",
    "sas",
    "ctrl",
    "controller",
    "nvme",
    "hba",
)

TEXT_EXTENSIONS = (".log", ".txt", ".out", ".tty", ".lsi", ".csv", ".raw", ".err")

# Regex patterns for Sense Key / ASC / ASCQ in PERC / LSI / MegaRAID logs
PATTERNS = [
    # 1) Raw SCSI Sense Data hex dump (e.g., "Sense Data: 70 00 03 00 00 00 00 0a 00 00 00 00 11 00 00 00")
    (
        "raw_hex",
        re.compile(
            r"(?:Sense(?:\s*Data)?|sense_data)\s*[:=]\s*\[?((?:(?:0x)?[0-9A-Fa-f]{2}[\s,]+){3,}(?:0x)?[0-9A-Fa-f]{2})\]?",
            re.IGNORECASE,
        ),
    ),
    # 2) Sense: 3/11/00 or Sense: 03/11/00 or Sense=0x03/0x11/0x00 or Sense: [05/24/00]
    (
        "slash",
        re.compile(
            r"Sense\s*[:=]\s*\[?(?:0x)?([0-9A-Fa-f]{1,2})\s*[/\-:]\s*(?:0x)?([0-9A-Fa-f]{1,2})\s*[/\-:]\s*(?:0x)?([0-9A-Fa-f]{1,2})\]?",
            re.IGNORECASE,
        ),
    ),
    # 3) Sense Key: 3 Sense code: 11 Sense qualifier: 0 (or ASC/ASCQ variants)
    (
        "labeled",
        re.compile(
            r"Sense\s*Key\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b[^;\r\n]*?\b(?:Additional\s*Sense\s*Code|Sense\s*Code|ASC)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b(?:[^;\r\n]*?\b(?:Additional\s*Sense\s*(?:Code\s*)?Qualifier|Sense\s*Qualifier|ASCQ)\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b)?",
            re.IGNORECASE,
        ),
    ),
    # 4) SK=03 ASC=11 ASCQ=00 or SK:03/ASC:11/ASCQ:00
    (
        "sk_asc",
        re.compile(
            r"\bSK\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b[\s,;/]+ASC\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b(?:[\s,;/]+ASCQ\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b)?",
            re.IGNORECASE,
        ),
    ),
    # 5) SENSE[03 11 00]
    (
        "bracket",
        re.compile(
            r"\bSENSE\s*\[\s*(?:0x)?([0-9A-Fa-f]{1,2})\s+(?:0x)?([0-9A-Fa-f]{1,2})\s+(?:0x)?([0-9A-Fa-f]{1,2})\s*\]",
            re.IGNORECASE,
        ),
    ),
    # 6) Standalone Sense Key: X (fallback when ASC/ASCQ is absent)
    (
        "sk_only",
        re.compile(
            r"\bSense\s*Key\s*[:=]\s*(?:0x)?([0-9A-Fa-f]{1,2})\b",
            re.IGNORECASE,
        ),
    ),
]

TIMESTAMP_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?|\d{2}/\d{2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}|[A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}(?:\s+\d{4})?)"
)

DEVICE_RE = re.compile(
    r"(PD\s+[0-9A-Fa-f]+(?:\([^)]+\))?|VD\s+\d+|Disk\s+\d+:\d+:\d+|Dev(?:ice)?\s*(?:ID)?\s*[:=]?\s*(?:0x)?[0-9A-Fa-f]+|Target\s+\d+|Enclosure\s+\d+\s+Slot\s+\d+|e\d+/s\d+)",
    re.IGNORECASE,
)

CDB_RE = re.compile(
    r"\bCDB\s*[:=]\s*\[?((?:[0-9A-Fa-f]{2}\s+){5,15}[0-9A-Fa-f]{2})\]?",
    re.IGNORECASE,
)


def _is_likely_text(data: bytes) -> bool:
    if not data:
        return False
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    return True


def _is_storage_log_path(path: str) -> bool:
    lower = path.lower()
    base = os.path.basename(lower)
    return any(kw in lower for kw in STORAGE_NAME_KEYWORDS) and (
        any(base.endswith(ext) for ext in TEXT_EXTENSIONS) or "." not in base or "tty" in base or "lsi" in base
    )


def extract_logs_from_bytes(
    filename: str, raw_bytes: bytes, max_depth: int = 2
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Extract candidate storage log files from a TSR .zip, .gz, or plain log file.
    Returns (storage_logs, all_filenames_seen).
    Each storage_log item is {"path": str, "content": str, "is_storage_match": bool, "size": int}.
    """
    all_files: List[str] = []
    candidates: List[Dict[str, Any]] = []

    def _walk_zip(zf_bytes: bytes, prefix: str, depth: int) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(zf_bytes)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    full_path = f"{prefix}/{info.filename}" if prefix else info.filename
                    all_files.append(full_path)
                    # Skip huge binary blobs > 50MB
                    if info.file_size > 50 * 1024 * 1024:
                        continue
                    try:
                        data = zf.read(info.filename)
                    except Exception:
                        continue

                    lower_name = info.filename.lower()
                    if lower_name.endswith(".zip") and depth < max_depth:
                        _walk_zip(data, full_path, depth + 1)
                    elif lower_name.endswith(".gz") and not lower_name.endswith(".tar.gz"):
                        try:
                            decomp = gzip.decompress(data)
                            inner_path = full_path[:-3]
                            if _is_likely_text(decomp):
                                candidates.append({
                                    "path": inner_path,
                                    "content": decomp.decode("utf-8", errors="replace"),
                                    "is_storage_match": _is_storage_log_path(inner_path),
                                    "size": len(decomp),
                                })
                        except Exception:
                            pass
                    elif _is_likely_text(data):
                        is_match = _is_storage_log_path(full_path)
                        if is_match or any(lower_name.endswith(ext) for ext in TEXT_EXTENSIONS):
                            candidates.append({
                                "path": full_path,
                                "content": data.decode("utf-8", errors="replace"),
                                "is_storage_match": is_match,
                                "size": len(data),
                            })
        except zipfile.BadZipFile:
            pass

    lower_fn = filename.lower()
    if lower_fn.endswith(".zip"):
        _walk_zip(raw_bytes, "", 0)
    elif lower_fn.endswith(".gz") and not lower_fn.endswith(".tar.gz"):
        try:
            decomp = gzip.decompress(raw_bytes)
            if _is_likely_text(decomp):
                inner = filename[:-3]
                all_files.append(inner)
                candidates.append({
                    "path": inner,
                    "content": decomp.decode("utf-8", errors="replace"),
                    "is_storage_match": True,
                    "size": len(decomp),
                })
        except Exception:
            pass
    else:
        if _is_likely_text(raw_bytes):
            all_files.append(filename)
            candidates.append({
                "path": filename,
                "content": raw_bytes.decode("utf-8", errors="replace"),
                "is_storage_match": True,
                "size": len(raw_bytes),
            })

    # Prefer explicit storage/tty/lsi logs if any were found; otherwise return all text logs
    storage_only = [c for c in candidates if c["is_storage_match"]]
    selected = storage_only if storage_only else candidates
    return selected, all_files


def _parse_raw_sense_bytes(hex_str: str) -> Optional[Tuple[str, str, str]]:
    tokens = re.findall(r"(?:0x)?([0-9A-Fa-f]{2})", hex_str)
    if len(tokens) < 4:
        return None
    b = [int(t, 16) for t in tokens]
    resp_code = b[0] & 0x7F
    if resp_code in (0x70, 0x71):
        # Fixed format sense data
        if len(b) < 14:
            return None
        sk = b[2] & 0x0F
        asc = b[12]
        ascq = b[13]
        return (f"{sk:X}", f"{asc:02X}", f"{ascq:02X}")
    if resp_code in (0x72, 0x73):
        # Descriptor format sense data
        sk = b[1] & 0x0F
        asc = b[2]
        ascq = b[3]
        return (f"{sk:X}", f"{asc:02X}", f"{ascq:02X}")
    return None


def parse_storage_logs(
    logs: List[Dict[str, Any]], t10_db: T10Database
) -> Dict[str, Any]:
    """
    Scan extracted storage logs for Sense Key / ASC / ASCQ occurrences.
    """
    occurrences: List[Dict[str, Any]] = []
    grouped: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for log in logs:
        path = log["path"]
        lines = log["content"].splitlines()
        total_lines = len(lines)

        for idx, line in enumerate(lines):
            if "sense" not in line.lower() and "sk=" not in line.lower() and "sk:" not in line.lower():
                continue

            matched: Optional[Tuple[str, Optional[str], Optional[str]]] = None
            for kind, pat in PATTERNS:
                m = pat.search(line)
                if not m:
                    continue
                if kind == "raw_hex":
                    parsed = _parse_raw_sense_bytes(m.group(1))
                    if parsed:
                        matched = parsed
                        break
                elif kind in ("slash", "bracket"):
                    sk = t10_db.normalize_sk(m.group(1))
                    asc = t10_db.normalize_byte(m.group(2))
                    ascq = t10_db.normalize_byte(m.group(3))
                    if sk:
                        matched = (sk, asc, ascq)
                        break
                elif kind in ("labeled", "sk_asc"):
                    sk = t10_db.normalize_sk(m.group(1))
                    asc = t10_db.normalize_byte(m.group(2))
                    ascq = t10_db.normalize_byte(m.group(3)) if m.group(3) else "00"
                    if sk:
                        matched = (sk, asc, ascq)
                        break
                elif kind == "sk_only":
                    sk = t10_db.normalize_sk(m.group(1))
                    if sk:
                        matched = (sk, None, None)
                        break

            if not matched:
                continue

            sk, asc, ascq = matched
            asc_key = asc if asc is not None else "--"
            ascq_key = ascq if ascq is not None else "--"

            ts_m = TIMESTAMP_RE.search(line)
            dev_m = DEVICE_RE.search(line)
            cdb_m = CDB_RE.search(line)

            start = max(0, idx - 2)
            end = min(total_lines, idx + 3)
            context_lines = [
                {"line_no": j + 1, "text": lines[j], "is_match": (j == idx)}
                for j in range(start, end)
            ]

            sk_info = t10_db.get_sense_key(sk)
            asc_info = (
                t10_db.get_asc_ascq(asc, ascq or "00")
                if asc is not None
                else None
            )

            occ = {
                "id": len(occurrences) + 1,
                "file": path,
                "line_no": idx + 1,
                "sk": sk,
                "sk_code": sk_info["code"],
                "sk_name": sk_info["name"],
                "asc": asc,
                "ascq": ascq,
                "asc_code": f"{asc_key}h/{ascq_key}h" if asc is not None else "N/A",
                "asc_description": asc_info["description"] if asc_info else "No ASC/ASCQ in log line",
                "timestamp": ts_m.group(1) if ts_m else "",
                "device": dev_m.group(1) if dev_m else "",
                "cdb": cdb_m.group(1) if cdb_m else "",
                "raw_line": line,
                "context": context_lines,
            }
            occurrences.append(occ)

            g_key = (sk, asc_key, ascq_key)
            if g_key not in grouped:
                grouped[g_key] = {
                    "key": f"{sk}/{asc_key}/{ascq_key}",
                    "sk": sk,
                    "sk_code": sk_info["code"],
                    "sk_hex": sk_info["hex"],
                    "sk_name": sk_info["name"],
                    "sk_ja_name": sk_info["ja_name"],
                    "sk_description": sk_info["description"],
                    "sk_ja_description": sk_info["ja_description"],
                    "asc": asc,
                    "ascq": ascq,
                    "asc_code": f"{asc_key}h/{ascq_key}h" if asc is not None else "N/A",
                    "asc_description": asc_info["description"] if asc_info else "No ASC/ASCQ specified",
                    "asc_device_types": asc_info["device_types"] if asc_info else [],
                    "asc_found_in_t10": asc_info["found"] if asc_info else False,
                    "count": 0,
                    "devices": set(),
                    "files": set(),
                    "occurrence_ids": [],
                }
            g = grouped[g_key]
            g["count"] += 1
            if occ["device"]:
                g["devices"].add(occ["device"])
            g["files"].add(path)
            g["occurrence_ids"].append(occ["id"])

    summary_list = []
    for g in grouped.values():
        summary_list.append({
            **g,
            "devices": sorted(g["devices"]),
            "files": sorted(g["files"]),
        })

    # Sort by occurrence count descending, then SK hex
    summary_list.sort(key=lambda x: (-x["count"], int(x["sk"], 16) if x["sk"] in "0123456789ABCDEF" else 99))

    return {
        "extracted_logs": [
            {"path": l["path"], "size": l["size"], "lines": len(l["content"].splitlines())}
            for l in logs
        ],
        "total_occurrences": len(occurrences),
        "unique_sense_codes": len(summary_list),
        "summary": summary_list,
        "occurrences": occurrences,
    }
