from __future__ import annotations

import sqlite3
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from medicalfacefound.service.heatmap_settings import AGE_HEATMAP_LABELS, DEFAULT_HEATMAP_METHOD

EXPLANATION_COLUMNS = {
    "block": ("explanation_image", "explanation_created_at"),
    "norm1": ("norm1_explanation_image", "norm1_explanation_created_at"),
    "hirescam": ("hirescam_explanation_image", "hirescam_explanation_created_at"),
    "layercam": ("layercam_explanation_image", "layercam_explanation_created_at"),
}


@dataclass(frozen=True)
class CaptureRecord:
    id: str
    created_at: str


@contextmanager
def connect(database_path: Path):
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if not database_path.exists():
        descriptor = os.open(database_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
    os.chmod(database_path, 0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database_path) + suffix)
        if sidecar.exists():
            os.chmod(sidecar, 0o600)
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA secure_delete = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path) -> None:
    if database_path.is_file() and database_path.stat().st_size:
        backup_database(database_path, "before-start")
    with connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS captures (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                age INTEGER NOT NULL CHECK (age BETWEEN 0 AND 120),
                gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other', 'unspecified')),
                height_cm REAL NOT NULL CHECK (height_cm BETWEEN 30 AND 250),
                weight_kg REAL NOT NULL CHECK (weight_kg BETWEEN 1 AND 500),
                capture_source TEXT NOT NULL CHECK (capture_source IN ('camera', 'upload')),
                filename TEXT,
                content_type TEXT NOT NULL,
                image_format TEXT NOT NULL,
                image_width INTEGER NOT NULL,
                image_height INTEGER NOT NULL,
                image_size_bytes INTEGER NOT NULL,
                image_data BLOB NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_captures_created_at ON captures(created_at)"
        )
        existing = {row[1] for row in connection.execute("PRAGMA table_info(captures)")}
        for name, kind in {
            "request_id": "TEXT", "payload_hash": "TEXT", "access_hash": "TEXT",
            "consent_version": "TEXT", "consented_at": "TEXT", "quality_json": "TEXT",
            "processed_image": "BLOB", "crop_box": "TEXT", "deletion_requested_at": "TEXT",
            "updated_at": "TEXT",
        }.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE captures ADD COLUMN {name} {kind}")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_capture_request ON captures(request_id)")
        connection.execute("""CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY, capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            model TEXT NOT NULL, model_version TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 1,
            result_json TEXT, error TEXT, UNIQUE(capture_id, model, model_version))""")
        prediction_columns = {row[1] for row in connection.execute("PRAGMA table_info(predictions)")}
        for image_column, timestamp_column in EXPLANATION_COLUMNS.values():
            for name, kind in ((image_column, "BLOB"), (timestamp_column, "TEXT")):
                if name not in prediction_columns:
                    connection.execute(f"ALTER TABLE predictions ADD COLUMN {name} {kind}")
        if "explanation_method" not in prediction_columns:
            connection.execute("ALTER TABLE predictions ADD COLUMN explanation_method TEXT")
        connection.execute("""CREATE TABLE IF NOT EXISTS site_settings (
            key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        connection.execute("CREATE TABLE IF NOT EXISTS admin_events (id INTEGER PRIMARY KEY, created_at TEXT, action TEXT, capture_id TEXT)")
        event_columns = {row[1] for row in connection.execute("PRAGMA table_info(admin_events)")}
        if "detail" not in event_columns:
            connection.execute("ALTER TABLE admin_events ADD COLUMN detail TEXT")
        connection.execute("""CREATE TABLE IF NOT EXISTS capture_tags (
            capture_id TEXT NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (capture_id, tag))""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_capture_tags_tag ON capture_tags(tag)")
        connection.execute("UPDATE predictions SET status='failed', error='服务重启中断了分析，请重试' WHERE status='running'")
    os.chmod(database_path, 0o600)


def save_capture(
    *,
    database_path: Path,
    age: int,
    gender: str,
    height_cm: float,
    weight_kg: float,
    capture_source: str,
    filename: str | None,
    content_type: str,
    image_format: str,
    image_width: int,
    image_height: int,
    image_data: bytes,
) -> CaptureRecord:
    capture_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO captures (
                id, created_at, age, gender, height_cm, weight_kg,
                capture_source, filename, content_type, image_format,
                image_width, image_height, image_size_bytes, image_data
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capture_id,
                created_at,
                age,
                gender,
                height_cm,
                weight_kg,
                capture_source,
                filename,
                content_type,
                image_format,
                image_width,
                image_height,
                len(image_data),
                sqlite3.Binary(image_data),
            ),
        )
    return CaptureRecord(id=capture_id, created_at=created_at)


