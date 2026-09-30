from typing import List, Literal, Dict, Any
import uuid
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from qdrant_client.http import models

from app.mongo import get_colecao_perfil
from app.vectorstore import qdrant, gerar_embedding, COLLECTION_RESTRICOES

router = APIRouter()

colecao_perfil = get_colecao_perfil()


class PerfilSchema(BaseModel):
    user_id: str = Field(..., min_length=1)
    renda_mensal: float = Field(..., gt=0)
    gasto_fixo_mensal: float = Field(..., ge=0)
    horizonte_meses: int = Field(..., ge=1, le=120)
    perfil_investidor: Literal["conservador", "moderado", "arrojado"]
    restricoes: List[str] = Field(..., min_items=1, max_items=5)

    @model_validator(mode="after")
    def validar_regras_de_negocio(self):
        if self.gasto_fixo_mensal >= self.renda_mensal:
            raise ValueError("O gasto fixo mensal deve ser obrigatoriamente menor que a renda mensal.")
        
        frases_limpas = [r.strip() for r in self.restricoes if r.strip()]
        if not frases_limpas:
            raise ValueError("A lista de restrições não pode conter apenas frases vazias.")
        self.restricoes = frases_limpas
        return self


def salvar_perfil_completo(payload: Dict[str, Any]) -> None:
    user_id = payload["user_id"]
    
    # 1. MongoDB - Upsert do perfil
    dados_estruturados = {
        "user_id": user_id,
        "renda_mensal": payload["renda_mensal"],
        "gasto_fixo_mensal": payload["gasto_fixo_mensal"],
        "horizonte_meses": payload["horizonte_meses"],
        "perfil_investidor": payload["perfil_investidor"]
    }
    colecao_perfil.replace_one({"user_id": user_id}, dados_estruturados, upsert=True)

    # 2. Qdrant - Deleta restrições antigas do mesmo usuário
    try:
        qdrant.delete(
            collection_name=COLLECTION_RESTRICOES,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
                )
            )
        )
    except Exception:
        pass

    # 3. Qdrant - Insere cada restrição individualmente
    restricoes = payload.get("restricoes", [])
    if restricoes:
        points = []
        for idx, texto_restricao in enumerate(restricoes):
            vetor = gerar_embedding(texto_restricao)
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{user_id}_{idx}"))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vetor,
                    payload={"user_id": user_id, "texto": texto_restricao}
                )
            )
        qdrant.upsert(collection_name=COLLECTION_RESTRICOES, points=points)


def buscar_perfil_e_restricoes(user_id: str, consulta_semantica: str = "") -> Dict[str, Any]:
    perfil = colecao_perfil.find_one({"user_id": user_id}, {"_id": 0})
    if not perfil:
        return {"cadastrado": False}

    restricoes_relevantes = []
    if consulta_semantica:
        try:
            vetor_query = gerar_embedding(consulta_semantica)
            resultados = qdrant.query_points(
                collection_name=COLLECTION_RESTRICOES,
                query=vetor_query,
                query_filter=models.Filter(
                    must=[models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
                ),
                limit=3
            )
            restricoes_relevantes = [hit.payload["texto"] for hit in resultados.points]
        except Exception:
            pass

    perfil["cadastrado"] = True
    perfil["restricoes_relevantes"] = restricoes_relevantes
    return perfil


@router.post("/perfil", status_code=status.HTTP_200_OK)
async def post_perfil(payload: PerfilSchema):
    try:
        dados = payload.model_dump()
        salvar_perfil_completo(dados)
        return dados
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))