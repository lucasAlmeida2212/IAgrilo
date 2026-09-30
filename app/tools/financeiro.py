
import psycopg2
from typing import Optional, List
from langchain.tools import tool
from pydantic import BaseModel, Field
from app.tools.perfil_tool import consultar_perfil_usuario
 

import app.config as config
 
DATABASE_URL = config.DATABASE_URL  
 
def get_conn():
    return psycopg2.connect(DATABASE_URL)
 
 
# Essa classe garante que o objeto de Python passe todos esses campos
class AddTransactionArgs(BaseModel):
    amount: float = Field(..., description="Valor da transação (use positivo).")
    source_text: str = Field(..., description="Texto original do usuário.")
    occurred_at: Optional[str] = Field(
        default=None,
        description="Timestamp ISO 8601; se ausente, usa NOW() no banco."
    )
    type_name: Optional[str] = Field(default=None, description="Nome do tipo: INCOME | EXPENSES | TRANSFER.")
    category_name:str = Field(default="outros", description="Nome da categoria: COMIDA | CONTAS | LAZER | TRANSPORTE | SAÚDE")
    category_id: Optional[int] = Field(default=None, description="FK de categories (opcional).")
    description: Optional[str] = Field(default=None, description="Descrição (opcional).")
    payment_method: Optional[str] = Field(default=None, description="Forma de pagamento (opcional).")

class QueryTransactionsArgs(BaseModel):
    query: Optional[str] = Field(None, description="Termo para busca na descrição ou texto original.")
    type_name: Optional[str] = Field(None, description="Filtrar por: INCOME, EXPENSES ou TRANSFER.")
    category_name: Optional[str] = Field(None, description="Categoria que esta atrelada a uma transação, filtrar por: COMIDA | CONTAS | LAZER | TRANSPORTE | SAÚDE ")
    date_from_local: Optional[str] = Field(None, description="Data inicial (ISO YYYY-MM-DD).")
    date_to_local: Optional[str] = Field(None, description="Data final (ISO YYYY-MM-DD).")
 
TYPE_ALIASES = {
    "INCOME":"INCOME", "GANHEI":"INCOME", "ENTRADA":"INCOME", "RECEITA":"INCOME","SALARIO":"INCOME",
    "EXPENSE":"EXPENSES","COMPREI":"EXPENSES","DESPESAS":"EXPENSES", "GASTO":"EXPENSES",
    "TRANSFER":"TRANSFER","TRANSFERENCIA":"TRANSFER", "PASSEI":"TRANSFER"
}
TYPE_CATEGORY={
    "COMIDA":"COMIDA","ALIMENTAÇÃO":"COMIDA","IFOOD":"COMIDA",
    "LUZ":"CONTAS","AGUA":"CONTAS","CONTA":"CONTAS","ALUGEL":"CONTAS",
    "ROUPA":"LAZER","CAMISETA":"LAZER","CALÇA":"LAZER","MEIA":"LAZER","TENIS":"LAZER",
    "PARQUE":"LAZER","JOGOS":"LAZER","STREAM":"LAZER","CINEMA":"LAZER","FESTA":"LAZER","VIAGEM":"LAZER",
    "ONIBUS":"TRANSPORTE","UBER":"TRANSPORTE","TREM":"TRANSPORTE","METRO":"TRANSPORTE",
    "MEDICO":"SAÚDE","DENTISTA":"SAÚDE","HOSPITAL":"SAÚDE","REMEDIO":"SAÚDE"
}
#Garante que o campo type da tabela transactions receba um id válido (1=INCOME, 2=EXPENSES, 3=TRANSFER
def _resolve_type_id(cur, type_name: Optional[str]) -> Optional[int]:
    if type_name:
        t = type_name.strip().upper()
        if t in TYPE_ALIASES:
            t = TYPE_ALIASES[t]
        cur.execute("SELECT id FROM transaction_types WHERE UPPER(type)=%s LIMIT 1;", (t,))
        row = cur.fetchone()
        return row[0] if row else None
    
