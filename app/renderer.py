"""Render the final commercial offer as a PDF-ready, print-styled HTML document."""

import html
from datetime import date

from .models import CostEstimate, InquiryAnalysis, OfferNarrative


def _e(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _eur(value: float) -> str:
    return f"€ {value:,.2f}"


def render_offer_html(
    offer_id: int,
    narrative: OfferNarrative,
    analysis: InquiryAnalysis,
    costing: CostEstimate,
    final_price: float,
) -> str:
    scope_items = "".join(f"<li>{_e(item)}</li>" for item in narrative.scope_of_work)

    pricing_rows = "".join(
        f"""<tr>
            <td>{_e(p.part_name)}</td>
            <td>{_e(p.material)}</td>
            <td class="num">{p.quantity}</td>
            <td class="num">{p.machining_hours_total:.1f} h</td>
            <td class="num">{_eur(p.subtotal)}</td>
        </tr>"""
        for p in costing.parts
    )

    assumption_items = "".join(
        f"<li><strong>{_e(a.field)}:</strong> {_e(a.assumption)} "
        f"<em>({_e(a.rationale)})</em></li>"
        for a in analysis.assumptions
    )
    if not assumption_items:
        assumption_items = "<li>No assumptions — all parameters were specified by the customer.</li>"

    customer = _e(analysis.customer_name or "Customer")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Offer {offer_id} — {_e(narrative.title)}</title>
<style>
  @page {{ size: A4; margin: 2cm; }}
  body {{ font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a;
         max-width: 800px; margin: 2rem auto; padding: 0 1.5rem; line-height: 1.55; }}
  header {{ border-bottom: 3px solid #1a3a5c; padding-bottom: 1rem; margin-bottom: 2rem; }}
  h1 {{ color: #1a3a5c; font-size: 1.6rem; margin: 0 0 .25rem; }}
  .meta {{ color: #555; font-size: .9rem; }}
  h2 {{ color: #1a3a5c; font-size: 1.1rem; border-bottom: 1px solid #ccc;
        padding-bottom: .25rem; margin-top: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: .95rem; }}
  th, td {{ border: 1px solid #bbb; padding: .45rem .6rem; text-align: left; }}
  th {{ background: #eef2f6; }}
  td.num, th.num {{ text-align: right; }}
  tr.total td {{ font-weight: bold; background: #eef2f6; font-size: 1.05rem; }}
  .terms {{ color: #555; font-size: .85rem; }}
  @media print {{ body {{ margin: 0; }} }}
</style>
</head>
<body>
<header>
  <h1>{_e(narrative.title)}</h1>
  <div class="meta">
    Offer No. {offer_id} &middot; Date: {date.today().isoformat()} &middot;
    For: {customer}
  </div>
</header>

<p>{_e(narrative.introduction)}</p>

<h2>1. Scope of Work</h2>
<ul>{scope_items}</ul>

<h2>2. Pricing</h2>
<table>
  <thead>
    <tr><th>Item</th><th>Material</th><th class="num">Qty</th>
        <th class="num">Prod. time</th><th class="num">Subtotal</th></tr>
  </thead>
  <tbody>
    {pricing_rows}
    <tr class="total"><td colspan="4">Total offer price (net, excl. VAT)</td>
        <td class="num">{_eur(final_price)}</td></tr>
  </tbody>
</table>

<h2>3. Delivery Timeline</h2>
<p>{_e(narrative.delivery_timeline)}</p>

<h2>4. Assumptions</h2>
<p>This offer is based on the following assumptions. Deviations may affect price and
delivery time:</p>
<ul>{assumption_items}</ul>

<h2>5. Terms &amp; Conditions</h2>
<p class="terms">[Placeholder — insert your company's standard terms: payment terms,
validity period, warranty, Incoterms, retention of title, applicable law.]</p>

<p>{_e(narrative.closing)}</p>
</body>
</html>"""
