// app.js — frontend do módulo de Análise Preliminar de Caso do Sophia.
// Sem dependências externas; fetch puro contra o backend Flask.

const state = {
  caseId: null,
  caseNome: null,
  analise: null,
  iaConfig: loadIaConfig(),
};

function loadIaConfig() {
  try {
    return JSON.parse(sessionStorage.getItem("sophia_ia_config") || "null");
  } catch {
    return null;
  }
}
function saveIaConfig(cfg) {
  state.iaConfig = cfg;
  sessionStorage.setItem("sophia_ia_config", JSON.stringify(cfg));
}

// ---------------------------------------------------------------------
// Elementos
// ---------------------------------------------------------------------
const el = {
  listaCasos: document.getElementById("listaCasos"),
  tituloCasoAtual: document.getElementById("tituloCasoAtual"),
  subtituloCasoAtual: document.getElementById("subtituloCasoAtual"),
  flowPlaceholder: document.getElementById("flowPlaceholder"),
  flowCanvas: document.getElementById("flowCanvas"),
  chatLog: document.getElementById("chatLog"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatSend: document.getElementById("chatSend"),
  chatSuggestions: document.getElementById("chatSuggestions"),
  btnGerarPeca: document.getElementById("btnGerarPeca"),

  modalNovoCaso: document.getElementById("modalNovoCaso"),
  formNovoCaso: document.getElementById("formNovoCaso"),
  modalStatus: document.getElementById("modalStatus"),

  modalConfigIA: document.getElementById("modalConfigIA"),
  formConfigIA: document.getElementById("formConfigIA"),

  modalPeca: document.getElementById("modalPeca"),
  formPeca: document.getElementById("formPeca"),
  pecaStatus: document.getElementById("pecaStatus"),
  pecaOutput: document.getElementById("pecaOutput"),
};

// ---------------------------------------------------------------------
// Casos (sidebar)
// ---------------------------------------------------------------------
async function carregarCasos() {
  const res = await fetch("/api/casos");
  const casos = await res.json();
  el.listaCasos.innerHTML = "";
  if (!casos.length) {
    el.listaCasos.innerHTML = '<p class="case-list-empty">Nenhum caso ainda. Comece criando um novo caso ao lado.</p>';
    return;
  }
  for (const c of casos) {
    const item = document.createElement("div");
    item.className = "case-item" + (c.id === state.caseId ? " active" : "");
    item.innerHTML = `<span class="case-name">${escapeHtml(c.nome)}</span><span class="case-date">${formatarData(c.updated_at)}</span>`;
    item.addEventListener("click", () => abrirCaso(c.id));
    el.listaCasos.appendChild(item);
  }
}

async function abrirCaso(caseId) {
  const res = await fetch(`/api/casos/${caseId}`);
  if (!res.ok) return;
  const caso = await res.json();
  state.caseId = caso.id;
  state.caseNome = caso.nome;
  state.analise = caso.analise_json;

  el.tituloCasoAtual.textContent = caso.nome;
  el.subtituloCasoAtual.textContent = "Análise Preliminar de Caso";
  el.btnGerarPeca.disabled = !state.analise;
  el.chatInput.disabled = !state.analise;
  el.chatSend.disabled = !state.analise;

  renderAnalise(state.analise);
  renderChatHistory(caso.chat_history || []);
  carregarCasos();
}

function formatarData(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
}
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---------------------------------------------------------------------
// Novo caso / análise
// ---------------------------------------------------------------------
document.getElementById("btnNovoCaso").addEventListener("click", () => {
  if (!requireIaConfig()) return;
  el.modalStatus.textContent = "";
  el.modalNovoCaso.showModal();
});
document.getElementById("btnCancelarNovoCaso").addEventListener("click", () => el.modalNovoCaso.close());

el.formNovoCaso.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const cfg = state.iaConfig;
  if (!cfg) { el.modalStatus.textContent = "Configure o motor de IA primeiro."; return; }

  const fd = new FormData(el.formNovoCaso);
  fd.set("usar_busca_web", el.formNovoCaso.usar_busca_web.checked ? "true" : "false");
  fd.set("provider", cfg.provider);
  fd.set("api_key", cfg.api_key);
  if (cfg.model) fd.set("model", cfg.model);
  if (state.caseId) fd.set("case_id", state.caseId);

  const btn = document.getElementById("btnEnviarAnalise");
  btn.disabled = true;
  el.modalStatus.className = "modal-status";
  el.modalStatus.textContent = "Analisando o caso — isso pode levar até um minuto…";

  try {
    const res = await fetch("/api/analisar", { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Falha na análise.");

    state.caseId = data.case_id;
    state.analise = data.analise;
    el.btnGerarPeca.disabled = false;
    el.chatInput.disabled = false;
    el.chatSend.disabled = false;

    el.tituloCasoAtual.textContent = fd.get("nome_caso");
    renderAnalise(state.analise);
    el.chatLog.innerHTML = "";

    if (data.alerta_seguranca) {
      alert(
        "Atenção: um dos documentos anexados contém trechos que se parecem com instruções direcionadas a uma IA (possível conteúdo malicioso). " +
        "O sistema tratou esse conteúdo apenas como dado do caso, mas revise o documento original com cuidado."
      );
    }

    el.modalNovoCaso.close();
    carregarCasos();
  } catch (e) {
    el.modalStatus.className = "modal-status erro";
    el.modalStatus.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------------
// Render do fluxograma (Seção 6.3 / mockup Seção 9)
// ---------------------------------------------------------------------
function renderAnalise(analise) {
  el.flowPlaceholder.hidden = true;
  el.flowCanvas.hidden = false;
  el.flowCanvas.innerHTML = "";

  if (!analise) { el.flowCanvas.hidden = true; el.flowPlaceholder.hidden = false; return; }

  const resumo = document.createElement("div");
  resumo.className = "resumo-caso";
  resumo.innerHTML = `<span class="label">Transcrição do Áudio do Cliente e Documentos Juntados</span>${escapeHtml(analise.resumo_caso || "")}`;
  el.flowCanvas.appendChild(resumo);

  const grid = document.createElement("div");
  grid.className = "flow-grid";
  grid.appendChild(categoriaColuna("Teses jurídicas aplicáveis", analise.teses, renderTese));
  grid.appendChild(categoriaColuna("Temas do STF/STJ", analise.temas_stf_stj, renderTema));
  grid.appendChild(categoriaColuna("Jurisprudência", analise.jurisprudencia, renderJurisprudencia));
  grid.appendChild(categoriaColuna("Perguntas sugeridas", analise.perguntas_sugeridas, renderPergunta));
  grid.appendChild(categoriaColuna("Necessidades adicionais", analise.necessidades_adicionais, renderNecessidade));
  el.flowCanvas.appendChild(grid);
}

function categoriaColuna(titulo, itens, renderFn) {
  const col = document.createElement("div");
  col.className = "flow-category";
  const h = document.createElement("div");
  h.className = "flow-category-title";
  h.textContent = `${titulo} (${(itens || []).length})`;
  col.appendChild(h);
  (itens || []).forEach((item) => col.appendChild(renderFn(item)));
  if (!itens || !itens.length) {
    const empty = document.createElement("div");
    empty.className = "node-card";
    empty.innerHTML = `<span class="node-desc">Nada identificado nesta categoria.</span>`;
    col.appendChild(empty);
  }
  return col;
}

function nodeMeta(relevanciaOuStatus, fonte) {
  return `<div class="node-meta"><span class="relevancia">${relevanciaOuStatus || ""}</span><span class="fonte">${escapeHtml(fonte || "não verificado")}</span></div>`;
}

function renderTese(t) {
  const d = document.createElement("div");
  d.className = "node-card tese";
  d.innerHTML = `<div class="node-title">${escapeHtml(t.titulo)}</div><div class="node-desc">${escapeHtml(t.descricao)}</div>${nodeMeta("Relevância: " + (t.relevancia || "—"), t.fonte)}`;
  return d;
}
function renderTema(t) {
  const d = document.createElement("div");
  d.className = "node-card tema";
  d.innerHTML = `<div class="node-title">${escapeHtml(t.titulo)}</div><div class="node-desc">${escapeHtml(t.descricao)}</div>${nodeMeta("Relevância: " + (t.relevancia || "—"), t.fonte)}`;
  return d;
}
function renderJurisprudencia(j) {
  const minoritaria = j.status === "minoritaria_em_analise";
  const d = document.createElement("div");
  d.className = "node-card " + (minoritaria ? "juris-min" : "juris-maj");
  const tag = minoritaria
    ? '<span class="status-tag minoritaria">Minoritária — Em Análise</span>'
    : '<span class="status-tag majoritaria">Majoritária</span>';
  d.innerHTML = `<div class="node-title">${escapeHtml(j.titulo)}${tag}</div>` +
    `<div class="node-desc">${escapeHtml(j.resumo || "")}</div>` +
    `<div class="node-desc" style="font-size:0.78rem">${escapeHtml(j.tribunal || "")}${j.processo ? " · " + escapeHtml(j.processo) : ""}${j.data ? " · " + escapeHtml(j.data) : ""}</div>` +
    nodeMeta("", j.fonte);
  return d;
}
function renderPergunta(p) {
  const d = document.createElement("div");
  d.className = "node-card pergunta";
  d.innerHTML = `<div class="node-title">${escapeHtml(p.pergunta)}</div><div class="node-desc">${escapeHtml(p.objetivo || "")}</div>`;
  return d;
}
function renderNecessidade(n) {
  const d = document.createElement("div");
  d.className = "node-card necessidade";
  d.innerHTML = `<div class="node-title">${escapeHtml(n.tipo)}</div><div class="node-desc">${escapeHtml(n.descricao)}</div>` +
    (n.probabilidade ? nodeMeta("Probabilidade: " + n.probabilidade, "") : "");
  return d;
}

// ---------------------------------------------------------------------
// Chat de refinamento
// ---------------------------------------------------------------------
function renderChatHistory(historico) {
  el.chatLog.innerHTML = "";
  for (const turn of historico) addChatBubble(turn.role, turn.content);
}
function addChatBubble(role, content) {
  const b = document.createElement("div");
  b.className = "chat-turn " + (role === "user" ? "user" : "assistant");
  b.textContent = content;
  el.chatLog.appendChild(b);
  el.chatLog.scrollTop = el.chatLog.scrollHeight;
}

async function enviarMensagem(msg) {
  if (!state.caseId || !msg.trim()) return;
  if (!requireIaConfig()) return;
  addChatBubble("user", msg);
  el.chatInput.value = "";
  el.chatSend.disabled = true;

  try {
    const res = await fetch(`/api/chat/${state.caseId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensagem: msg, ...state.iaConfig }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Falha no chat.");
    addChatBubble("assistant", data.resposta);
  } catch (e) {
    addChatBubble("assistant", "Não consegui responder: " + e.message);
  } finally {
    el.chatSend.disabled = false;
  }
}

el.chatForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  enviarMensagem(el.chatInput.value);
});
el.chatSuggestions.addEventListener("click", (ev) => {
  const btn = ev.target.closest(".chip");
  if (btn) enviarMensagem(btn.dataset.msg);
});

// ---------------------------------------------------------------------
// Configuração de IA (BYOK)
// ---------------------------------------------------------------------
function requireIaConfig() {
  if (state.iaConfig) return true;
  el.modalConfigIA.showModal();
  return false;
}
document.getElementById("btnConfigIA").addEventListener("click", () => {
  if (state.iaConfig) {
    el.formConfigIA.provider.value = state.iaConfig.provider;
    el.formConfigIA.api_key.value = state.iaConfig.api_key;
    el.formConfigIA.model.value = state.iaConfig.model || "";
  }
  el.modalConfigIA.showModal();
});
document.getElementById("btnCancelarConfigIA").addEventListener("click", () => el.modalConfigIA.close());
el.formConfigIA.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const fd = new FormData(el.formConfigIA);
  saveIaConfig({
    provider: fd.get("provider"),
    api_key: fd.get("api_key"),
    model: fd.get("model") || null,
    usar_busca_web: true,
  });
  el.modalConfigIA.close();
});

// ---------------------------------------------------------------------
// Geração de peça processual
// ---------------------------------------------------------------------
el.btnGerarPeca.addEventListener("click", () => {
  if (!requireIaConfig()) return;
  el.pecaStatus.textContent = "";
  el.pecaOutput.hidden = true;
  el.pecaOutput.textContent = "";
  el.modalPeca.showModal();
});
document.getElementById("btnCancelarPeca").addEventListener("click", () => el.modalPeca.close());

el.formPeca.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(el.formPeca);
  el.pecaStatus.className = "modal-status";
  el.pecaStatus.textContent = "Gerando minuta…";
  el.pecaOutput.hidden = true;

  try {
    const res = await fetch(`/api/gerar-peca/${state.caseId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tipo_peca: fd.get("tipo_peca"),
        instrucoes_extra: fd.get("instrucoes_extra"),
        ...state.iaConfig,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.erro || "Falha ao gerar a peça.");
    el.pecaStatus.textContent = data.aviso;
    el.pecaOutput.hidden = false;
    el.pecaOutput.textContent = data.rascunho;
  } catch (e) {
    el.pecaStatus.className = "modal-status erro";
    el.pecaStatus.textContent = e.message;
  }
});

// ---------------------------------------------------------------------
carregarCasos();