def resolve_category_id(cur, category_id: Optional[int], category_name: str) -> Optional[int]:
    if category_id:
        return int(category_id)
    if category_name:
        t = category_name.strip().upper()
        if t in TYPE_CATEGORY:
            t = TYPE_CATEGORY[t]
        cur.execute("SELECT id FROM categories WHERE UPPER(name)=%s LIMIT 1;", (t,))
        row = cur.fetchone()
        if row:
            return row[0]
    cur.execute("SELECT id FROM categories WHERE UPPER(name)='OUTROS' LIMIT 1;")
    fallback = cur.fetchone()
    return fallback[0] if fallback else None

@tool("search_transactions", args_schema=QueryTransactionsArgs)
def search_transactions(
    query: Optional[str] = None,
    type_name: Optional[str] = None,
    category_name:Optional[str]=None,
    date_from_local: Optional[str] = None,
    date_to_local: Optional[str] = None,
) -> dict:
    """
    Consulta transações, despesas e ganhos individuais com filtros por texto (source_text/description), tipo e datas locais (America/Sao_Paulo).
    Os dados devem vir na seguinte ordem:
        - Intervalo (date_from_local/date_to_local): ASC (cronológico).
        - Caso contrário: DESC (mais recentes primeiro).
    """
    conn= get_conn()
    cur = conn.cursor()
    try:
        sql = """
            SELECT t.id, t.amount, tt.type, c.name, t.description, t.occurred_at, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON t.type = tt.id
            LEFT JOIN categories c ON t.category_id = c.id
            WHERE 1=1
        """
        params = []
        if query:
            sql += " AND (t.description ILIKE %s OR t.source_text ILIKE %s)"
            params.extend([f"%{query}%", f"%{query}%"])
        if type_name:
            sql += "AND UPPER(tt.type) = %s"
            params.append(type_name.upper())
        if category_name:
            sql += "AND UPPER(c.name) = %s"
            params.append(category_name.upper())
        if date_from_local:
            sql += " AND t.occurred_at >= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo'"
            params.append(date_from_local)
        if date_to_local:
            if len(date_to_local) <= 10:
                date_to_val = f"{date_to_local} 23:59:59"
            else:
                date_to_val = date_to_local
            sql += " AND t.occurred_at <= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo'"
            params.append(date_to_val)
        if date_from_local or date_to_local:
            sql += " ORDER BY t.occurred_at ASC"
        else:
            sql += " ORDER BY t.occurred_at DESC"
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "amount": float(r[1]),
                "type": r[2],
                "category": r[3],
                "description": r[4],
                "occurred_at": r[5].strftime("%d/%m/%Y %H:%M"),
                "source_text": r[6]
            })
        return {"transactions": results,"status": "ok"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        cur.close()
        conn.close()
    
@tool("saldo_total")
def saldo_total() -> dict:
    """
     Retorna o saldo total (INCOME-EXPENSES) em todo o historico (ignora o TRANSFER)
    """
    conn= get_conn()
    cur = conn.cursor()

    try:
       sql="""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 1 THEN amount ELSE 0 END), 0) - 
                COALESCE(SUM(CASE WHEN type = 2 THEN amount ELSE 0 END), 0)
            FROM transactions;
        """
       cur.execute(sql)
       resultado = cur.fetchone()[0]
       return resultado        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        cur.close()
        conn.close()


@tool("saldo_diario")
def saldo_diario(date_local: str) -> dict:
    """
    Retorna o saldo (INCOME - EXPENSES) do dia local informado (YYYY-MM-DD) em America/Sao_Paulo.
    Ignora TRANSFER (type=3).
    """
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        date_from = f"{date_local} 00:00:00"
        date_to = f"{date_local} 23:59:59"
        sql = """
        SELECT 
        (SELECT COALESCE(SUM(amount), 0) FROM transactions 
         WHERE type = 1 AND occurred_at >= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo' 
         AND occurred_at <= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo') - 
        (SELECT COALESCE(SUM(amount), 0) FROM transactions 
         WHERE type = 2 AND occurred_at >= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo' 
         AND occurred_at <= %s::timestamptz AT TIME ZONE 'America/Sao_Paulo')
        """

        cur.execute(sql, (date_from, date_to, date_from, date_to))
        row = cur.fetchone()
        valor_final = float(row[0]) if row else 0.0
        return {"status": "ok" ,"saldo_final": valor_final}

    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        cur.close()
        conn.close()
    
 
# Tool: add_transaction
@tool("add_transaction", args_schema=AddTransactionArgs)
def add_transaction(
    amount: float,
    source_text: str,
    category_name: str,
    occurred_at: Optional[str] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
) -> dict:
    """Insere uma transação financeira no banco de dados Postgres.""" 
    conn = get_conn()
    cur = conn.cursor()
    try:
        resolved_type_id = _resolve_type_id(cur, type_name)
        if not resolved_type_id:
            return {"status": "error", "message": "Tipo inválido (use type_id ou type_name: INCOME/EXPENSES/TRANSFER)."}
        
        final_category_id = resolve_category_id(cur, category_id, category_name)
        if not final_category_id:
            return {"status": "error", "message": "Erro ao resolver categoria e fallback 'OUTROS' não encontrado."}
        
        if occurred_at:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, final_category_id, description, payment_method, occurred_at, source_text),
            )
        else:
            cur.execute(
                """
                INSERT INTO transactions
                    (amount, type, category_id, description, payment_method, occurred_at, source_text)
                VALUES
                    (%s, %s, %s, %s, %s, NOW(), %s)
                RETURNING id, occurred_at;
                """,
                (amount, resolved_type_id, final_category_id, description, payment_method, source_text),
            )
 
        new_id, occurred = cur.fetchone()
        conn.commit()
        return {"status": "ok", "id": new_id, "occurred_at": str(occurred)}
 
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
 

