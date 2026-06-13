/* Fertigungs-Betriebssystem — Single-Page-Oberfläche mit Modul-Views. */

const $ = (s, r = document) => r.querySelector(s);
const main = $("#main");

const STAGE_LABELS = {
  draft: "Entwurf", internal_review: "Interne Prüfung", sent: "Versendet",
  viewed: "Angesehen", negotiation: "Verhandlung", won: "Gewonnen", lost: "Verloren",
};
const PROJECT_STATUS = {
  planned: "Geplant", in_progress: "In Arbeit", waiting: "Wartet",
  completed: "Abgeschlossen", delivered: "Geliefert",
};
const COMPLEXITY = { low: "gering", medium: "mittel", high: "hoch", very_high: "sehr hoch" };

const eur = (v) => new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" })
  .format(v || 0);
const esc = (s) => { const d = document.createElement("div"); d.textContent = String(s ?? ""); return d.innerHTML; };
const fmtDate = (s) => s ? new Date(s).toLocaleDateString("de-DE") : "—";

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}
const jsonOpts = (method, body) => ({
  method, body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
});

/* ---------------- Router ---------------- */

const views = {};
let currentView = "dashboard";

function setView(name, arg) {
  currentView = name;
  document.querySelectorAll("#nav button").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name));
  main.innerHTML = "<p class='muted'>Lädt…</p>";
  views[name](arg).catch((e) => { main.innerHTML = `<div class="card">Fehler: ${esc(e.message)}</div>`; });
}

document.querySelectorAll("#nav button").forEach((b) =>
  b.onclick = () => setView(b.dataset.view));

/* ============================================================
   Startseite (Übersicht + Einrichtungsstatus)
   ============================================================ */
const FEATURES = [
  ["offers", "Angebote", "Kundenanfragen (E-Mail/manuell, inkl. Dateien) per KI analysieren, kalkulieren und als Angebot freigeben."],
  ["pipeline", "Sales-Pipeline", "Angebote durch die Phasen Entwurf → Versendet → Verhandlung → Gewonnen/Verloren steuern."],
  ["followups", "Follow-up", "Die KI erkennt Nachfass-Anlässe und entwirft Mails — Versand nur nach Freigabe."],
  ["crm", "CRM", "Firmen, Kontakte und die komplette Kundenhistorie an einem Ort."],
  ["projects", "Projekte", "Aus gewonnenen Angeboten werden Projekte: Aufgaben, Material, Zeit, Nachkalkulation."],
  ["production", "Produktion", "Maschinen, Kapazität und Einplanung — Auslastung auf einen Blick."],
  ["documents", "Dokumente", "Zeichnungen, PDFs & Co. zentral, durchsuchbar und versioniert."],
  ["copilot", "KI-Copilot", "Fragen zu echten Systemdaten stellen — jede Antwort ist belegbar."],
  ["dashboard", "Dashboard", "Umsatz, Abschlussquote, verspätete Projekte und Marge je Kunde."],
  ["settings", "Einstellungen", "Stammdaten & Pauschalen Ihres Unternehmens pflegen."],
];

views.home = async () => {
  const st = await api("/api/setup-status").catch(() => null);
  const checks = st ? [
    ["Firmendaten hinterlegt", st.company_name_set, "settings"],
    ["KI-Schlüssel aktiv", st.api_key_set, null],
    ["E-Mail-Eingang konfiguriert", st.email_configured, null],
    ["Materialpreise gepflegt (" + st.material_prices + ")", st.material_prices > 0, "settings"],
  ] : [];
  main.innerHTML = `
    <h2 class="view-title">Willkommen im Fertigungs-Betriebssystem</h2>
    <p class="muted" style="margin-top:-.6rem">Von der Kundenanfrage bis zur Nachkalkulation — alles in einem System.</p>
    ${st ? `<div class="card"><h3>Einrichtung</h3>
      <ul style="list-style:none;padding:0">${checks.map(([label, ok, view]) =>
        `<li style="padding:.25rem 0">${ok ? "✅" : "⬜"} ${esc(label)}
          ${!ok && view ? `<button class="sm" data-goto="${view}">einrichten</button>` : ""}</li>`).join("")}</ul>
      <p class="muted">Bestand: ${st.counts.offers} Angebote · ${st.counts.companies} Kunden · ${st.counts.projects} Projekte</p>
      </div>` : ""}
    <h4>Module</h4>
    <div class="grid-cards">${FEATURES.map(([view, title, desc]) =>
      `<div class="card" style="cursor:pointer" data-goto="${view}">
        <h3 style="margin-top:0">${esc(title)}</h3><p class="muted">${esc(desc)}</p></div>`).join("")}</div>`;
  main.querySelectorAll("[data-goto]").forEach((el) =>
    el.onclick = (e) => { e.stopPropagation(); setView(el.dataset.goto); });
};

/* ============================================================
   Einstellungen / Stammdaten
   ============================================================ */
