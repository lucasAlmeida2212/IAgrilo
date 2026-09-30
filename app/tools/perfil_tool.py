from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from app.routes.perfil import buscar_perfil_e_restricoes


@tool
def consultar_perfil_usuario(motivo_ou_duvida: str, config: RunnableConfig) -> str:
    """
    Consulta os dados de renda, gastos, horizonte e restrições do perfil do usuário.
    Use sempre antes de fornecer conselhos sobre investimentos ou planejamento financeiro.
    """
    user_id = config.get("configurable", {}).get("user_id", "usuario_teste")
    perfil = buscar_perfil_e_restricoes(user_id=user_id, consulta_semantica=motivo_ou_duvida)
    
    if not perfil.get("cadastrado"):
        return "ATENÇÃO: O usuário ainda não possui perfil cadastrado. Oriente-o a preencher a tela de Perfil."
    
    margem = perfil['renda_mensal'] - perfil['gasto_fixo_mensal']
    
    return f"""=== DADOS DO PERFIL DO USUÁRIO ===
- Renda Mensal: R$ {perfil['renda_mensal']:.2f}
- Gasto Fixo Mensal: R$ {perfil['gasto_fixo_mensal']:.2f}
- Margem Livre Aprox.: R$ {margem:.2f}
- Horizonte de Investimento: {perfil['horizonte_meses']} meses
- Perfil de Risco: {perfil['perfil_investidor']}
- Restrições Relevantes: {perfil['restricoes_relevantes']}
"""