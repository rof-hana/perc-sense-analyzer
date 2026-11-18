"""T10.org SCSI Sense Key and ASC/ASCQ SQLite database with startup daily update."""

from __future__ import annotations

import datetime
import json
import os
import re
import sqlite3
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

T10_ASC_URL = "https://www.t10.org/lists/asc-num.txt"

# Official T10.org Sense Key definitions (https://www.t10.org/lists/2sensekey.htm)
SENSE_KEYS: Dict[str, Dict[str, str]] = {
    "0": {
        "code": "0h",
        "hex": "00",
        "name": "NO SENSE",
        "ja_name": "センス情報なし (正常/情報)",
        "description": "Indicates that there is no specific sense key information to be reported. This may occur for a successful command or for a command that receives CHECK CONDITION status because one of the filemark, EOM, or ILI bits is set to one.",
        "ja_description": "報告すべき特定のセンスキー情報がないことを示します。コマンド成功時、またはファイルマーク・EOM・ILIビット等が立っている場合に返されます。",
    },
    "1": {
        "code": "1h",
        "hex": "01",
        "name": "RECOVERED ERROR",
        "ja_name": "回復済みエラー",
        "description": "Indicates that the command completed successfully, with some recovery action performed by the device server. Details may be determined by examining the additional sense bytes and the INFORMATION field.",
        "ja_description": "デバイス側でリトライやECC訂正などのリカバリ処理が行われた上でコマンドが正常終了したことを示します。頻発する場合はドライブ劣化の予兆となることがあります。",
    },
    "2": {
        "code": "2h",
        "hex": "02",
        "name": "NOT READY",
        "ja_name": "レディ状態ではない",
        "description": "Indicates that the logical unit is not accessible. Operator intervention may be required to correct this condition (e.g., spin-up in progress, format in progress, rebuild in progress, or media not present).",
        "ja_description": "論理ユニット(ドライブ等)にアクセスできない状態です。スピンアップ中、フォーマット中、リビルド中、またはメディア未挿入などの場合に発生します。",
    },
    "3": {
        "code": "3h",
        "hex": "03",
        "name": "MEDIUM ERROR",
        "ja_name": "メディアエラー (物理媒体異常)",
        "description": "Indicates that the command terminated with a non-recovered error condition that may have been caused by a flaw in the medium or an error in the recorded data.",
        "ja_description": "記録媒体の欠陥や記録データの破損など、回復不能なメディアエラーによりコマンドが終了したことを示します。バッドセクタやHDD/SSDの物理障害の典型的なサインです。",
    },
    "4": {
        "code": "4h",
        "hex": "04",
        "name": "HARDWARE ERROR",
        "ja_name": "ハードウェアエラー",
        "description": "Indicates that the device server detected a non-recovered hardware failure (e.g., controller failure, device failure, or parity error) while performing the command or during a self-test.",
        "ja_description": "コマンド実行中またはセルフテスト中に、回復不能なハードウェア障害（コントローラ異常、ドライブ内部障害、パリティエラー等）を検出したことを示します。",
    },
    "5": {
        "code": "5h",
        "hex": "05",
        "name": "ILLEGAL REQUEST",
        "ja_name": "不正なリクエスト",
        "description": "Indicates that there was an illegal parameter in the CDB or in the additional parameters supplied as data for some commands, or an invalid command operation code.",
        "ja_description": "CDB（コマンド記述子ブロック）またはパラメータリストに不正な値・未サポートのコマンドが含まれていたことを示します。RAID配下への直接コマンド発行時などにも見られます。",
    },
    "6": {
        "code": "6h",
        "hex": "06",
        "name": "UNIT ATTENTION",
        "ja_name": "ユニットアテンション (状態変化通知)",
        "description": "Indicates that a unit attention condition has been established (e.g., removable medium may have been changed, a target has been reset, power-on occurred, or mode parameters changed).",
        "ja_description": "電源投入、バス/ターゲットリセット、メディア交換、パラメータ変更など、デバイスの状態変化が発生したことをイニシエータに通知します。",
    },
    "7": {
        "code": "7h",
        "hex": "07",
        "name": "DATA PROTECT",
        "ja_name": "データ保護 (ライトプロテクト等)",
        "description": "Indicates that a command that reads or writes the medium was attempted on a block that is protected. The read or write operation is not performed.",
        "ja_description": "書き込み禁止（ライトプロテクト）や暗号化キー不一致など、保護された領域に対する読み書きが拒否されたことを示します。",
    },
    "8": {
        "code": "8h",
        "hex": "08",
        "name": "BLANK CHECK",
        "ja_name": "ブランクチェック (未記録領域)",
        "description": "Indicates that a write-once device or a sequential-access device encountered blank medium or format-defined end-of-data indication while reading or a write-once device encountered a non-blank medium while writing.",
        "ja_description": "シーケンシャルアクセスデバイス（テープ等）や追記型メディアで、未記録領域またはEOD（データ終端）を検出したことを示します。",
    },
    "9": {
        "code": "9h",
        "hex": "09",
        "name": "VENDOR SPECIFIC",
        "ja_name": "ベンダー固有",
        "description": "This sense key is available for reporting vendor specific conditions.",
        "ja_description": "ベンダー固有のエラー・状態通知に使用されるセンスキーです。",
    },
    "A": {
        "code": "Ah",
        "hex": "0A",
        "name": "COPY ABORTED",
        "ja_name": "コピー中断",
        "description": "Indicates a COPY, COMPARE, or COPY AND VERIFY command was aborted due to an error condition on the source device, the destination device, or both.",
        "ja_description": "COPY / EXTENDED COPY 等のコマンドが、ソースまたはデスティネーション側のエラーにより中断されたことを示します。",
    },
    "B": {
        "code": "Bh",
        "hex": "0B",
        "name": "ABORTED COMMAND",
        "ja_name": "コマンド中断",
        "description": "Indicates that the device server aborted the command. The application client may be able to recover by trying the command again.",
        "ja_description": "デバイス側でコマンドが中断されたことを示します（通信エラー、タイムアウト、オーバラップコマンド等）。リトライで回復する場合があります。",
    },
    "C": {
        "code": "Ch",
        "hex": "0C",
        "name": "RESERVED (EQUAL)",
        "ja_name": "予約済み (旧 EQUAL)",
        "description": "Reserved in modern SPC standards (formerly EQUAL for SEARCH DATA commands).",
        "ja_description": "現在のT10 SPC規格では予約済み（旧SEARCH DATA用EQUAL）です。",
    },
    "D": {
        "code": "Dh",
        "hex": "0D",
        "name": "VOLUME OVERFLOW",
        "ja_name": "ボリュームオーバーフロー",
        "description": "Indicates that a buffered SCSI device has reached the end-of-partition and data may remain in the buffer that has not been written to the medium.",
        "ja_description": "バッファ付きデバイスでパーティション終端に到達し、未書き込みデータがバッファに残っている可能性を示します。",
    },
    "E": {
        "code": "Eh",
        "hex": "0E",
        "name": "MISCOMPARE",
        "ja_name": "ミスコムペア (比較不一致)",
        "description": "Indicates that the source data did not match the data read from the medium.",
        "ja_description": "VERIFYやCOMPAREコマンド等で、ソースデータとメディアから読み取ったデータが一致しなかったことを示します。",
    },
    "F": {
        "code": "Fh",
        "hex": "0F",
        "name": "COMPLETED",
        "ja_name": "完了 (予約/特殊)",
        "description": "Indicates there is sense data to be returned to an enabled ACA or completed command condition.",
        "ja_description": "完了済みコマンドまたは特定の制御状態に対するセンス情報があることを示します。",
    },
}