views.settings = async () => {
  const s = await api("/api/settings");
  const prices = await api("/api/material-prices");
  const c = s.company, pr = s.pricing, co = s.commercial, cx = pr.complexity;
  main.innerHTML = `
    <h2 class="view-title">Einstellungen — Stammdaten</h2>
    <div class="ai-note">Diese Werte sind je Unternehmen unterschiedlich. Sie fließen in
    Kalkulation und Angebotsdokument ein. Nach dem Speichern gelten sie für neue Angebote.</div>
    <div class="row">
      <div class="col card">
        <h3>Firmendaten (Briefkopf)</h3>
        <div class="form-grid">
          <label class="field">Firmenname<input id="c-name" value="${esc(c.name)}"></label>
          <label class="field">E-Mail<input id="c-email" value="${esc(c.email)}"></label>
          <label class="field">Telefon<input id="c-phone" value="${esc(c.phone)}"></label>
          <label class="field">USt-IdNr.<input id="c-vat" value="${esc(c.vat_id)}"></label>
          <label class="field">Website<input id="c-web" value="${esc(c.website)}"></label>
          <label class="field" style="grid-column:1/-1">Adresse<input id="c-addr" value="${esc(c.address)}"></label>
          <label class="field" style="grid-column:1/-1">Logo (PNG/JPG)<input id="c-logo" type="file" accept="image/*"></label>
        </div>
      </div>
      <div class="col card">
        <h3>Kalkulation (Pauschalen)</h3>
        <div class="form-grid">
          <label class="field">Stundensatz €/h<input id="p-rate" type="number" step="0.01" value="${pr.hourly_rate}"></label>
          <label class="field">Rüstkosten €/Position<input id="p-setup" type="number" step="0.01" value="${pr.setup_cost}"></label>
          <label class="field">Gemeinkosten %<input id="p-oh" type="number" step="1" value="${(pr.overhead_pct*100).toFixed(0)}"></label>
          <label class="field">Zielmarge %<input id="p-margin" type="number" step="1" value="${(pr.target_margin_pct*100).toFixed(0)}"></label>
        </div>
        <h4>Komplexitätsfaktoren</h4>
        <div class="form-grid">
          <label class="field">gering<input id="cx-low" type="number" step="0.1" value="${cx.low}"></label>
          <label class="field">mittel<input id="cx-medium" type="number" step="0.1" value="${cx.medium}"></label>
          <label class="field">hoch<input id="cx-high" type="number" step="0.1" value="${cx.high}"></label>
          <label class="field">sehr hoch<input id="cx-vhigh" type="number" step="0.1" value="${cx.very_high}"></label>
        </div>
      </div>
    </div>
    <div class="card">
      <h3>Kaufmännische Konditionen</h3>
      <div class="form-grid">
        <label class="field">Währung<input id="co-cur" value="${esc(co.currency)}"></label>
        <label class="field">USt-Satz %<input id="co-vat" type="number" step="1" value="${(co.vat_rate*100).toFixed(0)}"></label>
        <label class="field">Zahlungsbedingungen<input id="co-pay" value="${esc(co.payment_terms)}"></label>
        <label class="field">Angebotsgültigkeit (Tage)<input id="co-valid" type="number" value="${co.validity_days}"></label>
      </div>
      <label class="field" style="margin-top:.5rem">AGB-/Bedingungstext (im Angebot)
        <textarea id="co-terms" rows="3">${esc(co.terms_text)}</textarea></label>
    </div>
    <div class="actions" style="margin-bottom:1rem"><button id="save-settings" class="primary">Stammdaten speichern</button>
      <span id="save-msg" class="muted"></span></div>

    <div class="card">
      <h3>Materialpreisliste (€/kg)</h3>
      <table><thead><tr><th>Material</th><th class="num">€/kg</th><th></th></tr></thead>
        <tbody>${prices.map((m) => `<tr>
          <td><input class="mp-name" data-id="${m.id}" value="${esc(m.name)}"></td>
          <td class="num"><input class="mp-rate" data-id="${m.id}" type="number" step="0.01" value="${m.eur_per_kg}" style="width:90px"></td>
          <td><button class="sm danger mp-del" data-id="${m.id}">×</button></td></tr>`).join("")}</tbody></table>
      <div class="actions" style="margin-top:.5rem">
        <input id="mp-new-name" placeholder="Material" style="flex:1">
        <input id="mp-new-rate" type="number" step="0.01" placeholder="€/kg" style="width:90px">
        <button id="mp-add" class="sm">+ Hinzufügen</button></div>
    </div>`;

  // Logo als Data-URL einlesen
  let logoDataUrl = null;
  $("#c-logo").onchange = (e) => {
    const f = e.target.files[0]; if (!f) return;
    const r = new FileReader(); r.onload = () => { logoDataUrl = r.result; }; r.readAsDataURL(f);
  };

  $("#save-settings").onclick = (e) => busy(e.target, async () => {
    const patch = {
      company: {
        name: $("#c-name").value, email: $("#c-email").value, phone: $("#c-phone").value,
        vat_id: $("#c-vat").value, website: $("#c-web").value, address: $("#c-addr").value,
      },
      pricing: {
        hourly_rate: Number($("#p-rate").value), setup_cost: Number($("#p-setup").value),
        overhead_pct: Number($("#p-oh").value) / 100, target_margin_pct: Number($("#p-margin").value) / 100,
        complexity: { low: Number($("#cx-low").value), medium: Number($("#cx-medium").value),
          high: Number($("#cx-high").value), very_high: Number($("#cx-vhigh").value) },
      },
      commercial: {
        currency: $("#co-cur").value, vat_rate: Number($("#co-vat").value) / 100,
        payment_terms: $("#co-pay").value, validity_days: Number($("#co-valid").value),
        terms_text: $("#co-terms").value,
      },
    };
    if (logoDataUrl) patch.company.logo_data_url = logoDataUrl;
    await api("/api/settings", jsonOpts("PUT", patch));
    $("#save-msg").textContent = "✓ Gespeichert";
  });

  main.querySelectorAll(".mp-name").forEach((inp) => inp.onchange = () =>
    api(`/api/material-prices/${inp.dataset.id}`, jsonOpts("PUT", { name: inp.value })));
  main.querySelectorAll(".mp-rate").forEach((inp) => inp.onchange = () =>
    api(`/api/material-prices/${inp.dataset.id}`, jsonOpts("PUT", { eur_per_kg: Number(inp.value) })));
  main.querySelectorAll(".mp-del").forEach((b) => b.onclick = () => busy(b, async () => {
    await api(`/api/material-prices/${b.dataset.id}`, { method: "DELETE" }); setView("settings"); }));
  $("#mp-add").onclick = (e) => busy(e.target, async () => {
    const name = $("#mp-new-name").value.trim(); if (!name) return;
    await api("/api/material-prices", jsonOpts("POST", { name, eur_per_kg: Number($("#mp-new-rate").value) }));
    setView("settings"); });
};

/* ============================================================
   Dashboard (Analytics — Modul 12)
   ============================================================ */
