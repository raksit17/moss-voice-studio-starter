import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .config import settings


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connection() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.data_dir / 'studio.sqlite3', timeout=20)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    return con


def initialize() -> None:
    for directory in ('voices', 'generations'):
        (settings.data_dir / directory).mkdir(parents=True, exist_ok=True)
    with connection() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS voices (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          language TEXT NOT NULL,
          file_path TEXT NOT NULL,
          created_at TEXT NOT NULL,
          transcript TEXT NOT NULL DEFAULT '',
          character TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          voice_id TEXT,
          text TEXT NOT NULL,
          language TEXT NOT NULL,
          status TEXT NOT NULL,
          error TEXT,
          output_path TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          settings_json TEXT NOT NULL DEFAULT '{}',
          FOREIGN KEY (voice_id) REFERENCES voices(id)
        );
        CREATE TABLE IF NOT EXISTS models (
          id TEXT PRIMARY KEY, name TEXT NOT NULL,
          model_path TEXT NOT NULL UNIQUE, precision TEXT NOT NULL,
          status TEXT NOT NULL, is_default INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_default_model ON models(is_default) WHERE is_default=1;
        CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
        ''')
        fields = {row[1] for row in con.execute('PRAGMA table_info(voices)')}
        if 'transcript' not in fields:
            con.execute("ALTER TABLE voices ADD COLUMN transcript TEXT NOT NULL DEFAULT ''")
        if 'character' not in fields:
            con.execute("ALTER TABLE voices ADD COLUMN character TEXT NOT NULL DEFAULT ''")
        job_fields = {row[1] for row in con.execute('PRAGMA table_info(jobs)')}
        if 'settings_json' not in job_fields:
            con.execute("ALTER TABLE jobs ADD COLUMN settings_json TEXT NOT NULL DEFAULT '{}'")
        if 'model_id' not in job_fields:
            con.execute('ALTER TABLE jobs ADD COLUMN model_id TEXT')
        con.execute("UPDATE jobs SET status='failed', error='Server restarted before completion', updated_at=? WHERE status IN ('queued','running')", (now_iso(),))


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    with connection() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    with connection() as con:
        row = con.execute(sql, params).fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple = ()) -> None:
    with connection() as con:
        con.execute(sql, params)
        con.commit()
