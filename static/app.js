/* Review interface: offer list, three-panel review, edits, approval workflow. */

const $ = (sel) => document.querySelector(sel);
let current = null; // currently loaded offer record

const eur = (v) =>
  new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" }).format(v);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

/* ---------------- offer list ---------------- */

async function refreshList() {
  const offers = await api("/api/offers");
  const ul = $("#offers");
  ul.innerHTML = "";
  for (const o of offers) {
    const li = document.createElement("li");
    if (current && current.id === o.id) li.classList.add("active");
    const name = o.analysis.customer_name || o.customer_email || "Unknown customer";
    li.innerHTML = `<span class="name">#${o.id} ${esc(name)}</span>
      <span class="sub">${esc(o.status)} · ${eur(o.final_price ?? o.costing.recommended_price)}</span>`;
    li.onclick = () => loadOffer(o.id);
    ul.appendChild(li);
  }
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = String(s ?? "");
  return d.innerHTML;
}

/* ---------------- workspace rendering ---------------- */

async function loadOffer(id) {
  current = await api(`/api/offers/${id}`);
  renderWorkspace();
  refreshList();
}

function renderWorkspace() {
  const o = current;
  $("#workspace").classList.remove("hidden");
  $("#empty-state").classList.add("hidden");

  $("#ws-title").textContent =
    `Offer #${o.id} — ${o.analysis.customer_name || o.customer_email || "Unknown customer"}`;
  const st = $("#ws-status");
  st.textContent = o.status;
  st.className = `badge ${o.status}`;

  $("#raw-inquiry").textContent = o.raw_inquiry;

  // customer / deadline block
  const a = o.analysis;
  $("#customer-block").innerHTML = `
    <p class="muted">
      Customer: <strong>${esc(a.customer_name || "—")}</strong> ·
      Contact: ${esc(a.customer_contact || "—")} ·
      Deadline: ${esc(a.deadline || "—")}
    </p>`;

  // editable parts
  const partsDiv = $("#parts");
  partsDiv.innerHTML = "";
  a.parts.forEach((p, i) => {
    const card = document.createElement("div");
    card.className = "part-card";
    card.innerHTML = `
      <span class="pname">${esc(p.name)}</span>
      ${p.material_is_assumption ? '<span class="assumed"> (material assumed)</span>' : ""}
      <div class="muted">${esc(p.description)}</div>
      <div class="grid">
        <label>Quantity
          <input type="number" min="1" data-i="${i}" data-f="quantity" value="${p.quantity}"></label>
        <label>Material
          <input type="text" data-i="${i}" data-f="material" value="${esc(p.material)}"></label>
        <label>Hours / part
          <input type="number" step="0.1" min="0" data-i="${i}"
                 data-f="estimated_machining_hours_per_part"
                 value="${p.estimated_machining_hours_per_part}"></label>
        <label>Mass kg / part
          <input type="number" step="0.1" min="0" data-i="${i}"
                 data-f="estimated_mass_kg_per_part"
                 value="${p.estimated_mass_kg_per_part}"></label>
        <label>Complexity
          <select data-i="${i}" data-f="complexity">
            ${["low", "medium", "high", "very_high"].map(
              (c) => `<option ${c === p.complexity ? "selected" : ""}>${c}</option>`
            ).join("")}
          </select></label>
        <label>Confidence
          <input type="number" disabled value="${p.confidence}%"></label>
      </div>`;
    partsDiv.appendChild(card);
  });

  $("#assumptions").innerHTML = a.assumptions.map(
    (x) => `<li><strong>${esc(x.field)}:</strong> ${esc(x.assumption)}
            <span class="muted">(${x.confidence}%)</span></li>`
  ).join("") || "<li class='muted'>None</li>";

  $("#missing").innerHTML = a.missing_information.map((m) => `<li>${esc(m)}</li>`).join("")
    || "<li class='muted'>Nothing flagged</li>";

  const r = o.risks;
  $("#risk-score").textContent = `severity ${r.overall_severity}/5`;
  $("#risk-summary").textContent = r.summary;
  $("#risks").innerHTML = r.risks.map(
    (x) => `<li><span class="sev sev-${x.severity}">${x.severity}</span>
            <strong>${esc(x.category.replaceAll("_", " "))}:</strong> ${esc(x.description)}
            <div class="muted">→ ${esc(x.mitigation)}</div></li>`
  ).join("") || "<li class='muted'>No risks identified</li>";

  // cost panel
  const c = o.costing;
  $("#cost-table tbody").innerHTML = c.parts.map(
    (p) => `<tr><td>${esc(p.part_name)}</td><td>${p.quantity}</td>
            <td>${esc(p.material)}</td><td>${eur(p.labor_cost)}</td>
            <td>${eur(p.subtotal)}</td></tr>`
  ).join("");

  $("#cost-summary").innerHTML = `
    <dt>Direct cost</dt><dd>${eur(c.direct_cost)}</dd>
    <dt>Overhead (${(c.overhead_percent * 100).toFixed(0)}%)</dt><dd>${eur(c.overhead_cost)}</dd>
    <dt>Total cost</dt><dd>${eur(c.total_cost)}</dd>
    <dt>Recommended price</dt><dd class="big">${eur(c.recommended_price)}</dd>
    <dt>Margin</dt><dd>${eur(o.final_price ? o.final_price - c.total_cost : c.margin_eur)}
        (target ${(c.target_margin_percent * 100).toFixed(0)}%)</dd>`;

  $("#final-price").value = (o.final_price ?? c.recommended_price).toFixed(2);

  $("#confidence-fill").style.width = `${a.overall_confidence}%`;
  $("#confidence-fill").style.background =
    a.overall_confidence >= 70 ? "#5a9e4b" : a.overall_confidence >= 40 ? "#d09a26" : "#c0392b";
  $("#confidence-label").textContent = `${a.overall_confidence}% overall AI confidence`;

  // button states by status
  const editable = ["draft", "reviewed"].includes(o.status);
  $("#btn-save").disabled = !editable;
  $("#btn-price").disabled = !editable;
  $("#btn-approve").disabled = !editable;
  $("#btn-document").disabled = !o.offer_html;
  $("#btn-send").disabled = !(o.status === "reviewed" && o.offer_html);
  $("#btn-accept").disabled = o.status !== "sent";
  $("#btn-reject").disabled = ["accepted", "rejected"].includes(o.status);
}