views.dashboard = async () => {
  const a = await api("/api/analytics");
  const s = a.sales, o = a.operations, p = a.profitability;
  main.innerHTML = `
    <h2 class="view-title">Dashboard</h2>
    <h4>Vertrieb</h4>
    <div class="kpi">
      <div class="card"><span class="big">${eur(s.revenue_won)}</span><span class="lbl">Umsatz (gewonnen)</span></div>
      <div class="card"><span class="big">${eur(s.open_pipeline_value)}</span><span class="lbl">Offene Pipeline</span></div>
      <div class="card"><span class="big">${s.won_count}</span><span class="lbl">Gewonnene Angebote</span></div>
      <div class="card"><span class="big">${s.conversion_rate ?? "—"}${s.conversion_rate != null ? " %" : ""}</span><span class="lbl">Abschlussquote</span></div>
    </div>
    <h4>Betrieb</h4>
    <div class="kpi">
      <div class="card"><span class="big">${o.active_projects}</span><span class="lbl">Aktive Projekte</span></div>
      <div class="card"><span class="big">${o.delayed_projects}</span><span class="lbl">Verspätete Projekte</span></div>
      <div class="card"><span class="big">${o.machine_utilization_pct ?? "—"}${o.machine_utilization_pct != null ? " %" : ""}</span><span class="lbl">Maschinenauslastung</span></div>
    </div>
    <h4>Profitabilität je Kunde</h4>
    <div class="card">
      <table><thead><tr><th>Kunde</th><th class="num">Umsatz</th><th class="num">Marge</th><th class="num">Aufträge</th></tr></thead>
      <tbody>${p.by_customer.map((c) => `<tr><td>${esc(c.customer)}</td>
        <td class="num">${eur(c.revenue)}</td><td class="num">${eur(c.margin)}</td>
        <td class="num">${c.count}</td></tr>`).join("") || "<tr><td colspan='4' class='muted'>Noch keine gewonnenen Aufträge</td></tr>"}</tbody></table>
    </div>
    ${o.delayed_list.length ? `<div class="card"><h4>Verspätete Projekte</h4><ul>${
      o.delayed_list.map((d) => `<li>#${d.id} ${esc(d.name)} — Frist ${fmtDate(d.deadline)}</li>`).join("")}</ul></div>` : ""}`;
};

/* ============================================================
   Angebote (Quotation-Kern, Drei-Panel-Review)
   ============================================================ */
views.offers = async (offerId) => {
  if (offerId) return renderOfferReview(offerId);
  const offers = await api("/api/offers");
  const mailState = await api("/api/email/status").catch(() => ({ configured: false }));
  main.innerHTML = `
    <h2 class="view-title">Angebote
      ${mailState.configured ? '<button id="mail-check" class="sm">📧 E-Mails abrufen</button>' : ""}</h2>
    <div class="card"><table>
      <thead><tr><th>#</th><th>Kunde</th><th>Quelle</th><th>Status</th><th>Pipeline</th>
        <th class="num">Wert</th><th class="num">Risiko</th><th></th></tr></thead>
      <tbody>${offers.map((o) => `<tr class="clickable" data-id="${o.id}">
        <td>${o.id}</td>
        <td>${esc(o.analysis.customer_name || o.email_from || "—")}</td>
        <td>${o.source === "email" ? "📧 E-Mail" : "Manuell"}</td>
        <td><span class="badge ${o.status}">${o.status}</span></td>
        <td><span class="badge ${o.pipeline_stage}">${STAGE_LABELS[o.pipeline_stage]}</span></td>
        <td class="num">${eur(o.final_price ?? o.costing.recommended_price)}</td>
        <td class="num"><span class="sev sev-${o.risks.overall_severity}">${o.risks.overall_severity}</span></td>
        <td><button class="sm danger del-offer" data-id="${o.id}">Löschen</button></td>
      </tr>`).join("") || "<tr><td colspan='8' class='muted'>Noch keine Angebote</td></tr>"}</tbody>
    </table></div>`;
  main.querySelectorAll("tr[data-id]").forEach((tr) =>
    tr.onclick = (e) => { if (!e.target.classList.contains("del-offer")) setView("offers", Number(tr.dataset.id)); });
  main.querySelectorAll(".del-offer").forEach((b) => b.onclick = (e) => {
    e.stopPropagation();
    if (!confirm(`Angebot #${b.dataset.id} wirklich löschen?`)) return;
    busy(b, async () => { await api(`/api/offers/${b.dataset.id}`, { method: "DELETE" }); setView("offers"); });
  });
  const mc = $("#mail-check");
  if (mc) mc.onclick = async () => {
    mc.disabled = true; mc.textContent = "Rufe ab…";
    try {
      const r = await api("/api/email/check", { method: "POST" });
      alert(`${r.checked} E-Mail(s) geprüft, ${r.imported.length} importiert.`);
      setView("offers");
    } catch (e) { alert(e.message); mc.disabled = false; mc.textContent = "📧 E-Mails abrufen"; }
  };
};