def now():
    return datetime.now(timezone.utc).isoformat()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def backup_database(path: Path, label="manual"):
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    target = directory / f"{label}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}.sqlite3"
    # Create with restrictive permissions before SQLite opens it.
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with sqlite3.connect(path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target.name


class RecordConflict(ValueError):
    pass


def save_verified_capture(path, *, content, decoded, profile, request_id, access_token, consent_version,
                          quality, processed, mask_content=None):
    encoded_profile = json.dumps(profile, sort_keys=True)
    hasher = hashlib.sha256(content + encoded_profile.encode() + consent_version.encode() + access_token.encode())
    if mask_content is not None:
        hasher.update(hashlib.sha256(mask_content).digest())
    fingerprint = hasher.hexdigest()
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT id, created_at, payload_hash FROM captures WHERE request_id=?", (request_id,)).fetchone()
        if previous:
            if previous["payload_hash"] != fingerprint:
                raise RecordConflict("同一提交编号的内容发生变化，请重新开始采集")
            return CaptureRecord(previous["id"], previous["created_at"])
        identity, timestamp = str(uuid4()), now()
        content_type = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[decoded.format]
        conn.execute("""INSERT INTO captures
            (id,created_at,age,gender,height_cm,weight_kg,capture_source,filename,content_type,image_format,
             image_width,image_height,image_size_bytes,image_data,request_id,payload_hash,access_hash,
             consent_version,consented_at,quality_json,processed_image,crop_box)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (identity,timestamp,profile["age"],profile["gender"],profile["height_cm"],profile["weight_kg"],
             profile["capture_source"],profile["filename"],content_type,decoded.format,decoded.width,decoded.height,
             len(content),content,request_id,fingerprint,token_hash(access_token),consent_version,timestamp,
             json.dumps({k:v for k,v in quality.items() if k != "preview"}, ensure_ascii=False),processed,
             json.dumps(quality["crop_box"])))
        return CaptureRecord(identity, timestamp)


def capture_row(path, identity):
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM captures WHERE id=?", (identity,)).fetchone()
        return dict(row) if row else None


def report(path, identity):
    with connect(path) as conn:
        row = conn.execute("""SELECT id,created_at,updated_at,age,gender,height_cm,weight_kg,capture_source,
            image_width,image_height,consent_version,consented_at,quality_json,crop_box,deletion_requested_at
            FROM captures WHERE id=?""", (identity,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("quality_json", "crop_box"):
            result[key] = json.loads(result[key]) if result[key] else None
        result["tags"] = [item[0] for item in conn.execute(
            "SELECT tag FROM capture_tags WHERE capture_id=? ORDER BY tag", (identity,))]
        predictions = conn.execute("SELECT * FROM predictions WHERE capture_id=? ORDER BY created_at", (identity,)).fetchall()
        result["predictions"] = []
        for entry in predictions:
            item = dict(entry)
            raw_result = item.pop("result_json")
            item["result"] = json.loads(raw_result) if raw_result else None
            item["has_explanation"] = bool(item.pop("explanation_image", None))
            item["has_norm1_explanation"] = bool(item.pop("norm1_explanation_image", None))
            item["has_hirescam_explanation"] = bool(item.pop("hirescam_explanation_image", None))
            item["has_layercam_explanation"] = bool(item.pop("layercam_explanation_image", None))
            result["predictions"].append(item)
        return result


def reserve_prediction(path, identity, model, version):
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        capture = conn.execute("SELECT deletion_requested_at FROM captures WHERE id=?", (identity,)).fetchone()
        if not capture or capture[0]:
            raise RecordConflict("该记录已删除或已申请删除，无法继续分析")
        row = conn.execute("SELECT * FROM predictions WHERE capture_id=? AND model=? AND model_version=?", (identity, model, version)).fetchone()
        if row:
            if row["status"] == "completed":
                return row["id"], json.loads(row["result_json"])
            if row["status"] == "running":
                raise RecordConflict("该指标正在分析，请稍后查看结果")
            conn.execute("UPDATE predictions SET status='running',error=NULL,updated_at=?,attempts=attempts+1 WHERE id=?", (now(),row["id"]))
            return row["id"], None
        prediction_id = str(uuid4())
        conn.execute("INSERT INTO predictions (id,capture_id,model,model_version,status,created_at,updated_at) VALUES (?,?,?,?,'running',?,?)",
                     (prediction_id,identity,model,version,now(),now()))
        return prediction_id, None


def finish_prediction(path, identity, result=None, error=None):
    with connect(path) as conn:
        conn.execute("UPDATE predictions SET status=?,updated_at=?,result_json=?,error=? WHERE id=?",
                     ("failed" if error else "completed",now(),json.dumps(result,ensure_ascii=False) if result else None,error,identity))


def save_explanation(path, prediction_id, image, *, variant="block", include_deletion_requested=False):
    image_column, timestamp_column = EXPLANATION_COLUMNS[variant]
    with connect(path) as conn:
        cursor = conn.execute(
            f"""UPDATE predictions SET {image_column}=?, {timestamp_column}=?
               WHERE id=? AND status='completed'
                 AND (? OR EXISTS (SELECT 1 FROM captures
                     WHERE captures.id=predictions.capture_id AND deletion_requested_at IS NULL))""",
            (sqlite3.Binary(image), now(), prediction_id, include_deletion_requested),
        )
        return cursor.rowcount == 1


def prediction_explanation(path, capture_id, prediction_id, *, variant="block"):
    image_column, _ = EXPLANATION_COLUMNS[variant]
    with connect(path) as conn:
        row = conn.execute(f"SELECT {image_column} FROM predictions WHERE id=? AND capture_id=?",
                           (prediction_id, capture_id)).fetchone()
        return bytes(row[0]) if row and row[0] else None


def age_heatmap_method(path):
    with connect(path) as conn:
        row = conn.execute("SELECT value FROM site_settings WHERE key='age_heatmap_method'").fetchone()
        if row and row[0] in AGE_HEATMAP_LABELS:
            return row[0]
        return DEFAULT_HEATMAP_METHOD


def set_age_heatmap_method(path, method):
    with connect(path) as conn:
        conn.execute("""INSERT INTO site_settings(key,value) VALUES ('age_heatmap_method',?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value""", (method,))
        audit(conn, "age_heatmap_method", detail={"method": method})


def set_explanation_method(path, prediction_id, method):
    with connect(path) as conn:
        conn.execute("""UPDATE predictions SET explanation_method=? WHERE id=? AND status='completed'
            AND EXISTS (SELECT 1 FROM captures WHERE captures.id=predictions.capture_id
                        AND deletion_requested_at IS NULL)""", (method, prediction_id))


def audit(conn, action, identity=None, detail=None):
    conn.execute("INSERT INTO admin_events (created_at,action,capture_id,detail) VALUES (?,?,?,?)",
                 (now(), action, identity, json.dumps(detail, ensure_ascii=False) if detail is not None else None))


def set_age(path, identity, age):
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT age FROM captures WHERE id=?", (identity,)).fetchone()
        if not row:
            raise KeyError(identity)
        previous = row[0]
        conn.execute("UPDATE captures SET age=?, updated_at=? WHERE id=?", (age, now(), identity))
        audit(conn, "edit_age", identity, {"from": previous, "to": age})
        return previous


def set_tags(path, identity, tags):
    with connect(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM captures WHERE id=?", (identity,)).fetchone():
            raise KeyError(identity)
        previous = [item[0] for item in conn.execute(
            "SELECT tag FROM capture_tags WHERE capture_id=? ORDER BY tag", (identity,))]
        timestamp = now()
        conn.execute("DELETE FROM capture_tags WHERE capture_id=?", (identity,))
        conn.executemany("INSERT INTO capture_tags (capture_id,tag,created_at) VALUES (?,?,?)",
                         [(identity, tag, timestamp) for tag in tags])
        conn.execute("UPDATE captures SET updated_at=? WHERE id=?", (timestamp, identity))
        audit(conn, "set_tags", identity, {"from": previous, "to": list(tags)})
        return previous


def list_tags(path):
    with connect(path) as conn:
        rows = conn.execute("""SELECT tag, count(*) AS count FROM capture_tags
            GROUP BY tag ORDER BY count DESC, tag""").fetchall()
        return [dict(row) for row in rows]


def list_captures(path, start=None, end=None, status="all", tag=None, limit=20, offset=0):
    conditions, args = [], []
    if start:
        conditions.append("c.created_at >= ?")
        args.append(start)
    if end:
        conditions.append("c.created_at < ?")
        args.append(end)
    if status == "failed":
        conditions.append("EXISTS (SELECT 1 FROM predictions p WHERE p.capture_id=c.id AND p.status='failed')")
    if status == "deletion":
        conditions.append("c.deletion_requested_at IS NOT NULL")
    if tag:
        conditions.append("EXISTS (SELECT 1 FROM capture_tags t WHERE t.capture_id=c.id AND t.tag=?)")
        args.append(tag)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with connect(path) as conn:
        total = conn.execute("SELECT count(*) FROM captures c"+where,args).fetchone()[0]
        rows = conn.execute("""SELECT c.id,c.created_at,c.updated_at,c.age,c.gender,c.capture_source,c.deletion_requested_at,
            (SELECT count(*) FROM predictions p WHERE p.capture_id=c.id AND p.status='completed') AS completed,
            (SELECT count(*) FROM predictions p WHERE p.capture_id=c.id AND p.status='failed') AS failed
            FROM captures c"""+where+" ORDER BY c.created_at DESC LIMIT ? OFFSET ?",[*args,limit,offset]).fetchall()
        items = [dict(row) for row in rows]
        if items:
            placeholders = ",".join("?" for _ in items)
            tag_rows = conn.execute(f"SELECT capture_id,tag FROM capture_tags WHERE capture_id IN ({placeholders}) ORDER BY tag",
                                    [item["id"] for item in items]).fetchall()
            tag_map = {}
            for capture_id, name in tag_rows:
                tag_map.setdefault(capture_id, []).append(name)
            for item in items:
                item["tags"] = tag_map.get(item["id"], [])
        return {"total":total,"items":items}