DEVICE_TYPE_LEGEND = {
    "D": "Direct Access Block Device (SBC-5)",
    "Z": "Host Managed Zoned Block Device (ZBC-3)",
    "T": "Sequential Access Device (SSC-5)",
    "P": "Processor Device (SPC-2)",
    "R": "C/DVD Device (MMC-6)",
    "O": "Optical Memory Block Device (SBC)",
    "M": "Media Changer Device (SMC-3)",
    "A": "Storage Array Device (SCC-2)",
    "E": "SCSI Enclosure Services (SES-3)",
    "B": "Simplified Direct-Access (RBC)",
    "K": "Optical Card Reader/Writer (OCRW)",
    "V": "Automation/Device Interface (ADC-4)",
    "F": "Object-based Storage Device (OSD-2)",
}

ASC_LINE_RE = re.compile(
    r"^([0-9A-Fa-f]{2})h/([0-9A-Fa-f]{2})h\s+([A-Za-z ]{13})\s*(.*)$"
)


class T10Database:
    def __init__(
        self,
        db_path: Optional[str] = None,
        asc_file_path: Optional[str] = None,
        auto_update: bool = False,
    ) -> None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.db_path = db_path or os.path.join(base_dir, "data", "scsi_sense.db")
        self.asc_file_path = asc_file_path or os.path.join(base_dir, "data", "asc-num.txt")

        if auto_update:
            self.ensure_daily_update()
        elif not os.path.exists(self.db_path):
            self.build_db(fetch_remote=False)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_last_updated_date(self) -> Optional[str]:
        if not os.path.exists(self.db_path):
            return None
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'last_updated_date'"
                ).fetchone()
                return row["value"] if row else None
        except sqlite3.Error:
            return None

    def ensure_daily_update(self, timeout: float = 5.0) -> bool:
        """
        Update scsi_sense.db once per startup day.
        Returns True if an update/rebuild ran, False if already up-to-date for today.
        """
        today = datetime.date.today().isoformat()
        last_date = self.get_last_updated_date()
        if last_date == today and os.path.exists(self.db_path):
            return False
        self.build_db(fetch_remote=True, timeout=timeout)
        return True

    def build_db(self, fetch_remote: bool = False, timeout: float = 5.0) -> None:
        source_label = "local:asc-num.txt"
        if fetch_remote:
            try:
                req = urllib.request.Request(
                    T10_ASC_URL, headers={"User-Agent": "PERCSenseAnalyzer/1.0"}
                )
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        raw = resp.read().decode("utf-8", errors="replace")
                        if "ASC/ASCQ" in raw:
                            os.makedirs(os.path.dirname(self.asc_file_path), exist_ok=True)
                            with open(self.asc_file_path, "w", encoding="utf-8") as f:
                                f.write(raw)
                            source_label = "remote:t10.org/lists/asc-num.txt"
            except Exception:
                # Offline or unreachable: gracefully use bundled local asc-num.txt
                pass

        asc_rows: List[Tuple[str, str, str, str, str, str]] = []
        if os.path.exists(self.asc_file_path):
            with open(self.asc_file_path, "r", encoding="utf-8", errors="replace") as f:
                for raw_line in f:
                    line = raw_line.rstrip("\r\n")
                    m = ASC_LINE_RE.match(line)
                    if not m:
                        continue
                    asc = m.group(1).upper()
                    ascq = m.group(2).upper()
                    flags = m.group(3)
                    desc = m.group(4).strip() or "(Reserved / No Description)"
                    dev_types = [
                        f"{ch}: {DEVICE_TYPE_LEGEND[ch]}"
                        for ch in flags
                        if ch in DEVICE_TYPE_LEGEND
                    ]
                    asc_rows.append(
                        (
                            asc,
                            ascq,
                            f"{asc}h/{ascq}h",
                            flags.strip(),
                            json.dumps(dev_types, ensure_ascii=False),
                            desc,
                        )
                    )

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        tmp_path = self.db_path + ".tmp"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        conn = sqlite3.connect(tmp_path)
        try:
            conn.executescript(
                """
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE sense_keys (
                    sk TEXT PRIMARY KEY,
                    sk_order INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    hex TEXT NOT NULL,
                    name TEXT NOT NULL,
                    ja_name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    ja_description TEXT NOT NULL
                );
                CREATE TABLE asc_ascq (
                    asc TEXT NOT NULL,
                    ascq TEXT NOT NULL,
                    code TEXT NOT NULL,
                    device_flags TEXT NOT NULL,
                    device_types_json TEXT NOT NULL,
                    description TEXT NOT NULL,
                    PRIMARY KEY (asc, ascq)
                );
                CREATE INDEX idx_asc_code ON asc_ascq (code);
                CREATE INDEX idx_asc_desc ON asc_ascq (description);
                """
            )
            sk_rows = [
                (
                    k,
                    int(k, 16),
                    v["code"],
                    v["hex"],
                    v["name"],
                    v["ja_name"],
                    v["description"],
                    v["ja_description"],
                )
                for k, v in SENSE_KEYS.items()
            ]
            conn.executemany(
                "INSERT INTO sense_keys VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sk_rows
            )
            conn.executemany(
                "INSERT INTO asc_ascq VALUES (?, ?, ?, ?, ?, ?)", asc_rows
            )
            today = datetime.date.today().isoformat()
            conn.executemany(
                "INSERT INTO metadata VALUES (?, ?)",
                [
                    ("last_updated_date", today),
                    ("source", source_label),
                    ("sk_count", str(len(sk_rows))),
                    ("asc_count", str(len(asc_rows))),
                ],
            )
            conn.commit()
        finally:
            conn.close()

        os.replace(tmp_path, self.db_path)

    @staticmethod
    def normalize_sk(sk: str) -> str:
        s = sk.strip().upper().replace("0X", "").rstrip("H")
        if not s:
            return ""
        try:
            val = int(s, 16) & 0x0F
            return f"{val:X}"
        except ValueError:
            return ""

    @staticmethod
    def normalize_byte(val_str: str) -> str:
        s = val_str.strip().upper().replace("0X", "").rstrip("H")
        if not s:
            return "00"
        try:
            val = int(s, 16) & 0xFF
            return f"{val:02X}"
        except ValueError:
            return "00"

    def get_sense_key(self, sk: str) -> Dict[str, str]:
        norm = self.normalize_sk(sk)
        if norm:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT code, hex, name, ja_name, description, ja_description FROM sense_keys WHERE sk = ?",
                    (norm,),
                ).fetchone()
                if row:
                    return dict(row)
        return {
            "code": f"{norm}h" if norm else "?h",
            "hex": f"0{norm}" if norm else "??",
            "name": "UNKNOWN SENSE KEY",
            "ja_name": "不明なセンスキー",
            "description": "Unrecognized Sense Key value.",
            "ja_description": "未知のセンスキー値です。",
        }

    def get_asc_ascq(self, asc: str, ascq: str) -> Dict[str, Any]:
        a = self.normalize_byte(asc)
        q = self.normalize_byte(ascq)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT asc, ascq, code, device_flags, device_types_json, description FROM asc_ascq WHERE asc = ? AND ascq = ?",
                (a, q),
            ).fetchone()
            if row:
                return {
                    "asc": row["asc"],
                    "ascq": row["ascq"],
                    "code": row["code"],
                    "device_flags": row["device_flags"],
                    "device_types": json.loads(row["device_types_json"]),
                    "description": row["description"],
                    "found": True,
                }

        a_int = int(a, 16)
        q_int = int(q, 16)
        if a_int >= 0x80 or q_int >= 0x80:
            return {
                "asc": a,
                "ascq": q,
                "code": f"{a}h/{q}h",
                "device_flags": "",
                "device_types": [],
                "description": "VENDOR SPECIFIC ASC/ASCQ (80h–FFh range)",
                "found": False,
            }
        return {
            "asc": a,
            "ascq": q,
            "code": f"{a}h/{q}h",
            "device_flags": "",
            "device_types": [],
            "description": "Not found in T10 ASC-NUM.TXT (Reserved or Vendor Specific)",
            "found": False,
        }

    def get_detail(
        self, sk: str, asc: Optional[str] = None, ascq: Optional[str] = None
    ) -> Dict[str, Any]:
        sk_info = self.get_sense_key(sk)
        asc_info = self.get_asc_ascq(asc, ascq or "00") if asc is not None else None
        return {
            "sense_key": sk_info,
            "asc_ascq": asc_info,
        }

    def list_sense_keys(self) -> List[Dict[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT code, hex, name, ja_name, description, ja_description FROM sense_keys ORDER BY sk_order ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def search(
        self, query: str = "", sk_filter: str = "", limit: int = 200
    ) -> Dict[str, Any]:
        q = query.strip().upper()
        sk_norm = self.normalize_sk(sk_filter) if sk_filter.strip() else ""

        sk_from_q = ""
        asc_q_pair: Optional[Tuple[str, str]] = None

        m3 = re.match(
            r"^(?:0X)?([0-9A-F]{1,2})[/:\s-]+(?:0X)?([0-9A-F]{1,2})[/:\s-]+(?:0X)?([0-9A-F]{1,2})$",
            q,
        )
        m2 = re.match(
            r"^(?:0X)?([0-9A-F]{1,2})[/:\s-]+(?:0X)?([0-9A-F]{1,2})$", q
        )
        if m3:
            sk_from_q = self.normalize_sk(m3.group(1))
            asc_q_pair = (
                self.normalize_byte(m3.group(2)),
                self.normalize_byte(m3.group(3)),
            )
        elif m2:
            asc_q_pair = (
                self.normalize_byte(m2.group(1)),
                self.normalize_byte(m2.group(2)),
            )

        with self._connect() as conn:
            total_asc = conn.execute("SELECT COUNT(*) FROM asc_ascq").fetchone()[0]

            all_sks = conn.execute(
                "SELECT sk, code, hex, name, ja_name, description, ja_description FROM sense_keys ORDER BY sk_order ASC"
            ).fetchall()

            matched_sks: List[Dict[str, str]] = []
            for row in all_sks:
                k = row["sk"]
                if sk_norm and k != sk_norm:
                    continue
                if sk_from_q and k != sk_from_q:
                    continue
                if not q or sk_from_q == k:
                    matched_sks.append(
                        {
                            "code": row["code"],
                            "hex": row["hex"],
                            "name": row["name"],
                            "ja_name": row["ja_name"],
                            "description": row["description"],
                            "ja_description": row["ja_description"],
                        }
                    )
                else:
                    haystack = f"{row['code']} {row['hex']} {row['name']} {row['ja_name']} {row['description']}".upper()
                    if q in haystack or q.lstrip("0X").rstrip("H") == k:
                        matched_sks.append(
                            {
                                "code": row["code"],
                                "hex": row["hex"],
                                "name": row["name"],
                                "ja_name": row["ja_name"],
                                "description": row["description"],
                                "ja_description": row["ja_description"],
                            }
                        )

            if asc_q_pair:
                a_target, q_target = asc_q_pair
                asc_rows = conn.execute(
                    "SELECT asc, ascq, code, device_flags, description FROM asc_ascq WHERE asc = ? AND ascq = ? LIMIT ?",
                    (a_target, q_target, limit),
                ).fetchall()
            elif q:
                q_clean = q.replace("0X", "").rstrip("H")
                like_q = f"%{q}%"
                asc_rows = conn.execute(
                    "SELECT asc, ascq, code, device_flags, description FROM asc_ascq WHERE UPPER(code) LIKE ? OR UPPER(description) LIKE ? OR asc = ? LIMIT ?",
                    (like_q, like_q, q_clean, limit),
                ).fetchall()
            else:
                asc_rows = conn.execute(
                    "SELECT asc, ascq, code, device_flags, description FROM asc_ascq ORDER BY asc ASC, ascq ASC LIMIT ?",
                    (limit,),
                ).fetchall()

            matched_ascs = [dict(r) for r in asc_rows]

        return {
            "sense_keys": matched_sks,
            "asc_entries": matched_ascs,
            "total_asc_loaded": total_asc,
        }


if __name__ == "__main__":
    db = T10Database()
    db.build_db(fetch_remote=False)
    print(f"Pre-generated SQLite DB at: {db.db_path}")
