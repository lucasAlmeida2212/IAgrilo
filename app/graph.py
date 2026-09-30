import operator
from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, MessagesState,END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig 
from app.tools.memoria import TOOLS_MEMORIA 
from app.tools.financeiro import TOOLS
from app.tools.faq import faq_retriever
from app.prompts import (
    ROUTER_PROMPT_COMPLETO,
    FINANCEIRO_PROMPT_COMPLETO,
    AGENDA_PROMPT_COMPLETO,
    ORQUESTRADOR_PROMPT_COMPLETO,
    FAQ_PROMPT_COMPLETO
)
from app.guardrail import guardrail_entrada, guardrail_saida, anonimizar_entrada
from langchain_core.messages import RemoveMessage
from app.memory import iniciar_sessao, salvar_mensagem, encerrar_sessao
import app.config as config
from app.llms import (
    llm_rapido,
    llm_especialista,

)
from app.memory import salvar_mensagem


memory = MemorySaver()

router_app       = create_agent(model=llm_rapido,       tools=TOOLS_MEMORIA,                system_prompt=ROUTER_PROMPT_COMPLETO)
financeiro_app   = create_agent(model=llm_especialista, tools=TOOLS + TOOLS_MEMORIA,        system_prompt=FINANCEIRO_PROMPT_COMPLETO)
agenda_app       = create_agent(model=llm_especialista, tools=TOOLS_MEMORIA, system_prompt=AGENDA_PROMPT_COMPLETO)
orquestrador_app = create_agent(model=llm_rapido,       system_prompt=ORQUESTRADOR_PROMPT_COMPLETO)
faq_app          = create_agent(model=llm_rapido,       tools=[faq_retriever], system_prompt=FAQ_PROMPT_COMPLETO)

# ==============================================================================
# ESTADO
# ==============================================================================
class Estado(MessagesState):
    agente_chamados:Annotated[list[str],operator.add]
    rota:str
    mapa_pii: dict
    sessao_id: str

# ==============================================================================
# NÓS
# ==============================================================================
def no_roteador(estado: Estado, config: RunnableConfig) -> dict:
    saida = router_app.invoke({"messages": list(estado["messages"])}, config=config)
    texto = saida["messages"][-1].text
    
    if "ROUTE=" not in texto:
        return {
            "agentes_chamados": ["roteador"],
            "rota": "fim",
            "messages": [{"role": "assistant", "content": texto}]
        }
    
    rota = "fim"  # Valor padrão caso falhe
    for linha in texto.splitlines():
        if linha.startswith("ROUTE="):
            rota = linha.split("=", 1)[1].strip()
            break
    return {
        "agente_chamados": ["roteador"],
        "rota": rota
    }


def no_orquestrador(estado: Estado) -> dict:
    ultima_especialista = ""
    for mensagem in reversed (estado["messages"]):
        if mensagem.type =="ai" and mensagem.content:
            ultima_especialista = mensagem.content
            break
    saida = orquestrador_app.invoke(
        {"messages":[{"role":"human", "content": ultima_especialista}]}
    )
    return {
            "agente_chamados":[estado["rota"],"orquestrador"],
            "messages":[{"role":"assistant", "content":saida["messages"][-1].content}]
        }

def no_guardrail_entrada(estado: Estado) -> dict:
    print("Estado:", estado)
    mensagem_usuario = estado["messages"][-1]       
    pergunta_usuario = mensagem_usuario.content
    salvar_mensagem(session_id=estado["sessao_id"], role="human", content=pergunta_usuario)

    print("estado:", estado)
    pergunta_anonimizada, mapa_pii = anonimizar_entrada(pergunta_usuario)
    resultado_guardrail = guardrail_entrada(pergunta_anonimizada)

    if resultado_guardrail["bloqueado"]:
        return {
            "rota": "fim",
            "messages": [{"role": "assistant", "content": resultado_guardrail["mensagem"]}],
        }
    print(f"--- DEBUG GUARDRAIL OUTPUT: '{resultado_guardrail['mensagem']}' ---")
    return {
        "rota": "roteador",
        "messages": [
            RemoveMessage(id=mensagem_usuario.id),              
            {"role": "human", "content": pergunta_anonimizada}, 
        ],
        "mapa_pii": mapa_pii,
    }
    
    
