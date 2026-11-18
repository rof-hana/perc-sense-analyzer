# PERC Sense Key Analyzer (T10.org SCSI Reference)

Dell PERC のストレージログ（TSR `.zip` 内の TTY ログ / LSI ログ等）から SCSI Sense Key / ASC / ASCQ を抽出し、**T10.org 標準仕様** と照合して一覧表示・詳細確認・検索ができるローカル Web ツール（Flask + HTML/CSS/JS）です。

## 特徴
- **実行形式 (.exe) 不要**: Python + Flask のローカル Web サーバとして動作します。
- **TSR ZIP 自動展開**: `.zip`（ネストされた `.zip` / `.gz` 含む）または `.log`/`.txt` をアップロードすると、`tty` / `lsi` / `perc` / `raid` 等のストレージログを自動抽出します。
- **マルチフォーマット対応**:
  - `Sense: 3/11/00` / `Sense: 0x03/0x11/0x00`
  - `Sense key: 3 Sense code: 11 Sense qualifier: 0`
  - `SK=03 ASC=11 ASCQ=00`
  - 生の SCSI Sense Data 16進ダンプ (`70 00 03 ... 11 00 ...` / Descriptor 形式 `72 ...`)
- **T10.org 標準データ網羅**: `data/asc-num.txt`（T10.org 公式 `ASC-NUM.TXT`）と Sense Key `0h`–`Fh` を内蔵し、オフライン環境でも T10 標準のリファレンス検索が可能です。
- **モノクロ UI**: 視認性の高いモノクロデザイン。

## 起動方法（完全オフライン対応）

### 方法A: 標準ライブラリのみで起動（追加インストール不要・完全オフライン向け）
Python 3 が入っていれば、`pip install` すら不要でそのまま起動できます。

```bash
python3 offline_server.py
```

### 方法B: Flask を使って起動

```bash
python3 -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python app.py
```

ブラウザで `http://127.0.0.1:5002` を開きます。

## Sense Key データベースについて
- SCSI 標準規格 (T10.org) に基づく Sense Key / ASC / ASCQ データは `data/scsi_sense.db` (SQLite) として事前生成されています。
- `app.py`（または `offline_server.py`）の起動時に、その日の初回起動であれば自動的にデータベースの更新チェックを行います（オフライン環境では同梱の `data/asc-num.txt` を使用して安全にフォールバックします）。