def _get_category_id(cur, category_name: Optional[str]) -> Optional[int]:
    if not category_name:
        return None
    cur.execute(
        "SELECT id FROM categories WHERE LOWER(name) = LOWER(%s) LIMIT 1;",
        (category_name,)
    )
    row = cur.fetchone()
    return row[0] if row else None

def _local_date_filter_sql(field: str = "occurred_at") -> str:
    """
    Retorna um trecho SQL para filtragem por dia local em America/Sao_Paulo.
    Ex.: (occurred_at AT TIME ZONE 'America/Sao_Paulo')::date = %s::date
    """
    return f"(({field} AT TIME ZONE 'America/Sao_Paulo')::date = %s::date)"

class UpdateTransactionArgs(BaseModel):
    id: Optional[int] = Field(
        default=None,
        description="ID da transação a atualizar. Se ausente, será feita uma busca por (match_text + date_local)."
    )
    match_text: Optional[str] = Field(
        default=None,
        description="Texto para localizar transação quando id não for informado (busca em source_text/description)."
    )
    date_local: Optional[str] = Field(
        default=None,
        description="Data local (YYYY-MM-DD) em America/Sao_Paulo; usado em conjunto com match_text quando id ausente."
    )
    amount: Optional[float] = Field(default=None, description="Novo valor.")
    type_id: Optional[int] = Field(default=None, description="Novo type_id (1/2/3).")
    type_name: Optional[str] = Field(default=None, description="Novo type_name: INCOME | EXPENSES | TRANSFER.")
    category_id: Optional[int] = Field(default=None, description="Nova categoria (id).")
    category_name: Optional[str] = Field(default=None, description="Nova categoria (nome).")
    description: Optional[str] = Field(default=None, description="Nova descrição.")
    payment_method: Optional[str] = Field(default=None, description="Novo meio de pagamento.")
    occurred_at: Optional[str] = Field(default=None, description="Novo timestamp ISO 8601.")

