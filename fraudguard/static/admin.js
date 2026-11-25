const $ = (s) => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts });
  if (!r.ok) { let m = `Error ${r.status}`; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return r.json();
}
async function load() {
  try {
    const s = await api("/api/admin/stats");
    const box = $("#stats"); box.replaceChildren();
    const row = (k, v) => { const d = el("div", "hrow"); d.append(el("b", null, String(v)), el("span", null, k)); box.append(d); };
    row("IA conectada (" + (s.model || "—") + ")", s.ai_connected ? "sí" : "no");
    row("Análisis totales", s.analyses_total);
    row("Análisis este mes (total / con imágenes)", `${s.usage_month.total} / ${s.usage_month.images}`);
    row("Claves de API activas", s.active_keys);
    s.users.forEach((u) => row("Usuarios plan " + u.plan, u.n));
    s.analyses_by_band.forEach((b) => row("Resultados: " + b.band, b.n));
    const ub = $("#users"); ub.replaceChildren();
    for (const u of await api("/api/admin/users")) {
      const r = el("div", "hrow"); const d = el("div"); d.append(el("span", null, u.email + (u.is_admin ? " (admin)" : "") + (u.disabled ? " · desactivado" : "")), el("small", null, u.created_at.slice(0, 10)));
      const sel = el("select"); ["free", "premium"].forEach((p) => { const o = el("option", null, p); o.value = p; o.selected = p === u.plan; sel.append(o); });
      sel.addEventListener("change", () => api(`/api/admin/users/${u.id}/plan`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan: sel.value }) }).catch((e) => alert(e.message)));
      const tg = el("button", "ghost", u.disabled ? "Activar" : "Desactivar");
      tg.addEventListener("click", async () => { try { await api(`/api/admin/users/${u.id}/disabled?disabled=${!u.disabled}`, { method: "PUT" }); load(); } catch (e) { alert(e.message); } });
      r.append(d, sel, tg); ub.append(r);
    }
  } catch (e) { const er = $("#err"); er.hidden = false; er.textContent = e.message + " — inicia sesión como administrador en la pestaña Cuenta."; }
}
load();
