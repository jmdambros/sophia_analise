# Sophia — Módulo de Análise Preliminar de Caso

Esta é a **segunda parte** do produto Sophia (a primeira, transcrição em
tempo real, já existe como protótipo separado). Este módulo:

1. Recebe a **transcrição** da entrevista (arquivo `.docx`) e, opcionalmente,
   **documentos do processo** já em posse do advogado (`.docx`, `.pdf`, `.txt`).
2. **Sanitiza** os documentos anexados: eles são isolados em blocos
   claramente rotulados como "dado não confiável" no prompt, e um detector
   heurístico sinaliza (sem apagar silenciosamente) padrões comuns de
   instrução oculta / prompt injection.
3. Envia o contexto para a **IA generalista escolhida pelo próprio advogado**
   (OpenAI, Anthropic ou Google — BYOK, o usuário fornece sua própria chave),
   pedindo uma resposta estruturada em JSON com: teses jurídicas, temas do
   STF/STJ, jurisprudência (com status majoritária/minoritária), perguntas
   sugeridas e necessidades adicionais — **cada item com fonte obrigatória**
   (ou "não verificado", nunca uma referência inventada).
4. Renderiza esse resultado como o **fluxograma** do mockup de referência do
   documento de contexto, com um chat de refinamento embaixo.
5. Permite gerar **rascunhos de peças processuais** a partir do contexto já
   consolidado do caso (sempre como minuta para revisão humana).

## Rodando localmente

```bash
cd sophia_analise
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt      # instale também o SDK do provedor que for usar
export SOPHIA_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python app.py
```

Abra `http://localhost:5000`. Clique em **"Configurar IA"**, escolha o
provedor e cole sua chave de API (fica só na sessão do navegador — não é
enviada ao banco de dados neste protótipo). Depois clique em **"+ Novo
caso"** e envie o `.docx` da transcrição.

## Estrutura

```
app.py              # rotas Flask: /api/analisar, /api/chat/<id>, /api/gerar-peca/<id>, /api/casos
analysis.py          # prompt de sistema, schema JSON, validação da resposta da IA
llm_providers.py      # camada de abstração BYOK: OpenAI / Anthropic / Google
document_utils.py     # extração de texto (.docx/.pdf/.txt) + sanitização/rotulagem
storage.py            # SQLite: um registro por caso (transcrição, docs, análise, chat)
templates/index.html  # layout: sidebar de casos, fluxograma, chat
static/style.css      # identidade visual (ver "Decisões de design" abaixo)
static/app.js         # toda a lógica de frontend (fetch puro, sem framework)
```

## Decisões de design tomadas (e por quê)

- **Nenhum banco de jurisprudência próprio.** Conforme a Seção 2.1 do
  documento de contexto, a IA generalista escolhida pelo usuário já tem uma
  base de conhecimento maior do que qualquer banco proprietário. Este módulo
  não tenta re-implementar isso — ele estrutura o prompt e valida o formato
  da resposta. Quando o provedor suporta (Anthropic, OpenAI, Google), a
  ferramenta de **busca na web nativa** é habilitada por padrão na análise
  inicial, para aumentar a chance de jurisprudência atualizada com fonte real.
- **JSON estruturado obrigatório, nunca texto livre**, para poder garantir
  em código (não só por instrução ao modelo) que todo item tenha um campo de
  fonte — requisito não negociável da Seção 7.
- **Sanitização por rotulagem + heurística de alerta**, não por tentativa de
  "limpar" o texto automaticamente — apagar trechos poderia destruir
  conteúdo legítimo do processo. A defesa real é o prompt de sistema instruir
  a IA a nunca tratar o conteúdo de `<documento_anexado_N>` como comando.
  Isso responde à pergunta em aberto nº 5 da Seção 15: optamos por sinalizar
  (alerta ao advogado), não bloquear silenciosamente.
- **Chave de API não persistida por padrão** (fica em `sessionStorage` do
  navegador, some ao fechar a aba) — reduz a superfície de risco do
  protótipo. `storage.py` já traz `encrypt_api_key`/`decrypt_api_key` com
  Fernet prontos para o dia em que for necessário persistir chaves (ex.:
  "lembrar minha chave"), mas isso é uma decisão de produto em aberto.
- **SQLite** para o protótipo (Seção 11, "estrutura de dados por caso":
  transcrição + documentos + histórico de chat + fluxograma, tudo junto por
  `case_id`). Trocar para Postgres depois é direto, pois todo o acesso a
  dados passa por `storage.py`.

## Limitações conhecidas / próximos passos

- A geração de peça processual (`/api/gerar-peca`) não usa busca web por
  padrão — é uma escolha de custo/latência; pode ser ligada se necessário.
- Não há autenticação/multiusuário ainda — cada instalação serve um único
  advogado/escritório. Antes de multiusuário, seria necessário adicionar
  login e isolar `cases` por conta.
- O SDK do provedor precisa estar instalado para aquele provedor funcionar
  (ver comentários em `requirements.txt`); o app falha com uma mensagem
  clara (`LLMError`) se o pacote não estiver presente, em vez de quebrar.
- Perguntas em aberto da Seção 15 (reanálise incremental, modelo de
  precificação, quais provedores lançar) permanecem decisões de produto,
  não técnicas — o endpoint `/api/analisar` já aceita `case_id` para
  reanalisar um caso existente, então a reanálise incremental já é possível
  tecnicamente.
