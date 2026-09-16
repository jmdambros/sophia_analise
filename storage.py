"""
storage.py
----------
Persistência mínima em SQLite para o protótipo. Guarda, por caso: nome,
transcrição, documentos (metadados), última análise (JSON) e histórico de
chat. Isso corresponde à "estrutura de dados por caso" da Seção 11.

Chaves de API: para este protótipo, a chave é criptografada com Fernet
(chave simétrica derivada de uma SOPHIA_SECRET_KEY de ambiente) e nunca
fica em texto puro no banco. Em produção real, isso deveria migrar para
um cofre de segredos gerenciado (ex.: KMS/HashiCorp Vault) — ver README.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet

DB_PATH = os.environ.get("SOPHIA_DB_PATH", "sophia.db")


def _get_fernet() -> Fernet:
    key = os.environ.get("SOPHIA_SECRET_KEY")
    if not key:
        # Gera uma chave de desenvolvimento e avisa — NÃO usar em produção.
        key = Fernet.generate_key().decode()
        print(
            "[AVISO] SOPHIA_SECRET_KEY não definida no ambiente. Usando uma "
            "chave temporária gerada em memória só para esta execução — as "
            "chaves de API salvas não sobreviverão a um restart. Defina "
            "SOPHIA_SECRET_KEY em produção."
        )
        os.environ["SOPHIA_SECRET_KEY"] = key
    return Fernet(key.encode() if isinstance(key, str) else key)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                nome TEXT NOT NULL,
                transcricao TEXT,
                documentos_meta TEXT,
                analise_json TEXT,
                chat_history TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT
            )
            """
        )


def create_case(case_id: str, nome: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cases (id, nome, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (case_id, nome, now, now),
        )


def update_case_analysis(
    case_id: str,
    transcricao: str,
    documentos_meta: List[Dict[str, Any]],
    analise_json: Dict[str, Any],
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE cases
            SET transcricao = ?, documentos_meta = ?, analise_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                transcricao,
                json.dumps(documentos_meta, ensure_ascii=False),
                json.dumps(analise_json, ensure_ascii=False),
                datetime.utcnow().isoformat(),
                case_id,
            ),
        )


def append_chat_turn(case_id: str, role: str, content: str) -> List[Dict[str, str]]:
    with get_conn() as conn:
        row = conn.execute("SELECT chat_history FROM cases WHERE id = ?", (case_id,)).fetchone()
        history = json.loads(row["chat_history"]) if row and row["chat_history"] else []
        history.append({"role": role, "content": content})
        conn.execute(
            "UPDATE cases SET chat_history = ?, updated_at = ? WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), datetime.utcnow().isoformat(), case_id),
        )
        return history


def get_case(case_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["documentos_meta"] = json.loads(d["documentos_meta"]) if d["documentos_meta"] else []
        d["analise_json"] = json.loads(d["analise_json"]) if d["analise_json"] else None
        d["chat_history"] = json.loads(d["chat_history"]) if d["chat_history"] else []
        return d


def list_cases() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, nome, updated_at FROM cases ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def delete_case(case_id: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM cases WHERE id = ?", (case_id,))


def encrypt_api_key(raw_key: str) -> str:
    return _get_fernet().encrypt(raw_key.encode()).decode()


def decrypt_api_key(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()
