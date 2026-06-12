/* Review-Oberfläche: Angebotsliste, Drei-Panel-Review, Bearbeitung, Freigabe-Workflow. */

const $ = (sel) => document.querySelector(sel);
let current = null; // aktuell geladenes Angebot

const STATUS_LABELS = {
  draft: "Entwurf", reviewed: "Geprüft", sent: "Versendet",
  accepted: "Angenommen", rejected: "Abgelehnt",
};
const COMPLEXITY_LABELS = { low: "gering", medium: "mittel", high: "hoch", very_high: "sehr hoch" };

const eur = (v) =>
  new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(v);

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}
const jsonOpts = (method, body) => ({
  method, body: JSON.stringify(body), headers: { "Content-Type": "application/json" },
});

/* ---------------- Angebotsliste ---------------- */

async function refreshList() {
  const offers = await api("/api/offers");
  const ul = $("#offers");
  ul.innerHTML = "";
  for (const o of offers) {
    const li = document.createElement("li");
    if (current && current.id === o.id) li.classList.add("active");
    const name = o.analysis.customer_name || o.customer_email || "Unbekannter Kunde";
    const src = o.source === "email" ? "📧 " : "";
    li.innerHTML = `<span class="name">${src}#${o.id} ${esc(name)}</span>
      <span class="sub">${STATUS_LABELS[o.status]} · ${eur(o.final_price ?? o.costing.recommended_price)}</span>`;
    li.onclick = () => loadOffer(o.id);
    ul.appendChild(li);
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

/* ---------------- Workspace ---------------- */

async function loadOffer(id) {
  current = await api(`/api/offers/${id}`);
  renderWorkspace();
  refreshList();
}

function renderWorkspace() {
  if (!current) return;
  const o = current;
  $("#workspace").classList.remove("hidden");
  $("#empty-state").classList.add("hidden");

  $("#ws-title").textContent =
    `Angebot #${o.id} — ${o.analysis.customer_name || o.customer_email || "Unbekannter Kunde"}`;
  const st = $("#ws-status");
  st.textContent = STATUS_LABELS[o.status];
  st.className = `badge ${o.status}`;
  const src = $("#ws-source");
  src.textContent = o.source === "email" ? "aus E-Mail" : "manuell";
  src.classList.remove("hidden");

  $("#email-meta").innerHTML = o.source === "email"
    ? `Von: <strong>${esc(o.email_from || "—")}</strong><br>Betreff: ${esc(o.email_subject || "—")}`
    : "";
  $("#raw-inquiry").textContent = o.raw_inquiry;

  // Anhänge
  const atts = o.attachments || [];
  $("#attachments-block").classList.toggle("hidden", atts.length === 0);
  $("#attachments").innerHTML = atts.map((a, i) =>
    `<li><a href="/api/offers/${o.id}/attachments/${i}" target="_blank">${esc(a.filename)}</a>
     <span class="muted">(${(a.size_bytes / 1024).toFixed(0)} KB${a.passed_to_ai ? ", von KI gelesen" : ", nicht KI-lesbar"})</span></li>`
  ).join("");

  // Kunde / Termin
  const a = o.analysis;
  $("#customer-block").innerHTML = `
    <p class="muted">
      Kunde: <strong>${esc(a.customer_name || "—")}</strong> ·
      Kontakt: ${esc(a.customer_contact || "—")} ·
      Termin: ${esc(a.deadline || "—")}
    </p>`;

  // editierbare Positionen
  const partsDiv = $("#parts");
  partsDiv.innerHTML = "";
  a.parts.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "part-card";
    card.innerHTML = `
      <span class="pname">${esc(p.name)}</span>
      ${p.material_is_assumption ? '<span class="assumed"> (Material angenommen)</span>' : ""}
      <div class="muted">${esc(p.description)}</div>
      <div class="grid">
        <label>Stückzahl
          <input type="number" min="1" data-i="${i}" data-f="quantity" value="${p.quantity}"></label>
        <label>Material
          <input type="text" data-i="${i}" data-f="material" value="${esc(p.material)}"></label>
        <label>Stunden / Stück
          <input type="number" step="0.1" min="0" data-i="${i}"
                 data-f="estimated_machining_hours_per_part"
                 value="${p.estimated_machining_hours_per_part}"></label>
        <label>Masse kg / Stück
          <input type="number" step="0.1" min="0" data-i="${i}"
                 data-f="estimated_mass_kg_per_part"
                 value="${p.estimated_mass_kg_per_part}"></label>
        <label>Komplexität
          <select data-i="${i}" data-f="complexity">
            ${["low", "medium", "high", "very_high"].map(
              (c) => `<option value="${c}" ${c === p.complexity ? "selected" : ""}>${COMPLEXITY_LABELS[c]}</option>`
            ).join("")}
          </select></label>
        <label>Konfidenz
          <input type="text" disabled value="${p.confidence} %"></label>
      </div>`;
    partsDiv.appendChild(card);
  });

  $("#assumptions").innerHTML = a.assumptions.map(
    (x) => `<li><strong>${esc(x.field)}:</strong> ${esc(x.assumption)}
            <span class="muted">(${x.confidence} %)</span></li>`
  ).join("") || "<li class='muted'>Keine</li>";

  $("#missing").innerHTML = a.missing_information.map((m) => `<li>${esc(m)}</li>`).join("")
    || "<li class='muted'>Nichts offen</li>";

  const r = o.risks;
  $("#risk-score").textContent = `Schwere ${r.overall_severity}/5`;
  $("#risk-summary").textContent = r.summary;
  $("#risks").innerHTML = r.risks.map(
    (x) => `<li><span class="sev sev-${x.severity}">${x.severity}</span>
            ${esc(x.description)}
            <div class="muted">→ ${esc(x.mitigation)}</div></li>`
  ).join("") || "<li class='muted'>Keine Risiken erkannt</li>";

  // Kalkulation
  const c = o.costing;
  $("#cost-table tbody").innerHTML = c.parts.map(
    (p) => `<tr><td>${esc(p.part_name)}</td><td>${p.quantity}</td>
            <td>${esc(p.material)}</td><td>${eur(p.labor_cost)}</td>
            <td>${eur(p.subtotal)}</td></tr>`
  ).join("");

  $("#cost-summary").innerHTML = `
    <dt>Direkte Kosten</dt><dd>${eur(c.direct_cost)}</dd>
    <dt>Gemeinkosten (${(c.overhead_percent * 100).toFixed(0)} %)</dt><dd>${eur(c.overhead_cost)}</dd>
    <dt>Gesamtkosten</dt><dd>${eur(c.total_cost)}</dd>
    <dt>Empfohlener Preis</dt><dd class="big">${eur(c.recommended_price)}</dd>
    <dt>Marge</dt><dd>${eur(o.final_price ? o.final_price - c.total_cost : c.margin_eur)}
        (Ziel ${(c.target_margin_percent * 100).toFixed(0)} %)</dd>`;

  $("#final-price").value = (o.final_price ?? c.recommended_price).toFixed(2);

  $("#confidence-fill").style.width = `${a.overall_confidence}%`;
  $("#confidence-fill").style.background =
    a.overall_confidence >= 70 ? "#5a9e4b" : a.overall_confidence >= 40 ? "#d09a26" : "#c0392b";
  $("#confidence-label").textContent = `${a.overall_confidence} % KI-Gesamtkonfidenz`;

  // Buttons je nach Status
  const editable = ["draft", "reviewed"].includes(o.status);
  $("#btn-save").disabled = !editable;
  $("#btn-price").disabled = !editable;
  $("#btn-approve").disabled = !editable;
  $("#btn-document").disabled = !o.offer_html;
  $("#btn-send").disabled = !(o.status === "reviewed" && o.offer_html);
  $("#btn-accept").disabled = o.status !== "sent";
  $("#btn-reject").disabled = ["accepted", "rejected"].includes(o.status);
}

