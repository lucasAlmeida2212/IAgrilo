# JUSTIFICATIVA DO PROJETO - SISTEMA DE PERFIL DO USUÁRIO

### 1. Quais arquivos você criou ou modificou? Indique o caminho de cada um.
* **Criado:** `app/routes/perfil.py` (rota `POST /perfil`, validação Pydantic e lógica de persisência) e `app/tools/perfil_tool.py` (tool do LangChain para consulta do agente).
* **Modificado:** `app/main.py`, `app/vectorstore.py`, `app/tools/financeiro.py` e `app/prompts.py`.

### 2. Por onde o perfil entra, e onde cada parte dele é gravada?
* O perfil entra pela rota HTTP `POST /perfil` via formulário frontend.
* Os dados estruturados (renda, gastos, horizonte e perfil de risco) são gravados no **MongoDB**, enquanto as restrições em texto livre são convertidas em embeddings e salvas individualmente no **Qdrant**.

### 3. Como o texto livre é indexado e consultado, e por que não é busca por palavra?
* Cada frase é transformada em um vetor numérico de 768 dimensões com o Gemini Embeddings e consultada via distância de cosseno no Qdrant.
* Não é busca por palavras-chave para capturar o sentido semântico das restrições, permitindo encontrar contextos equivalentes mesmo com vocabulário diferente, no caso mesmo que 2 frases tenham palavras diferentes, ainda sim a busca sera realizada por conta do sentido da frase.

### 4. Você criou uma tool ou duas? Por quê?
* Foi criada apenas **uma tool** unificada (`consultar_perfil_usuario`).
* Isso reduz o overhead do agente e otimiza a latência, recuperando tanto os dados estruturados do MongoDB quanto a busca semântica do Qdrant em uma única chamada.

### 5. O que garante que o perfil de um usuário não apareceria para outro, se houvesse mais de um?
* O isolamento estrito via Multitenancy usando o campo `user_id`.
* Todas as operações de leitura e exclusão aplicam filtros obrigatórios pelo `user_id` extraído com segurança via `RunnableConfig` na sessão atrelada ao usuário.

### 6. Sua tool consulta o banco diretamente ou faz uma chamada HTTP na própria API? Por quê?
* A tool consulta o banco de dados **diretamente** invocando funções Python internas.
* Fazer chamadas HTTP para a própria API criaria latência desnecessária, redundância e pontos extras de falha na aplicação.

### 7. Por que optamos por não criar um agente "perfil"?
* Porque o perfil é um contexto passivo de dados, não um domínio de decisão ativo.
* O Especialista Financeiro já possui o papel de aconselhar e só precisa consultar as informações do perfil como ferramenta para apoiar suas decisões.

### 8. Qual a vantagem do chat não alterar o cadastro?
* Garante a integridade dos dados e impede alucinações da LLM ao modificar campos financeiros críticos sem validação estrita.
* Mantém o fluxo de escrita restrito ao formulário validado pelo Pydantic, garantindo o cumprimento de regras de negócio como `gasto_fixo_mensal < renda_mensal`.