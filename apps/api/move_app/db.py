import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from . import config


def now() -> float:
    return time.time()


def uid() -> str:
    return uuid.uuid4().hex


@contextmanager
def connect():
    config.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    con = sqlite3.connect(config.DATA / "move.sqlite", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


def initialize():
    with connect() as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, source_name TEXT NOT NULL,
          metadata TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
          subtitle_revision INTEGER NOT NULL DEFAULT 0,
          export_revision INTEGER, export_signature TEXT
        );
        CREATE TABLE IF NOT EXISTS cues (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          position INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
          original TEXT NOT NULL DEFAULT '', translation TEXT NOT NULL DEFAULT '',
          revision INTEGER NOT NULL DEFAULT 0, audio_hash TEXT,
          audio_duration REAL, audio_file TEXT
        );
        CREATE INDEX IF NOT EXISTS cues_project ON cues(project_id, position);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          stage TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '', error TEXT,
          payload TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)


def project(project_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row:
            value = dict(row)
            value["metadata"] = json.loads(value["metadata"])
            return value
    return None


def cues(project_id: str) -> list[dict]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                "SELECT * FROM cues WHERE project_id=? ORDER BY start,position", (project_id,)
            )
        ]


def jobs(project_id: str) -> list[dict]:
    with connect() as con:
        return [
            dict(row)
            for row in con.execute(
                "SELECT id,project_id,stage,status,progress,message,error,created,updated "
                "FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 100",
                (project_id,),
            )
        ]


def changed(con, project_id: str):
    con.execute(
        "UPDATE projects SET updated=?,subtitle_revision=subtitle_revision+1 WHERE id=?",
        (now(), project_id),
    )


def replace_cues(project_id: str, values: list[dict], con=None):
    if con is None:
        with connect() as connection:
            replace_cues(project_id, values, connection)
        return
    con.execute("DELETE FROM cues WHERE project_id=?", (project_id,))
    con.executemany(
        "INSERT INTO cues(id,project_id,position,start,end,original,translation) "
        "VALUES(?,?,?,?,?,?,?)",
        [
            (
                uid(),
                project_id,
                i,
                c["start"],
                c["end"],
                c.get("original", ""),
                c.get("translation", ""),
            )
            for i, c in enumerate(values)
        ],
    )
    changed(con, project_id)


def update_job(job_id: str, **values):
    allowed = {"status", "progress", "message", "error"}
    if not values.keys() <= allowed:
        raise ValueError("Invalid job field")
    values["updated"] = now()
    with connect() as con:
        con.execute(
            "UPDATE jobs SET " + ",".join(f"{key}=?" for key in values) + " WHERE id=?",
            (*values.values(), job_id),
        )


DEFAULTS = {
    "translation_provider": "deepseek",
    "deepseek_model": "deepseek-chat",
    "qwen_model": "qwen-plus",
    "qwen_region": "cn",
    "tts_model": "speech-02-hd",
    "tts_region": "cn",
    "voice_id": "male-qn-jingying",
    "speed": 1.0,
    "glossary": "",
    "translation_style": "自然、准确、适合口播。技术术语保持一致。",
}


def settings() -> dict:
    with connect() as con:
        stored = {
            row["key"]: json.loads(row["value"]) for row in con.execute("SELECT * FROM settings")
        }
    return DEFAULTS | stored


def save_settings(values: dict):
    with connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in values.items()],
        )
