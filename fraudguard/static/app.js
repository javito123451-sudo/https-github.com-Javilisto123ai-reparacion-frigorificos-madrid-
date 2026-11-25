const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
let photos = [];

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (!r.ok) {
    let msg = `Error ${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : (j.detail?.[0]?.msg || msg); } catch {}
    throw new Error(msg);
  }
  return r.json();
}
const num = (id) => { const v = $(id).value; return v === "" ? null : Number(v); };
const ctxClean = (c) => Object.fromEntries(Object.entries(c).filter(([, v]) => v !== null && v !== ""));

function busy(on) { $("#busy").hidden = !on; document.querySelectorAll(".go").forEach((b) => (b.disabled = on)); }
function error(msg) { const e = $("#err"); e.hidden = !msg; e.textContent = msg || ""; }

function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  document.querySelectorAll(".panel").forEach((p) => (p.hidden = p.id !== "tab-" + name));
  $("#result").hidden = true; error("");
  if (name === "history") loadHistory();
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

function gauge(score, band) {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg"); svg.setAttribute("viewBox", "0 0 200 112"); svg.setAttribute("aria-hidden", "true");
  const arc = (cls, frac) => {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", "M20 100 A80 80 0 0 1 180 100"); p.setAttribute("fill", "none"); p.setAttribute("stroke-width", "16"); p.setAttribute("stroke-linecap", "round");
    p.setAttribute("pathLength", "100"); p.setAttribute("stroke-dasharray", `${frac} 100`); p.setAttribute("class", cls); return p;
  };
  const track = arc("", 100); track.setAttribute("stroke", "currentColor"); track.setAttribute("opacity", ".15"); svg.append(track);
  if (score != null) { const v = arc("band-" + band, Math.max(score, 2)); v.setAttribute("stroke", "currentColor"); svg.append(v); }
  return svg;
}

function render(r) {
  const a = r.assessment, root = $("#result"); root.replaceChildren(); root.hidden = false;
  const g = el("div", "gauge band-" + a.band);
  g.append(gauge(a.score, a.band));
  g.append(el("div", "n", a.score == null ? "?" : String(a.score)), el("div", "b", a.band_label));
  root.append(g);
  const conf = el("div", "conf", `Confianza del análisis: ${Math.round(a.confidence * 100)} %`);
  const m = el("div", "meter"); const i = el("i"); i.style.width = Math.round(a.confidence * 100) + "%"; m.append(i);
  root.append(conf, m);
  if (r.summary) root.append(el("p", "ev", r.summary));
  if (a.verdict === "indeterminate") root.append(el("p", "warn", "Resultado indeterminado: no hay información suficiente para valorar el riesgo. Esto no significa que sea seguro."));

  root.append(el("h2", null, a.signals.length ? "Señales detectadas" : "Señales detectadas: ninguna"));
  const ul = el("ul", "sig");
  for (const s of a.signals) {
    const li = el("li"); li.append(el("div", "t", s.title));
    const tag = { rdap: "verificado (RDAP)", user_input: "según tus datos", heuristic: "umbral orientativo", llm: "IA", "rule+llm": "reglas + IA", rule: "reglas" }[s.source] || s.source;
    li.append(el("div", "ev", `${tag}${s.evidence ? " · " + s.evidence : ""}`));
    const bar = el("div", "bar"), bi = el("i"); bi.style.width = Math.min(100, Math.round(s.contribution * 100 / 0.7 )) + "%"; bar.append(bi); li.append(bar);
    ul.append(li);
  }
  root.append(ul);
  if (a.mitigators.length) {
    root.append(el("h2", null, "Factores que reducen el riesgo"));
    const g2 = el("ul", "sig good");
    for (const mm of a.mitigators) { const li = el("li"); li.append(el("div", "t", mm.title), el("div", "ev", mm.evidence)); g2.append(li); }
    root.append(g2);
  }
  const list = (title, items) => { if (!items.length) return; root.append(el("h2", null, title)); const u = el("ul", "plain"); items.forEach((t) => u.append(el("li", null, t))); root.append(u); };
  list("No se pudo verificar", a.unverifiable);
  list("Qué hacer ahora", a.recommendations);
  list("Limitaciones", a.limitations);

  const act = el("div", "actions");
  const rep = el("a", null, "📄 Informe"); rep.href = `/api/analyses/${r.id}/report`; rep.target = "_blank"; rep.rel = "noopener";
  const copy = el("button", null, "Copiar resumen");
  copy.addEventListener("click", () => navigator.clipboard?.writeText(`${a.band_label}${a.score != null ? " (" + a.score + "/100)" : ""} — ${r.summary}\n` + a.signals.map((s) => "• " + s.title).join("\n")));
  const del = el("button", null, "Borrar");
  del.addEventListener("click", async () => { await api(`/api/analyses/${r.id}`, { method: "DELETE" }); root.hidden = true; });
  act.append(rep, copy, del); root.append(act);
  root.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function run(fn) {
  error(""); busy(true); $("#result").hidden = true;
  try { render(await fn()); } catch (e) { error(e.message); } finally { busy(false); }
}
const post = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

$("#go-text").addEventListener("click", () => {
  const text = $("#t-text").value.trim();
  if (!text) return error("Pega primero un texto.");
  run(() => post("/api/analyze/text", { text, context: ctxClean({ price_eur: num("#t-price"), reference_price_eur: num("#t-ref"), channel: $("#t-channel").value }) }));
});
$("#go-url").addEventListener("click", () => {
  const url = $("#u-url").value.trim();
  if (!url) return error("Pega primero un enlace.");
  run(() => post("/api/analyze/url", { url, context: {} }));
});

function drawShots() {
  const box = $("#shots"); box.replaceChildren();
  photos.forEach((f, idx) => {
    const d = el("div"); const im = el("img"); im.src = URL.createObjectURL(f); im.alt = "Foto " + (idx + 1);
    const x = el("button", null, "×"); x.setAttribute("aria-label", "Quitar foto"); x.addEventListener("click", () => { photos.splice(idx, 1); drawShots(); });
    d.append(im, x); box.append(d);
  });
}
for (const id of ["#p-cam", "#p-file"]) $(id).addEventListener("change", (e) => {
  photos = photos.concat([...e.target.files]).slice(0, 4); e.target.value = ""; drawShots();
});
$("#go-photo").addEventListener("click", () => {
  if (!photos.length) return error("Añade al menos una foto.");
  const fd = new FormData(); photos.forEach((f) => fd.append("files", f));
  fd.append("text", "");
  fd.append("context", JSON.stringify(ctxClean({ price_eur: num("#p-price"), reference_price_eur: num("#p-ref"), brand_claimed: $("#p-brand").value.trim(), channel: "presencial", situation: $("#p-sit").value.trim() })));
  run(() => api("/api/analyze/image", { method: "POST", body: fd }));
});

async function loadHistory() {
  const box = $("#hist"); box.replaceChildren();
  const items = await api("/api/analyses").catch(() => []);
  if (!items.length) box.append(el("p", "hint", "Todavía no has analizado nada."));
  for (const it of items) {
    const row = el("div", "hrow"); const b = el("b", "band-" + it.band, it.score == null ? "?" : String(it.score));
    const d = el("div"); d.append(el("span", null, it.summary || it.kind), el("small", null, `${it.kind} · ${new Date(it.created_at).toLocaleString("es-ES")}`));
    row.append(b, d); row.addEventListener("click", async () => { const r = await api("/api/analyses/" + it.id); render(r); });
    box.append(row);
  }
}
$("#del-all").addEventListener("click", async () => {
  if (confirm("¿Borrar todo tu historial? No se puede deshacer.")) { await api("/api/analyses", { method: "DELETE" }); loadHistory(); }
});

api("/api/health").then((h) => {
  const c = $("#aistate"); c.textContent = h.ai_connected ? `IA conectada · OpenAI ${h.model}` : "Modo reglas (sin IA conectada)"; c.classList.toggle("on", h.ai_connected);
  $("#ret").textContent = h.retention_days;
}).catch(() => {});