/* ---------------- Aktionen ---------------- */

function collectEditedAnalysis() {
  const a = structuredClone(current.analysis);
  document.querySelectorAll("#parts [data-f]").forEach((el) => {
    const part = a.parts[Number(el.dataset.i)];
    const field = el.dataset.f;
    part[field] = el.type === "number" ? Number(el.value) : el.value;
    if (field === "quantity") part[field] = Math.max(1, Math.round(part[field]));
  });
  return a;
}

async function withBusy(btn, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Bitte warten…";
  try {
    await fn();
  } catch (e) {
    alert(e.message);
  } finally {
    btn.textContent = old;
    renderWorkspace();
    refreshList();
  }
}

$("#btn-save").onclick = (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/analysis`,
    jsonOpts("PUT", collectEditedAnalysis()));
});

$("#btn-price").onclick = (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/price`,
    jsonOpts("POST", { final_price: Number($("#final-price").value) }));
});

$("#btn-approve").onclick = (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/approve`, { method: "POST" });
});

$("#btn-document").onclick = () =>
  window.open(`/api/offers/${current.id}/document`, "_blank");

const setStatus = (status) => (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/status`, jsonOpts("POST", { status }));
});
$("#btn-send").onclick = setStatus("sent");
$("#btn-accept").onclick = setStatus("accepted");
$("#btn-reject").onclick = setStatus("rejected");

/* ---------------- Neue Anfrage (Text + Dateien) ---------------- */

$("#btn-new").onclick = () => $("#dlg-new").showModal();
$("#btn-cancel").onclick = () => $("#dlg-new").close();

$("#btn-analyze").onclick = async (e) => {
  const text = $("#new-text").value.trim();
  const fileInput = $("#new-files");
  if (!text && fileInput.files.length === 0)
    return alert("Bitte Text einfügen oder Dateien anhängen.");
  e.target.disabled = true;
  $("#new-status").textContent = "KI-Analyse läuft — das kann eine Minute dauern…";
  try {
    const form = new FormData();
    form.append("text", text);
    if ($("#new-email").value) form.append("customer_email", $("#new-email").value);
    for (const f of fileInput.files) form.append("files", f);
    const offer = await api("/api/inquiries", { method: "POST", body: form });
    $("#dlg-new").close();
    $("#new-text").value = "";
    fileInput.value = "";
    $("#new-status").textContent = "";
    current = offer;
    renderWorkspace();
    refreshList();
  } catch (err) {
    $("#new-status").textContent = "Fehler: " + err.message;
  } finally {
    e.target.disabled = false;
  }
};

/* ---------------- E-Mail-Eingang ---------------- */

async function initMail() {
  try {
    const s = await api("/api/email/status");
    if (!s.configured) return;
    $("#btn-mail").classList.remove("hidden");
    $("#mail-state").textContent = s.enabled
      ? `E-Mail-Eingang aktiv (${s.processed} importiert, ${s.skipped} übersprungen)`
      : "";
  } catch {}
}

$("#btn-mail").onclick = (e) => withBusy(e.target, async () => {
  const result = await api("/api/email/check", { method: "POST" });
  const imported = result.imported.length;
  alert(`${result.checked} neue E-Mail(s) geprüft, ${imported} als Anfrage importiert.`);
  if (imported) await loadOffer(result.imported[0].offer_id);
  initMail();
});

refreshList();
initMail();
