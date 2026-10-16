"""Persistent registry for local and Hub MOSS checkpoints. Never execute untrusted model code."""
from pathlib import Path
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .config import settings
from .db import connection, now_iso, query_all, query_one

class ImportModel(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    model_path: str = Field(min_length=1, max_length=2048)
    precision: str = 'bf16'

def default_model():
    return query_one("SELECT * FROM models WHERE is_default=1 LIMIT 1")

def resolve_model(model_id=None):
    model = query_one("SELECT * FROM models WHERE id=?", (model_id,)) if model_id else default_model()
    if not model:
        raise HTTPException(404, "Model not found")
    if model["status"] != "ready":
        raise HTTPException(409, "Model is not validated and ready")
    return model

def inspect_path(raw, precision):
    if precision not in ('bf16', 'fp32', 'int8'):
        raise HTTPException(422, "Unsupported precision")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise HTTPException(422, "Model directory does not exist on backend host")
    # Only import within explicitly allowed model root. No arbitrary filesystem traversal.
    root = settings.models_dir.expanduser().resolve()
    if not path.is_relative_to(root):
        raise HTTPException(403, f"Place model under allowed directory: {root}")
    if not (path / "config.json").is_file():
        raise HTTPException(422, "Missing config.json")
    weights = any(path.glob(p) for p in ("*.safetensors", "*.safetensors.index.json"))
    if not weights:
        raise HTTPException(422, "Missing safetensors weights")
    if precision == 'int8':
        return str(path), 'pending_validation'
    return str(path), 'pending_validation'

def import_model(body: ImportModel):
    path, status = inspect_path(body.model_path, body.precision)
    with connection() as con:
        existing = con.execute("SELECT id FROM models WHERE model_path=?", (path,)).fetchone()
        if existing:
            raise HTTPException(409, "Model directory already registered")
        model_id = str(uuid4())
        con.execute("INSERT INTO models(id,name,model_path,precision,status,is_default,created_at) VALUES(?,?,?,?,?,0,?)",
                    (model_id, body.name, path, body.precision, status, now_iso()))
    return query_one("SELECT * FROM models WHERE id=?", (model_id,))

def register_original():
    with connection() as con:
        exists = con.execute("SELECT 1 FROM models LIMIT 1").fetchone()
        if not exists:
            con.execute("INSERT INTO models(id,name,model_path,precision,status,is_default,created_at) VALUES(?,?,?,?,?,1,?)",
                        ("moss-original", "MOSS-TTS v1.5 Original", settings.moss_model_id, "bf16", "ready", now_iso()))

def activate(model_id):
    model = resolve_model(model_id)
    with connection() as con:
        con.execute("UPDATE models SET is_default=0 WHERE is_default=1")
        con.execute("UPDATE models SET is_default=1 WHERE id=?", (model_id,))
    return model

def list_models():
    return query_all("SELECT * FROM models ORDER BY is_default DESC, created_at DESC")