@tool("update_transaction", args_schema=UpdateTransactionArgs)
def update_transaction(
    id: Optional[int] = None,
    match_text: Optional[str] = None,
    date_local: Optional[str] = None,
    amount: Optional[float] = None,
    type_id: Optional[int] = None,
    type_name: Optional[str] = None,
    category_id: Optional[int] = None,
    category_name: Optional[str] = None,
    description: Optional[str] = None,
    payment_method: Optional[str] = None,
    occurred_at: Optional[str] = None,
) -> dict:
    """
    Atualiza uma transação existente.
    Estratégias:
      - Se 'id' for informado: atualiza diretamente por ID.
      - Caso contrário: localiza a transação mais recente que combine (match_text em source_text/description)
        E (date_local em America/Sao_Paulo), então atualiza.
    Retorna: status, rows_affected, id, e o registro atualizado.
    """
    if not any([amount, type_id, type_name, category_id, category_name, description, payment_method, occurred_at]):
        return {"status": "error", "message": "Nada para atualizar: forneça pelo menos um campo (amount, type, category, description, payment_method, occurred_at)."}

    conn = get_conn()
    cur = conn.cursor()
    try:
        # Resolve target_id
        target_id = id
        if target_id is None:
            if not match_text or not date_local:
                return {"status": "error", "message": "Sem 'id': informe match_text E date_local para localizar o registro."}

            # Buscar o mais recente no dia local informado que combine o texto
            cur.execute(
                f"""
                SELECT t.id
                FROM transactions t
                WHERE (t.source_text ILIKE %s OR t.description ILIKE %s)
                  AND {_local_date_filter_sql("t.occurred_at")}
                ORDER BY t.occurred_at DESC
                LIMIT 1;
                """,
                (f"%{match_text}%", f"%{match_text}%", date_local)
            )
            row = cur.fetchone()
            if not row:
                return {"status": "error", "message": "Nenhuma transação encontrada para os filtros fornecidos."}
            target_id = row[0]

        # Resolver type_id / category_id a partir de nomes, se fornecidos
        resolved_type_id = _resolve_type_id(cur, type_id, type_name) if (type_id or type_name) else None
        resolved_category_id = category_id
        if category_name and not category_id:
            resolved_category_id = resolve_category_id(cur, category_name)

        # Montar SET dinâmico
        sets = []
        params: List[object] = []
        if amount is not None:
            sets.append("amount = %s")
            params.append(amount)
        if resolved_type_id is not None:
            sets.append("type = %s")
            params.append(resolved_type_id)
        if resolved_category_id is not None:
            sets.append("category_id = %s")
            params.append(resolved_category_id)
        if description is not None:
            sets.append("description = %s")
            params.append(description)
        if payment_method is not None:
            sets.append("payment_method = %s")
            params.append(payment_method)
        if occurred_at is not None:
            sets.append("occurred_at = %s::timestamptz")
            params.append(occurred_at)

        if not sets:
            return {"status": "error", "message": "Nenhum campo válido para atualizar."}

        params.append(target_id)

        cur.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE id = %s;",
            params
        )
        rows_affected = cur.rowcount
        conn.commit()

        # Retornar o registro atualizado
        cur.execute(
            """
            SELECT
              t.id, t.occurred_at, t.amount, tt.type AS type_name,
              c.name AS category_name, t.description, t.payment_method, t.source_text
            FROM transactions t
            JOIN transaction_types tt ON tt.id = t.type
            LEFT JOIN categories c ON c.id = t.category_id
            WHERE t.id = %s;
            """,
            (target_id,)
        )
        r = cur.fetchone()
        updated = None
        if r:
            updated = {
                "id": r[0],
                "occurred_at": str(r[1]),
                "amount": float(r[2]),
                "type": r[3],
                "category": r[4],
                "description": r[5],
                "payment_method": r[6],
                "source_text": r[7],
            }

        return {
            "status": "ok",
            "rows_affected": rows_affected,
            "id": target_id,
            "updated": updated
        }

    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": str(e)}
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass

# Exporta a lista de tools
TOOLS = [add_transaction, search_transactions, saldo_total, saldo_diario,consultar_perfil_usuario]