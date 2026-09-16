"""
app.py
------
Backend Flask do módulo de "Análise Preliminar de Caso" do Sophia (a
segunda parte do produto, que assume que a transcrição em tempo real já
existe como protótipo separado). Este serviço:

  1. Recebe a transcrição (.docx) e documentos anexados do caso.
  2. Sanitiza/rotula os documentos anexados como conteúdo não confiável.
  3. Chama a IA generalista escolhida pelo advogado (BYOK) para produzir
     teses, temas do STF/STJ, jurisprudência, perguntas e necessidades
     adicionais — todos com fonte.
  4. Serve o fluxograma resultante e o chat de refinamento (Seção 6.4).
  5. Gera rascunhos de peças processuais a partir do contexto consolidado
     (Seção 6.5).

Rodar localmente:
    pip install -r requirements.txt
    export SOPHIA_SECRET_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    python app.py
"""

from __future__ import annotations

import uuid

from flask import Flask, jsonify, render_template, request

import storage
from analysis import LLMError, run_case_analysis, run_chat_turn, run_document_draft
from document_utils import build_untrusted_context_block, extract_text, extract_text_from_docx
from llm_providers import get_provider

app = Flask(__name__)
storage.init_db()

MAX_UPLOAD_MB = 25
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


# ---------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html", cases=storage.list_cases())


# ---------------------------------------------------------------------
# Casos
# ---------------------------------------------------------------------

@app.get("/api/casos")
def api_list_casos():
    return jsonify(storage.list_cases())


@app.get("/api/casos/<case_id>")
def api_get_caso(case_id: str):
    case = storage.get_case(case_id)
    if not case:
        return jsonify({"erro": "Caso não encontrado."}), 404
    return jsonify(case)


@app.delete("/api/casos/<case_id>")
def api_delete_caso(case_id: str):
    storage.delete_case(case_id)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------
# Análise preliminar (core flow, Seção 5 e 6.3)
# ---------------------------------------------------------------------

@app.post("/api/analisar")
def api_analisar():
    """
    multipart/form-data esperado:
      - nome_caso: str
      - provider: 'openai' | 'anthropic' | 'google'
      - api_key: str (chave do próprio usuário, BYOK)
      - model: str opcional
      - usar_busca_web: 'true' | 'false'
      - transcricao_docx: arquivo .docx (a transcrição da entrevista)
      - documentos: 0+ arquivos (.docx/.pdf/.txt) anexados pelo advogado
      - case_id: opcional, para reanalisar um caso existente (Seção 15, item 1)
    """
    form = request.form
    provider_name = form.get("provider", "").strip()
    api_key = form.get("api_key", "").strip()
    model = form.get("model", "").strip() or None
    usar_busca_web = form.get("usar_busca_web", "true").lower() == "true"
    nome_caso = form.get("nome_caso", "").strip() or "Caso sem nome"
    case_id = form.get("case_id", "").strip() or str(uuid.uuid4())

    if "transcricao_docx" not in request.files:
        return jsonify({"erro": "Arquivo 'transcricao_docx' é obrigatório."}), 400

    try:
        transcricao_file = request.files["transcricao_docx"]
        transcricao_bytes = transcricao_file.read()
        transcricao_texto = extract_text_from_docx(transcricao_bytes)

        documentos_extraidos = []
        for f in request.files.getlist("documentos"):
            if not f.filename:
                continue
            doc = extract_text(f.filename, f.read())
            documentos_extraidos.append(doc)

        documentos_bloco = build_untrusted_context_block(documentos_extraidos)

        provider = get_provider(provider_name, api_key, model=model)
        analise = run_case_analysis(
            provider,
            transcricao=transcricao_texto,
            documentos_bloco=documentos_bloco,
            use_web_search=usar_busca_web,
        )
    except LLMError as e:
        return jsonify({"erro": str(e)}), 502
    except ValueError as e:
        return jsonify({"erro": str(e)}), 400

    # Persiste o caso (transcrição, docs, análise) — Seção 11, "estrutura de
    # dados por caso" — e sinaliza documentos suspeitos ao advogado.
    existing = storage.get_case(case_id)
    if not existing:
        storage.create_case(case_id, nome_caso)

    docs_meta = [
        {
            "filename": d.filename,
            "sha256": d.sha256,
            "suspicious": d.suspicious,
            "suspicious_matches": d.suspicious_matches,
        }
        for d in documentos_extraidos
    ]
    storage.update_case_analysis(case_id, transcricao_texto, docs_meta, analise)

    return jsonify(
        {
            "case_id": case_id,
            "analise": analise,
            "documentos_meta": docs_meta,
            "alerta_seguranca": any(d.suspicious for d in documentos_extraidos),
        }
    )


# ---------------------------------------------------------------------
# Chat de refinamento (Seção 6.4)
# ---------------------------------------------------------------------

@app.post("/api/chat/<case_id>")
def api_chat(case_id: str):
    body = request.get_json(force=True) or {}
    mensagem = (body.get("mensagem") or "").strip()
    provider_name = body.get("provider", "").strip()
    api_key = body.get("api_key", "").strip()
    model = body.get("model") or None
    usar_busca_web = bool(body.get("usar_busca_web", True))

    if not mensagem:
        return jsonify({"erro": "Mensagem vazia."}), 400

    case = storage.get_case(case_id)
    if not case or not case["analise_json"]:
        return jsonify({"erro": "Caso não encontrado ou ainda sem análise."}), 404

    try:
        provider = get_provider(provider_name, api_key, model=model)
        resposta = run_chat_turn(
            provider,
            case_context_json=case["analise_json"],
            conversation_history=case["chat_history"],
            new_message=mensagem,
            use_web_search=usar_busca_web,
        )
    except LLMError as e:
        return jsonify({"erro": str(e)}), 502

    storage.append_chat_turn(case_id, "user", mensagem)
    history = storage.append_chat_turn(case_id, "assistant", resposta)

    return jsonify({"resposta": resposta, "historico": history})


# ---------------------------------------------------------------------
# Geração de peças processuais (Seção 6.5)
# ---------------------------------------------------------------------

@app.post("/api/gerar-peca/<case_id>")
def api_gerar_peca(case_id: str):
    body = request.get_json(force=True) or {}
    tipo_peca = (body.get("tipo_peca") or "").strip()
    instrucoes_extra = body.get("instrucoes_extra")
    provider_name = body.get("provider", "").strip()
    api_key = body.get("api_key", "").strip()
    model = body.get("model") or None

    if not tipo_peca:
        return jsonify({"erro": "Informe o tipo de peça (ex: 'petição inicial')."}), 400

    case = storage.get_case(case_id)
    if not case or not case["analise_json"]:
        return jsonify({"erro": "Caso não encontrado ou ainda sem análise."}), 404

    try:
        provider = get_provider(provider_name, api_key, model=model)
        rascunho = run_document_draft(
            provider,
            case_context_json=case["analise_json"],
            tipo_peca=tipo_peca,
            instrucoes_extra=instrucoes_extra,
        )
    except LLMError as e:
        return jsonify({"erro": str(e)}), 502

    return jsonify({"rascunho": rascunho, "aviso": "Minuta gerada por IA — revise antes de protocolar."})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