/* ---------------- actions ---------------- */

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
  btn.textContent = "Working…";
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
  current = await api(`/api/offers/${current.id}/analysis`, {
    method: "PUT", body: JSON.stringify(collectEditedAnalysis()),
  });
});

$("#btn-price").onclick = (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/price`, {
    method: "POST", body: JSON.stringify({ final_price: Number($("#final-price").value) }),
  });
});

$("#btn-approve").onclick = (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/approve`, { method: "POST" });
});

$("#btn-document").onclick = () =>
  window.open(`/api/offers/${current.id}/document`, "_blank");

const setStatus = (status) => (e) => withBusy(e.target, async () => {
  current = await api(`/api/offers/${current.id}/status`, {
    method: "POST", body: JSON.stringify({ status }),
  });
});
$("#btn-send").onclick = setStatus("sent");
$("#btn-accept").onclick = setStatus("accepted");
$("#btn-reject").onclick = setStatus("rejected");

/* ---------------- new inquiry dialog ---------------- */

$("#btn-new").onclick = () => $("#dlg-new").showModal();
$("#btn-cancel").onclick = () => $("#dlg-new").close();

$("#btn-analyze").onclick = async (e) => {
  const text = $("#new-text").value.trim();
  if (!text) return alert("Paste an inquiry first.");
  e.target.disabled = true;
  $("#new-status").textContent = "Analyzing with AI — this can take a minute…";
  try {
    const offer = await api("/api/inquiries", {
      method: "POST",
      body: JSON.stringify({ text, customer_email: $("#new-email").value || null }),
    });
    $("#dlg-new").close();
    $("#new-text").value = "";
    current = offer;
    renderWorkspace();
    refreshList();
  } catch (err) {
    $("#new-status").textContent = "Error: " + err.message;
  } finally {
    e.target.disabled = false;
  }
};

refreshList();