async function renderOfferReview(id) {
  const o = await api(`/api/offers/${id}`);
  const a = o.analysis, c = o.costing, r = o.risks;
  const editable = ["draft", "reviewed"].includes(o.status);
  main.innerHTML = `
    <h2 class="view-title">
      <button class="sm" id="back">← Angebote</button>
      Angebot #${o.id} — ${esc(a.customer_name || "—")}
      <span class="badge ${o.status}">${o.status}</span>
      <span class="badge ${o.pipeline_stage}">${STAGE_LABELS[o.pipeline_stage]}</span>
    </h2>
    <div class="actions" style="margin-bottom:.8rem">
      <button id="approve" class="primary" ${editable ? "" : "disabled"}>Freigeben &amp; Dokument</button>
      <button id="doc" ${o.offer_html ? "" : "disabled"}>Dokument</button>
      <label class="field" style="flex-direction:row;align-items:center;gap:.4rem">Pipeline:
        <select id="stage">${Object.entries(STAGE_LABELS).map(([k, v]) =>
          `<option value="${k}" ${k === o.pipeline_stage ? "selected" : ""}>${v}</option>`).join("")}</select></label>
    </div>
    <div class="panels">
      <div class="panel">
        <h3>Original-Anfrage</h3>
        ${o.source === "email" ? `<p class="muted">Von: ${esc(o.email_from || "—")}<br>Betreff: ${esc(o.email_subject || "—")}</p>` : ""}
        <pre>${esc(o.raw_inquiry)}</pre>
        ${o.attachments.length ? `<h4>Anhänge</h4><ul>${o.attachments.map((at, i) =>
          `<li><a href="/api/offers/${o.id}/attachments/${i}" target="_blank">${esc(at.filename)}</a>
           <span class="muted">(${(at.size_bytes/1024).toFixed(0)} KB${at.passed_to_ai ? ", KI-gelesen" : ""})</span></li>`).join("")}</ul>` : ""}
        <h4>Verlauf</h4>
        <div id="timeline">${renderTimeline(o.activities)}</div>
        <div class="actions" style="margin-top:.4rem">
          <input id="note" placeholder="Notiz / Aktivität…" style="flex:1">
          <button id="add-note" class="sm">+</button>
        </div>
      </div>
      <div class="panel">
        <h3>KI-Interpretation <span class="hint muted">Werte anpassen, dann Speichern</span></h3>
        <p class="muted">Kunde: <strong>${esc(a.customer_name || "—")}</strong> · Termin: ${esc(a.deadline || "—")}</p>
        <h4>Positionen</h4><div id="parts"></div>
        <h4>Annahmen</h4><ul>${a.assumptions.map((x) =>
          `<li><strong>${esc(x.field)}:</strong> ${esc(x.assumption)} <span class="muted">(${x.confidence} %)</span></li>`).join("") || "<li class='muted'>Keine</li>"}</ul>
        <h4>Fehlende Infos</h4><ul>${a.missing_information.map((m) => `<li>${esc(m)}</li>`).join("") || "<li class='muted'>—</li>"}</ul>
        <h4>Risiken <span class="badge">Schwere ${r.overall_severity}/5</span></h4>
        <p class="muted">${esc(r.summary)}</p>
        <ul>${r.risks.map((x) => `<li><span class="sev sev-${x.severity}">${x.severity}</span>${esc(x.description)}
          <div class="muted">→ ${esc(x.mitigation)}</div></li>`).join("")}</ul>
        <button id="save" class="primary" ${editable ? "" : "disabled"}>Speichern &amp; neu kalkulieren</button>
      </div>
      <div class="panel">
        <h3>Kalkulation &amp; Preis</h3>
        <table><thead><tr><th>Pos.</th><th class="num">Menge</th><th class="num">Fertigung</th><th class="num">Summe</th></tr></thead>
        <tbody>${c.parts.map((pp) => `<tr><td>${esc(pp.part_name)}</td><td class="num">${pp.quantity}</td>
          <td class="num">${eur(pp.labor_cost)}</td><td class="num">${eur(pp.subtotal)}</td></tr>`).join("")}</tbody></table>
        <dl class="summary" style="margin:.8rem 0">
          <dt>Direkte Kosten</dt><dd>${eur(c.direct_cost)}</dd>
          <dt>Gemeinkosten</dt><dd>${eur(c.overhead_cost)}</dd>
          <dt>Gesamtkosten</dt><dd>${eur(c.total_cost)}</dd>
          <dt>Empf. Preis</dt><dd class="big">${eur(c.recommended_price)}</dd>
          <dt>Marge</dt><dd>${eur(o.final_price ? o.final_price - c.total_cost : c.margin_eur)}</dd>
        </dl>
        <h4>Finaler Preis</h4>
        <div class="actions"><input id="price" type="number" step="0.01" value="${(o.final_price ?? c.recommended_price).toFixed(2)}" style="flex:1">
          <button id="set-price" class="sm" ${editable ? "" : "disabled"}>Übersteuern</button></div>
        <h4>Konfidenz</h4>
        <div class="confidence-bar"><div style="width:${a.overall_confidence}%;background:${
          a.overall_confidence >= 70 ? "#5a9e4b" : a.overall_confidence >= 40 ? "#d09a26" : "#c0392b"}"></div></div>
        <span class="muted">${a.overall_confidence} % KI-Gesamtkonfidenz</span>
      </div>
    </div>`;

  // Positionen editierbar rendern
  const partsDiv = $("#parts");
  a.parts.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "part-card";
    card.innerHTML = `<span class="pname">${esc(p.name)}</span>
      ${p.material_is_assumption ? '<span class="assumed"> (Material angenommen)</span>' : ""}
      <div class="grid">
        <label class="field">Stückzahl<input type="number" min="1" data-i="${i}" data-f="quantity" value="${p.quantity}"></label>
        <label class="field">Material<input type="text" data-i="${i}" data-f="material" value="${esc(p.material)}"></label>
        <label class="field">Std/Stück<input type="number" step="0.1" data-i="${i}" data-f="estimated_machining_hours_per_part" value="${p.estimated_machining_hours_per_part}"></label>
        <label class="field">kg/Stück<input type="number" step="0.1" data-i="${i}" data-f="estimated_mass_kg_per_part" value="${p.estimated_mass_kg_per_part}"></label>
        <label class="field">Komplexität<select data-i="${i}" data-f="complexity">${
          Object.entries(COMPLEXITY).map(([k, v]) => `<option value="${k}" ${k === p.complexity ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      </div>`;
    partsDiv.appendChild(card);
  });

  $("#back").onclick = () => setView("offers");
  $("#doc").onclick = () => window.open(`/api/offers/${id}/document`, "_blank");
  $("#approve").onclick = (e) => busy(e.target, async () => {
    await api(`/api/offers/${id}/approve`, { method: "POST" }); setView("offers", id); });
  $("#stage").onchange = (e) => {
    const stage = e.target.value;  // vor busy() lesen — busy darf Selects nicht anfassen
    busy(e.target, async () => {
      await api(`/api/offers/${id}/pipeline`, jsonOpts("POST", { stage }));
      setView("offers", id); });
  };
  $("#save").onclick = (e) => busy(e.target, async () => {
    const ana = structuredClone(a);
    document.querySelectorAll("#parts [data-f]").forEach((el) => {
      const part = ana.parts[+el.dataset.i];
      part[el.dataset.f] = el.type === "number" ? Number(el.value) : el.value;
    });
    await api(`/api/offers/${id}/analysis`, jsonOpts("PUT", ana)); setView("offers", id); });
  $("#set-price").onclick = (e) => busy(e.target, async () => {
    await api(`/api/offers/${id}/price`, jsonOpts("POST", { final_price: Number($("#price").value) }));
    setView("offers", id); });
  $("#add-note").onclick = (e) => busy(e.target, async () => {
    const body = $("#note").value.trim(); if (!body) return;
    await api(`/api/offers/${id}/activity`, jsonOpts("POST", { body, kind: "note" }));
    setView("offers", id); });
}

function renderTimeline(activities) {
  if (!activities || !activities.length) return "<p class='muted'>Keine Einträge</p>";
  return "<ul>" + activities.map((x) =>
    `<li><span class="muted">${fmtDate(x.created_at)} · ${esc(x.kind)}</span><br>${esc(x.body)}</li>`).join("") + "</ul>";
}

/* ============================================================
   Sales-Pipeline (Modul 2)
   ============================================================ */
views.pipeline = async () => {
  const board = await api("/api/pipeline");
  main.innerHTML = `<h2 class="view-title">Sales-Pipeline</h2>
    <div class="board">${Object.keys(STAGE_LABELS).map((stage) => {
      const deals = board[stage] || [];
      const sum = deals.reduce((t, d) => t + (d.value || 0), 0);
      return `<div class="col-stage"><h4>${STAGE_LABELS[stage]} (${deals.length}) · ${eur(sum)}</h4>
        ${deals.map((d) => `<div class="deal" data-id="${d.id}">
          <div>${esc(d.customer || "—")}</div>
          <div class="v">${eur(d.value)}</div>
          ${d.risk ? `<span class="sev sev-${d.risk}">R${d.risk}</span>` : ""}
        </div>`).join("")}</div>`;
    }).join("")}</div>`;
  main.querySelectorAll(".deal").forEach((el) =>
    el.onclick = () => setView("offers", Number(el.dataset.id)));
};

/* ============================================================
   Follow-up-Assistent (Modul 3)
   ============================================================ */
views.followups = async () => {
  const list = await api("/api/followups");
  main.innerHTML = `<h2 class="view-title">Follow-up-Assistent</h2>
    <div class="ai-note">Die KI überwacht offene Angebote und schlägt Nachfass-Aktionen vor.
    Entwürfe werden nie automatisch versendet — jeder Entwurf braucht Ihre Freigabe.</div>
    <div id="fu">${list.length ? list.map((s) => `<div class="card" data-id="${s.offer_id}">
      <div class="row"><div class="col">
        <strong>Angebot #${s.offer_id} — ${esc(s.customer || "—")}</strong>
        <span class="badge ${s.stage}">${STAGE_LABELS[s.stage]}</span> · ${eur(s.value)}
        <ul>${s.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      </div><div><button class="primary draft" data-id="${s.offer_id}">KI-Entwurf erstellen</button></div></div>
      <div class="draft-box hidden"></div>
    </div>`).join("") : "<div class='card muted'>Aktuell keine Nachfass-Anlässe.</div>"}</div>`;

  main.querySelectorAll(".draft").forEach((btn) => btn.onclick = (e) => busy(e.target, async () => {
    const id = btn.dataset.id;
    const res = await api(`/api/offers/${id}/followup/draft`, { method: "POST" });
    const box = btn.closest(".card").querySelector(".draft-box");
    box.classList.remove("hidden");
    box.innerHTML = `<h4>KI-Entwurf (Freigabe erforderlich)</h4>
      <textarea rows="8">${esc(res.draft)}</textarea>
      <div class="actions"><button class="primary approve" data-aid="${res.activity_id}">Freigeben</button></div>`;
    box.querySelector(".approve").onclick = (ev) => busy(ev.target, async () => {
      await api(`/api/followups/${res.activity_id}/approve`, { method: "POST" });
      ev.target.textContent = "✓ Freigegeben"; ev.target.disabled = true;
    });
  }));
};

/* ============================================================
   CRM (Modul 1)
   ============================================================ */
views.crm = async (companyId) => {
  if (companyId) return renderCompany(companyId);
  const companies = await api("/api/companies");
  main.innerHTML = `<h2 class="view-title">CRM — Kunden</h2>
    <div class="actions" style="margin-bottom:.8rem">
      <input id="search" placeholder="Suche Name / E-Mail / Branche…" style="flex:1">
      <button id="add-co" class="primary">+ Firma</button></div>
    <div class="card"><table><thead><tr><th>Firma</th><th>Branche</th><th>E-Mail</th><th>Telefon</th></tr></thead>
      <tbody id="co-rows">${companyRows(companies)}</tbody></table></div>`;
  const refresh = async (q) => { $("#co-rows").innerHTML = companyRows(await api("/api/companies?q=" + encodeURIComponent(q))); bindRows(); };
  const bindRows = () => main.querySelectorAll("tr[data-id]").forEach((tr) =>
    tr.onclick = () => setView("crm", Number(tr.dataset.id)));
  bindRows();
  let t; $("#search").oninput = (e) => { clearTimeout(t); t = setTimeout(() => refresh(e.target.value), 250); };
  $("#add-co").onclick = async () => {
    const name = prompt("Firmenname:"); if (!name) return;
    await api("/api/companies", jsonOpts("POST", { name }));
    setView("crm");
  };
};
const companyRows = (cs) => cs.map((c) => `<tr class="clickable" data-id="${c.id}">
  <td>${esc(c.name)}</td><td>${esc(c.industry || "—")}</td><td>${esc(c.email || "—")}</td>
  <td>${esc(c.phone || "—")}</td></tr>`).join("") || "<tr><td colspan='4' class='muted'>Keine Firmen</td></tr>";

async function renderCompany(id) {
  const c = await api(`/api/companies/${id}`);
  main.innerHTML = `<h2 class="view-title"><button class="sm" id="back">← CRM</button> ${esc(c.name)}</h2>
    <div class="row">
      <div class="col card">
        <h3>Stammdaten</h3>
        <p class="muted">${esc(c.industry || "")}<br>${esc(c.email || "")} · ${esc(c.phone || "")}<br>${esc(c.address || "")}</p>
        <h4>Ansprechpartner</h4>
        <ul>${(c.contacts || []).map((k) => `<li>${esc(k.name)} ${k.role ? "(" + esc(k.role) + ")" : ""} — ${esc(k.email || "")}</li>`).join("") || "<li class='muted'>Keine</li>"}</ul>
        <button id="add-contact" class="sm">+ Kontakt</button>
      </div>
      <div class="col card">
        <h3>Historie</h3>
        <h4>Angebote</h4>
        <table><tbody>${(c.offers || []).map((o) => `<tr class="clickable" data-oid="${o.id}">
          <td>#${o.id}</td><td><span class="badge ${o.stage}">${STAGE_LABELS[o.stage]}</span></td>
          <td class="num">${eur(o.value)}</td><td>${fmtDate(o.created_at)}</td></tr>`).join("") || "<tr><td class='muted'>Keine</td></tr>"}</table>
        <h4>Projekte</h4>
        <table><tbody>${(c.projects || []).map((p) => `<tr class="clickable" data-pid="${p.id}">
          <td>#${p.id} ${esc(p.name)}</td><td><span class="badge ${p.status}">${PROJECT_STATUS[p.status]}</span></td></tr>`).join("") || "<tr><td class='muted'>Keine</td></tr>"}</table>
      </div>
    </div>
    <div class="card"><h3>Notizen &amp; interne Kommentare</h3>
      <div id="timeline">${renderTimeline(c.activities)}</div>
      <div class="actions" style="margin-top:.5rem"><input id="note" placeholder="Interne Notiz…" style="flex:1">
        <button id="add-note" class="sm">+</button></div></div>`;
  $("#back").onclick = () => setView("crm");
  main.querySelectorAll("tr[data-oid]").forEach((tr) => tr.onclick = () => setView("offers", Number(tr.dataset.oid)));
  main.querySelectorAll("tr[data-pid]").forEach((tr) => tr.onclick = () => setView("projects", Number(tr.dataset.pid)));
  $("#add-contact").onclick = async () => {
    const name = prompt("Name des Kontakts:"); if (!name) return;
    const email = prompt("E-Mail (optional):") || null;
    await api(`/api/companies/${id}/contacts`, jsonOpts("POST", { name, email }));
    setView("crm", id);
  };
  $("#add-note").onclick = (e) => busy(e.target, async () => {
    const body = $("#note").value.trim(); if (!body) return;
    await api(`/api/companies/${id}/activity`, jsonOpts("POST", { body, kind: "comment" }));
    setView("crm", id);
  });
}

/* ============================================================
   Projekte (Module 5, 6, 8, 9)
   ============================================================ */
views.projects = async (projectId) => {
  if (projectId) return renderProject(projectId);
  const projects = await api("/api/projects");
  main.innerHTML = `<h2 class="view-title">Projekte</h2>
    <div class="card"><table><thead><tr><th>#</th><th>Projekt</th><th>Status</th>
      <th class="num">Auftragswert</th><th>Frist</th></tr></thead>
      <tbody>${projects.map((p) => `<tr class="clickable" data-id="${p.id}">
        <td>${p.id}</td><td>${esc(p.name)}</td>
        <td><span class="badge ${p.status}">${PROJECT_STATUS[p.status]}</span></td>
        <td class="num">${eur(p.order_value)}</td><td>${fmtDate(p.deadline)}</td></tr>`).join("")
        || "<tr><td colspan='5' class='muted'>Noch keine Projekte. Gewinne ein Angebot, um eines zu erzeugen.</td></tr>"}</tbody></table></div>`;
  main.querySelectorAll("tr[data-id]").forEach((tr) => tr.onclick = () => setView("projects", Number(tr.dataset.id)));
};

async function renderProject(id) {
  const p = await api(`/api/projects/${id}`);
  const pc = p.post_calculation;
  const vClass = (v) => v > 0 ? "var-neg" : v < 0 ? "var-pos" : "";
  main.innerHTML = `<h2 class="view-title"><button class="sm" id="back">← Projekte</button>
      #${p.id} ${esc(p.name)} <span class="badge ${p.status}">${PROJECT_STATUS[p.status]}</span></h2>
    <div class="actions" style="margin-bottom:.8rem">
      <label class="field" style="flex-direction:row;align-items:center;gap:.4rem">Status:
        <select id="status">${Object.entries(PROJECT_STATUS).map(([k, v]) =>
          `<option value="${k}" ${k === p.status ? "selected" : ""}>${v}</option>`).join("")}</select></label>
      <span class="muted">Auftragswert: ${eur(p.order_value)} · Frist: ${fmtDate(p.deadline)}</span>
    </div>
    <div class="row">
      <div class="col card">
        <h3>Aufgaben &amp; Meilensteine</h3>
        <table id="tasks"><tbody>${p.tasks.map((t) => `<tr>
          <td>${t.is_milestone ? "◆ " : ""}${esc(t.title)}</td>
          <td><span class="badge ${t.status}">${t.status}</span></td>
          <td class="num">${t.planned_hours || 0} h</td>
          <td><button class="sm del-task" data-id="${t.id}">×</button></td></tr>`).join("") || "<tr><td class='muted'>Keine</td></tr>"}</tbody></table>
        <div class="actions" style="margin-top:.4rem"><input id="t-title" placeholder="Neue Aufgabe…" style="flex:1">
          <input id="t-hours" type="number" placeholder="h" style="width:60px"><button id="add-task" class="sm">+</button></div>

        <h3 style="margin-top:1.2rem">Zeiterfassung</h3>
        <table><tbody>${p.time_entries.map((t) => `<tr>
          <td>${esc(t.employee)}</td><td>${fmtDate(t.entry_date)}</td>
          <td class="num">${t.hours} h</td><td><button class="sm del-time" data-id="${t.id}">×</button></td></tr>`).join("") || "<tr><td class='muted'>Keine Buchungen</td></tr>"}</table>
        <div class="actions" style="margin-top:.4rem">
          <input id="te-emp" placeholder="Mitarbeiter" style="width:110px">
          <input id="te-hours" type="number" step="0.5" placeholder="Std" style="width:70px">
          <input id="te-date" type="date" value="${new Date().toISOString().slice(0,10)}">
          <button id="add-time" class="sm">+</button></div>
      </div>
      <div class="col card">
        <h3>Materialbedarf</h3>
        <table><tbody>${p.materials.map((m) => `<tr>
          <td>${esc(m.name)} <span class="muted">${esc(m.spec || "")}</span></td>
          <td class="num">${m.quantity} ${esc(m.unit)}</td>
          <td><select class="mat-status" data-id="${m.id}">${
            ["needed","ordered","received"].map((s) => `<option value="${s}" ${s===m.status?"selected":""}>${
              {needed:"benötigt",ordered:"bestellt",received:"erhalten"}[s]}</option>`).join("")}</select></td>
          <td><input class="mat-cost" data-id="${m.id}" type="number" step="0.01" value="${m.unit_cost||0}" style="width:80px" title="€/Einheit"></td>
          </tr>`).join("") || "<tr><td class='muted'>Kein Material</td></tr>"}</table>
        <div class="actions" style="margin-top:.4rem"><input id="m-name" placeholder="Material…" style="flex:1">
          <input id="m-qty" type="number" placeholder="Menge" style="width:70px"><button id="add-mat" class="sm">+</button></div>

        <h3 style="margin-top:1.2rem">Nachkalkulation (Soll vs. Ist)</h3>
        ${pc.has_offer ? `<table>
          <thead><tr><th></th><th class="num">Soll</th><th class="num">Ist</th><th class="num">Abweichung</th></tr></thead>
          <tbody>
            <tr><td>Material</td><td class="num">${eur(pc.material.estimate)}</td><td class="num">${eur(pc.material.actual)}</td><td class="num ${vClass(pc.material.variance)}">${eur(pc.material.variance)}</td></tr>
            <tr><td>Arbeit</td><td class="num">${eur(pc.labor.estimate)}</td><td class="num">${eur(pc.labor.actual)}</td><td class="num ${vClass(pc.labor.variance)}">${eur(pc.labor.variance)}</td></tr>
            <tr><td>Gesamtkosten</td><td class="num">${eur(pc.total_cost.estimate)}</td><td class="num">${eur(pc.total_cost.actual)}</td><td class="num ${vClass(pc.total_cost.variance)}">${eur(pc.total_cost.variance)}</td></tr>
            <tr><td><strong>Marge</strong></td><td class="num">${eur(pc.margin.estimated)}</td><td class="num">${eur(pc.margin.actual)}</td><td class="num ${vClass(-pc.margin.variance)}">${eur(pc.margin.variance)}</td></tr>
            <tr><td>Stunden</td><td class="num">${pc.hours.planned} h</td><td class="num">${pc.hours.actual} h</td><td class="num ${vClass(pc.hours.actual-pc.hours.planned)}">${(pc.hours.actual-pc.hours.planned).toFixed(1)} h</td></tr>
          </tbody></table>
          <p class="muted">Datenbasis: ${pc.data_completeness.time_entries} Zeitbuchungen,
          ${pc.data_completeness.materials_costed}/${pc.data_completeness.materials_total} Materialien mit Kosten.</p>`
          : "<p class='muted'>Kein verknüpftes Angebot — Soll-Werte nicht verfügbar.</p>"}
      </div>
    </div>`;
  $("#back").onclick = () => setView("projects");
  $("#status").onchange = (e) => {
    const status = e.target.value;
    busy(e.target, async () => {
      await api(`/api/projects/${id}`, jsonOpts("PUT", { status })); setView("projects", id); });
  };
  $("#add-task").onclick = (e) => busy(e.target, async () => {
    const title = $("#t-title").value.trim(); if (!title) return;
    await api(`/api/projects/${id}/tasks`, jsonOpts("POST", { title, planned_hours: Number($("#t-hours").value) || 0 }));
    setView("projects", id); });
  main.querySelectorAll(".del-task").forEach((b) => b.onclick = () => busy(b, async () => {
    await api(`/api/tasks/${b.dataset.id}`, { method: "DELETE" }); setView("projects", id); }));
  $("#add-time").onclick = (e) => busy(e.target, async () => {
    const employee = $("#te-emp").value.trim(); const hours = Number($("#te-hours").value);
    if (!employee || !hours) return alert("Mitarbeiter und Stunden nötig");
    await api(`/api/projects/${id}/time`, jsonOpts("POST", { employee, hours, entry_date: $("#te-date").value }));
    setView("projects", id); });
  main.querySelectorAll(".del-time").forEach((b) => b.onclick = () => busy(b, async () => {
    await api(`/api/time/${b.dataset.id}`, { method: "DELETE" }); setView("projects", id); }));
  $("#add-mat").onclick = (e) => busy(e.target, async () => {
    const name = $("#m-name").value.trim(); if (!name) return;
    await api(`/api/projects/${id}/materials`, jsonOpts("POST", { name, quantity: Number($("#m-qty").value) || 1 }));
    setView("projects", id); });
  main.querySelectorAll(".mat-status").forEach((sel) => sel.onchange = () =>
    api(`/api/materials/${sel.dataset.id}`, jsonOpts("PUT", { status: sel.value })).then(() => setView("projects", id)));
  main.querySelectorAll(".mat-cost").forEach((inp) => inp.onchange = () =>
    api(`/api/materials/${inp.dataset.id}`, jsonOpts("PUT", { unit_cost: Number(inp.value) })).then(() => setView("projects", id)));
}

/* ============================================================
   Produktion (Modul 7)
   ============================================================ */
views.production = async () => {
  const b = await api("/api/production");
  main.innerHTML = `<h2 class="view-title">Produktionsplanung</h2>
    <div class="card"><h3>Maschinen &amp; Auslastung</h3>
      <table><thead><tr><th>Maschine</th><th>Arbeitszentrum</th><th class="num">Kapazität/Wo</th>
        <th class="num">Verplant</th><th class="num">Auslastung</th><th></th></tr></thead>
      <tbody>${b.machines.map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.work_center || "—")}</td>
        <td class="num">${m.capacity_hours_per_week} h</td><td class="num">${m.booked_hours} h</td>
        <td class="num">${m.utilization_pct ?? "—"}${m.utilization_pct != null ? " %" : ""}</td>
        <td><button class="sm del-machine" data-id="${m.id}">×</button></td></tr>`).join("")
        || "<tr><td colspan='6' class='muted'>Keine Maschinen</td></tr>"}</tbody></table>
      <div class="actions" style="margin-top:.5rem">
        <input id="m-name" placeholder="Maschinenname"><input id="m-wc" placeholder="Arbeitszentrum">
        <input id="m-cap" type="number" placeholder="h/Woche" style="width:90px"><button id="add-machine" class="sm">+ Maschine</button></div>
    </div>
    <div class="card"><h3>Produktionsplan</h3>
      <table><thead><tr><th>Auftrag</th><th>Maschine</th><th>Von</th><th>Bis</th><th class="num">Std</th><th></th></tr></thead>
      <tbody>${b.slots.map((s) => { const m = b.machines.find((x) => x.id === s.machine_id);
        return `<tr><td>${esc(s.title)}</td><td>${esc(m ? m.name : "?")}</td>
          <td>${fmtDate(s.start_date)}</td><td>${fmtDate(s.end_date)}</td><td class="num">${s.hours} h</td>
          <td><button class="sm del-slot" data-id="${s.id}">×</button></td></tr>`; }).join("")
        || "<tr><td colspan='6' class='muted'>Keine Einplanung</td></tr>"}</tbody></table>
      <div class="actions" style="margin-top:.5rem">
        <input id="s-title" placeholder="Bezeichnung">
        <select id="s-machine">${b.machines.map((m) => `<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select>
        <input id="s-start" type="date"><input id="s-end" type="date">
        <input id="s-hours" type="number" placeholder="Std" style="width:70px"><button id="add-slot" class="sm">+ Einplanen</button></div>
    </div>`;
  $("#add-machine").onclick = (e) => busy(e.target, async () => {
    const name = $("#m-name").value.trim(); if (!name) return;
    await api("/api/machines", jsonOpts("POST", { name, work_center: $("#m-wc").value || null,
      capacity_hours_per_week: Number($("#m-cap").value) || 40 })); setView("production"); });
  main.querySelectorAll(".del-machine").forEach((b2) => b2.onclick = () => busy(b2, async () => {
    await api(`/api/machines/${b2.dataset.id}`, { method: "DELETE" }); setView("production"); }));
  $("#add-slot").onclick = (e) => busy(e.target, async () => {
    const title = $("#s-title").value.trim(); const machine_id = Number($("#s-machine").value);
    if (!title || !machine_id) return alert("Bezeichnung und Maschine nötig");
    await api("/api/production/slots", jsonOpts("POST", { title, machine_id,
      start_date: $("#s-start").value, end_date: $("#s-end").value, hours: Number($("#s-hours").value) || 0 }));
    setView("production"); });
  main.querySelectorAll(".del-slot").forEach((b2) => b2.onclick = () => busy(b2, async () => {
    await api(`/api/production/slots/${b2.dataset.id}`, { method: "DELETE" }); setView("production"); }));
};

/* ============================================================
   Dokumente (Modul 10)
   ============================================================ */
views.documents = async () => {
  const docs = await api("/api/documents");
  main.innerHTML = `<h2 class="view-title">Dokumente</h2>
    <div class="actions" style="margin-bottom:.8rem">
      <input id="search" placeholder="Suche Dateiname…" style="flex:1">
      <input id="up-file" type="file"><input id="up-kind" placeholder="Typ (z.B. Zeichnung)" style="width:140px">
      <button id="upload" class="primary">Hochladen</button></div>
    <div class="card"><table><thead><tr><th>Name</th><th>Typ</th><th class="num">Version</th>
      <th class="num">Größe</th><th>Datum</th><th></th></tr></thead>
      <tbody id="doc-rows">${docRows(docs)}</tbody></table></div>`;
  const refresh = async (q) => { $("#doc-rows").innerHTML = docRows(await api("/api/documents?q=" + encodeURIComponent(q))); };
  let t; $("#search").oninput = (e) => { clearTimeout(t); t = setTimeout(() => refresh(e.target.value), 250); };
  $("#upload").onclick = (e) => busy(e.target, async () => {
    const f = $("#up-file").files[0]; if (!f) return alert("Datei wählen");
    const form = new FormData(); form.append("file", f); form.append("kind", $("#up-kind").value || "Dokument");
    await api("/api/documents", { method: "POST", body: form }); setView("documents"); });
};
const docRows = (ds) => ds.map((d) => `<tr><td><a href="/api/documents/${d.id}/download">${esc(d.name)}</a></td>
  <td>${esc(d.kind || "—")}</td><td class="num">v${d.version}</td>
  <td class="num">${((d.size_bytes||0)/1024).toFixed(0)} KB</td><td>${fmtDate(d.created_at)}</td>
  <td></td></tr>`).join("") || "<tr><td colspan='6' class='muted'>Keine Dokumente</td></tr>";

/* ============================================================
   KI-Copilot (Modul 11)
   ============================================================ */
const copilotHistory = [];
views.copilot = async () => {
  main.innerHTML = `<h2 class="view-title">KI-Copilot</h2>
    <div class="ai-note">Der Copilot beantwortet ausschließlich anhand echter Systemdaten.
    Er ruft dafür Abfrage-Werkzeuge auf — jede Antwort ist über die genutzten Datensätze
    nachvollziehbar (siehe „Datenquellen"). Er erfindet keine Werte.</div>
    <div class="card chat" id="chat">${copilotHistory.map(renderMsg).join("")}</div>
    <div class="actions" style="margin-top:.8rem">
      <input id="q" placeholder="z. B. Welche Projekte sind verspätet?" style="flex:1">
      <button id="ask" class="primary">Fragen</button></div>
    <div class="muted" style="margin-top:.4rem">Beispiele: „Welche Angebote warten auf Freigabe?“ ·
      „Welcher Kunde hat den höchsten Umsatz?“ · „Welches Angebot hat das höchste Risiko?“</div>`;
  const chat = $("#chat");
  const ask = async () => {
    const q = $("#q").value.trim(); if (!q) return;
    copilotHistory.push({ role: "user", text: q });
    chat.innerHTML = copilotHistory.map(renderMsg).join("") + `<div class="msg ai">Denkt nach…</div>`;
    $("#q").value = ""; chat.scrollTop = chat.scrollHeight;
    try {
      const res = await api("/api/copilot", jsonOpts("POST", { question: q }));
      copilotHistory.push({ role: "ai", text: res.answer, sources: res.sources });
    } catch (e) {
      copilotHistory.push({ role: "ai", text: "Fehler: " + e.message });
    }
    chat.innerHTML = copilotHistory.map(renderMsg).join("");
    chat.scrollTop = chat.scrollHeight;
  };
  $("#ask").onclick = ask;
  $("#q").onkeydown = (e) => { if (e.key === "Enter") ask(); };
};
function renderMsg(m) {
  if (m.role === "user") return `<div class="msg user">${esc(m.text)}</div>`;
  const src = m.sources && m.sources.length
    ? `<details class="sources"><summary>Datenquellen (${m.sources.length} Abfragen)</summary>
       <pre>${esc(JSON.stringify(m.sources, null, 2))}</pre></details>` : "";
  return `<div class="msg ai">${esc(m.text)}${src}</div>`;
}

/* ---------------- Helpers & Neue-Anfrage-Dialog ---------------- */

async function busy(btn, fn) {
  // Bei <select>/<input> NIE textContent ändern — das würde Optionen/Wert zerstören.
  const isButton = btn.tagName === "BUTTON";
  const old = isButton ? btn.textContent : null;
  btn.disabled = true;
  if (isButton) btn.textContent = "…";
  try { await fn(); } catch (e) { alert(e.message); btn.disabled = false; if (isButton) btn.textContent = old; }
}

$("#btn-new").onclick = () => $("#dlg-new").showModal();
$("#btn-cancel").onclick = () => $("#dlg-new").close();
$("#btn-analyze").onclick = async (e) => {
  const text = $("#new-text").value.trim();
  const fileInput = $("#new-files");
  if (!text && fileInput.files.length === 0) return alert("Text oder Dateien nötig.");
  e.target.disabled = true;
  $("#new-status").textContent = "KI-Analyse läuft — das kann eine Minute dauern…";
  try {
    const form = new FormData();
    form.append("text", text);
    if ($("#new-email").value) form.append("customer_email", $("#new-email").value);
    for (const f of fileInput.files) form.append("files", f);
    const offer = await api("/api/inquiries", { method: "POST", body: form });
    $("#dlg-new").close(); $("#new-text").value = ""; fileInput.value = ""; $("#new-status").textContent = "";
    setView("offers", offer.id);
  } catch (err) {
    $("#new-status").textContent = "Fehler: " + err.message;
  } finally { e.target.disabled = false; }
};

setView("home");
