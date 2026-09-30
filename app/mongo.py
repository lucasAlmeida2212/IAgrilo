"""Cliente MongoDB centralizado — pronto para Atlas + Render.

Por que este arquivo existe:
- O erro `SSL handshake failed ... TLSV1_ALERT_INTERNAL_ERROR` no Render
  acontece porque o `MongoClient` era criado sem `tlsCAFile`. No Atlas
  (mongodb+srv / *.mongodb.net) é preciso apontar explicitamente para o
  bundle de CAs do `certifi`.
- `MongoClient()` é lazy (não conecta no construtor). O que derrubava o
  boot no Render era `col_sessoes.create_index(...)` executado NO IMPORT
  em `app/memory.py`: isso força a primeira conexão ainda no boot e, se o
  Mongo estiver fora, o uvicorn nem sobe. Aqui os índices são criados de
  forma lazy via `ensure_indexes()`, que nunca levanta exceção.
"""

import logging

import certifi
from pymongo import MongoClient

import app.config as config

_log = logging.getLogger(__name__)

_client = None
_indexes_ensured = False


def _build_kwargs() -> dict:
    uri = config.MONGODB_URI or ""
    kwargs: dict = {
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 10000,
        "socketTimeoutMS": 20000,
        "retryWrites": True,
    }
    is_atlas = "mongodb+srv" in uri or "mongodb.net" in uri
    if is_atlas:
        # Atlas exige TLS com cadeia completa de CAs. Sem tlsCAFile o
        # handshake falha no Render com TLSV1_ALERT_INTERNAL_ERROR.
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = certifi.where()
    return kwargs


def get_mongo_client() -> MongoClient:
    """Singleton lazy. Não conecta até a primeira operação."""
    global _client
    if _client is None:
        if not config.MONGODB_URI:
            raise RuntimeError("MONGODB_URI ausente no .env / env do Render")
        _client = MongoClient(config.MONGODB_URI, **_build_kwargs())
    return _client


def get_db(name: str | None = None):
    """Retorna um database. Se `name` for None, usa o da URI ou 'assessor'."""
    client = get_mongo_client()
    if name:
        return client[name]
    try:
        db = client.get_default_database()
        if db is not None:
            return db
    except Exception:
        pass
    return client["assessor"]


def get_col_sessoes():
    """Collection de sessões (mantém o nome antigo: assessor.sessoes)."""
    return get_db("assessor")["sessoes"]


def get_colecao_perfil():
    """Collection de perfil. Preserva o comportamento antigo:

    `mongo_client.get_default_database("financas_db")["perfil_usuario"]`,
    ou seja: usa o DB da URI quando ela tem path, senão `financas_db`.
    """
    client = get_mongo_client()
    try:
        db = client.get_default_database(default="financas_db")
    except Exception:
        db = client["financas_db"]
    return db["perfil_usuario"]


def ensure_indexes() -> bool:
    """Cria os índices do Mongo. Retorna False (sem levantar) se o Mongo
    estiver inalcançável — o app continua no ar e o /health acusa."""
    global _indexes_ensured
    if _indexes_ensured:
        return True
    try:
        col = get_col_sessoes()
        col.create_index("session_id")
        col.create_index("iniciada_em")
        _indexes_ensured = True
        return True
    except Exception as exc:  # noqa: BLE001 — boot nunca pode cair por causa do Mongo
        _log.warning("MongoDB inalcançável em ensure_indexes(): %s", exc)
        return False


def ping_mongo(timeout_ms: int = 5000) -> bool:
    """True se o Mongo responde ao `ping`. Usado pelo /health estendido."""
    try:
        get_mongo_client().admin.command("ping")
        return True
    except Exception:
        return False