def no_guardrail_saida(estado: Estado) -> dict:
    resposta_orquestrador = estado["messages"][-1].content
    mapa_pii = estado["mapa_pii"]
    resposta_revisada = guardrail_saida(resposta_orquestrador, mapa_pii, {})
    return {
        "agentes_chamados":["guardrail_saida"],
        "rota":"fim",
        "messages":[{"role":"assistant", "content":resposta_revisada["mensagem"]}]
    }

def decidir_pos_guardrail_entrada(estado: Estado) -> str:
    rota_final = estado["rota"]
    if rota_final in "fim":
        return "fim"
    else:
        return "roteador"
# ==============================================================================
# FUNÇÃO DE DECISÃO
# ==============================================================================
def decidir_especialista(estado: Estado) -> str:
    """Lê o protocolo do roteador e devolve o nome do próximo nó."""
    return estado["rota"] if estado["rota"] in ("financeiro", "agenda", "faq") else "fim"




# ==============================================================================
# CONSTRUÇÃO DO GRAFO
# ==============================================================================
grafo = StateGraph(Estado)

grafo.add_node("roteador",     no_roteador)
grafo.add_node("financeiro",   financeiro_app)
grafo.add_node("agenda",       agenda_app)
grafo.add_node("faq",          faq_app)
grafo.add_node("orquestrador", no_orquestrador)
grafo.add_node("guardrail_entrada",  no_guardrail_entrada)   
grafo.add_node("guardrail_saida",    no_guardrail_saida)

grafo.set_entry_point("guardrail_entrada")
grafo.add_conditional_edges(
    "guardrail_entrada",
    decidir_pos_guardrail_entrada,
    {
        "roteador": "roteador",
        "fim":   END
    },
)
grafo.add_conditional_edges(
    "roteador",
    decidir_especialista,
    {
        "financeiro": "financeiro",
        "agenda":     "agenda",
        "faq":        "faq",
        "fim":        END,
    },
)

grafo.add_edge("financeiro",   "orquestrador")
grafo.add_edge("agenda",       "orquestrador")
grafo.add_edge("orquestrador", "guardrail_saida")
grafo.add_edge("guardrail_saida", END)
grafo.add_edge("faq",          END)   # FAQ bypassa o orquestrador

# Memória centralizada no grafo — persiste o Estado inteiro entre turns
memory = MemorySaver()
fluxo_agentes = grafo.compile(checkpointer=memory)


# ==============================================================================
# FLUXO PRINCIPAL
# ==============================================================================
def executar_fluxo_assessor(
    pergunta_usuario: str, session_id: str, user_id: str = "usuario_teste"
) -> str:
    pergunta_usuario_anonimizado, _ = anonimizar_entrada(pergunta_usuario)
    estado_inicial = {
        "messages":         [{"role": "human", "content": pergunta_usuario}],
        "agentes_chamados": [],
        "rota":             "",
        "mapa_pii":         {},
        "sessao_id":       session_id,
    }

    estado_final = fluxo_agentes.invoke(
        estado_inicial,
        config={"configurable": {"thread_id": session_id, "user_id": user_id}},
    )

    resposta = estado_final["messages"][-1].content
    
    salvar_mensagem(session_id, "human",     pergunta_usuario_anonimizado, user_id=user_id)
    salvar_mensagem(session_id, "assistant", resposta, user_id=user_id)

    return resposta


# if __name__ == "__main__":
#     while True:
#         pergunta_usuario = input("\nUsuário: ")
#         if pergunta_usuario.lower() in ["sair", "exit", "quit"]:
#             print("Encerrando o assistente.")
#             encerrar_sessao(session_id)
#             break
#         try:
#             resposta = executar_fluxo_assessor(
#                 pergunta_usuario=pergunta_usuario,
#                 session_id=session_id
#             )
#             print(f"Assistente: {resposta}")
#         except Exception as e:
#             print(f"Erro: {e}")
