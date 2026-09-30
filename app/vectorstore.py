"""
Cliente Qdrant e função de embedding — centralizados aqui.

Dois consumidores:
  - memory.py   → salva/busca resumos na collection "memoria_resumos"
  - tools/faq.py → busca chunks do PDF na collection "faq_chunks"

O modelo de embedding é o mesmo para ambos (gemini-embedding-2-preview, 768d),
então instanciamos uma vez só.
"""

from qdrant_client import QdrantClient, models
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from app.config import QDRANT_URL, QDRANT_API_KEY, GEMINI_API_KEY

import logging

_log = logging.getLogger(__name__)


class _LazyQdrant:
    """Proxy que só cria o QdrantClient real no primeiro uso.

    Evita que o app caia no boot no Render quando QDRANT_URL ainda não
    está configurada — o erro aparece só ao usar a busca vetorial.
    """

    def __init__(self):
        self._real = None

    def _get(self):
        if self._real is None:
            if not QDRANT_URL:
                raise RuntimeError("QDRANT_URL ausente no .env / env do Render")
            self._real = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        return self._real

    def __getattr__(self, name):
        return getattr(self._get(), name)


qdrant = _LazyQdrant()

COLLECTION_MEMORIA = "memoria_resumos"
COLLECTION_FAQ     = "faq_chunks"
COLLECTION_RESTRICOES = "restricoes_perfil"
EMBEDDING_DIM      = 768

_embeddings = GoogleGenerativeAIEmbeddings(
    model="gemini-embedding-2-preview",
    google_api_key=GEMINI_API_KEY,
)


def gerar_embedding(texto: str) -> list[float]:
    """Gera um vetor de 768 dimensões para o texto informado."""
    return _embeddings.embed_query(texto, output_dimensionality=EMBEDDING_DIM)


def gerar_embeddings_batch(textos: list[str]) -> list[list[float]]:
    """Gera embeddings para uma lista de textos de uma vez (mais eficiente)."""
    return _embeddings.embed_documents(textos, output_dimensionality=EMBEDDING_DIM)