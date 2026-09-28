"""Write the ranked shortlist as JSON, CSV, Markdown and a standalone HTML page."""

from __future__ import annotations

import csv
import datetime as dt
import html
import json
from pathlib import Path


def _money(v) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.0f}"


def payload(result: dict, profile: dict) -> dict:
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "max_purchase_price": result["max_purchase_price"],
        "scanned": result["scanned"],
        "matched": result["matched"],
        "rejected_by": result["rejected_by"],
        "no_price": result["no_price"],
        "criteria": profile["criteria"],
        "assumptions": profile["assumptions"],
        "top": [a.to_dict() for a in result["top"]],
    }


def write(result: dict, profile: dict, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    data = payload(result, profile)
    paths = {
        "json": out_dir / f"shortlist-{stamp}.json",
        "csv": out_dir / f"shortlist-{stamp}.csv",
        "md": out_dir / f"shortlist-{stamp}.md",
        "html": out_dir / f"shortlist-{stamp}.html",
    }
    paths["json"].write_text(json.dumps(data, indent=1), encoding="utf-8")
    write_csv(data, paths["csv"])
    paths["md"].write_text(markdown(data), encoding="utf-8")
    paths["html"].write_text(render_html(data), encoding="utf-8")
    return paths


def write_csv(data: dict, path: Path) -> None:
    cols = ["rank", "score", "verdict", "address", "suburb", "type", "price", "beds", "baths", "cars", "land_sqm",
            "weekly_rent", "rent_method", "gross_yield_pct", "after_tax_weekly", "loan", "lvr", "serviceability_surplus",
            "url"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for a in data["top"]:
            l, cf = a["listing"], a["cash_flow"]
            w.writerow([a["rank"], a["score"], a["verdict"], l["address"], l["suburb"], l["property_type"], l["price"],
                        l["bedrooms"], l["bathrooms"], l["car_spaces"], l["land_size_sqm"], a["rent"]["weekly"],
                        a["rent"]["method"], cf["gross_yield_pct"], cf["after_tax_weekly"], a["purchase"]["loan"],
                        a["purchase"]["lvr"], a["serviceability"]["surplus_monthly"], l["url"]])


def markdown(data: dict) -> str:
    lines = [
        f"# WA investment shortlist ({data['generated'][:10]})",
        "",
        f"Max purchase price from your pre-approval and cash: **{_money(data['max_purchase_price'])}**. "
        f"Scanned {data['scanned']} listings, {data['matched']} matched your criteria.",
        "",
        "| # | Score | Verdict | Property | Price | Beds/Bath/Car | Rent/wk | Yield | After-tax/wk |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in data["top"]:
        l, cf = a["listing"], a["cash_flow"]
        name = f"[{l['address'] or l['suburb']}, {l['suburb']}]({l['url']})" if l["url"] else f"{l['address']}, {l['suburb']}"
        lines.append(
            f"| {a['rank']} | {a['score']:.0f} | {a['verdict']} | {name} | {_money(l['price'])} | "
            f"{l['bedrooms'] or '?'}/{l['bathrooms'] or '?'}/{l['car_spaces'] if l['car_spaces'] is not None else '?'} | "
            f"{_money(a['rent']['weekly'])} | {cf['gross_yield_pct']:.1f}% | {_money(cf['after_tax_weekly'])} |"
        )
    lines += ["", "Screening estimates only, not financial, tax or credit advice."]
    return "\n".join(lines) + "\n"


CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1c1c1a;--muted:#6b6b66;--line:#e4e4df;--good:#1f7a4d;--warn:#a86400;--bad:#b3261e;--accent:#0b5cad}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151514;--card:#1f1f1d;--ink:#ecece8;--muted:#a3a39c;--line:#34342f;--good:#5cc28f;--warn:#e0a44a;--bad:#f07a70;--accent:#6aa9ec}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px}h1{font-size:1.5rem;margin:0 0 4px}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:12px 0}
.head{display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}.rank{font-weight:700;font-size:1.3rem;min-width:2.2em}
.score{font-weight:700;font-variant-numeric:tabular-nums}.pill{border-radius:99px;padding:2px 10px;font-size:.8rem;border:1px solid currentColor}
.v-good{color:var(--good)}.v-warn{color:var(--warn)}.v-bad{color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:10px}
.kv{font-size:.85rem}.kv b{display:block;font-size:1rem;font-variant-numeric:tabular-nums}
ul{margin:6px 0;padding-left:18px}a{color:var(--accent)}
"""


def verdict_class(v: str) -> str:
    return {"Strong candidate": "v-good", "Worth a look": "v-good", "Marginal": "v-warn"}.get(v, "v-bad")


def render_html(data: dict) -> str:
    e = html.escape
    cards = []
    for a in data["top"]:
        l, cf, p, s, r = a["listing"], a["cash_flow"], a["purchase"], a["serviceability"], a["rent"]
        title = e(f"{l['address'] or 'Address withheld'}, {l['suburb']} {l['postcode']}")
        link = f'<a href="{e(l["url"])}" target="_blank" rel="noopener">{title}</a>' if l["url"] else title
        pros = "".join(f"<li>{e(x)}</li>" for x in a["pros"])
        cons = "".join(f"<li>{e(x)}</li>" for x in a["cons"])
        cards.append(f"""
<div class="card"><div class="head"><span class="rank">#{a['rank']}</span><span class="score">{a['score']:.0f}/100</span>
<span class="pill {verdict_class(a['verdict'])}">{e(a['verdict'])}</span><span>{link}</span></div>
<div class="muted">{e(l['property_type'])} · {l['bedrooms'] or '?'} bed · {l['bathrooms'] or '?'} bath · {l['car_spaces'] if l['car_spaces'] is not None else '?'} car{f" · {l['land_size_sqm']:,.0f} m²" if l['land_size_sqm'] else ''} · {e(l['price_text'] or _money(l['price']))}</div>
<div class="grid">
<div class="kv">Price used<b>{_money(l['price'])}</b></div>
<div class="kv">Rent estimate<b>{_money(r['weekly'])}/wk</b><span class="muted">{e(r['method'])}</span></div>
<div class="kv">Gross / net yield<b>{cf['gross_yield_pct']:.1f}% / {cf['net_yield_pct']:.1f}%</b></div>
<div class="kv">Cash flow after tax<b>{_money(cf['after_tax_weekly'])}/wk</b></div>
<div class="kv">Loan (LVR)<b>{_money(p['loan'])} ({p['lvr']:.0%})</b></div>
<div class="kv">Cash needed<b>{_money(p['cash_used'])}</b><span class="muted">incl. duty {_money(p['duty'])}</span></div>
<div class="kv">Bank test surplus<b>{_money(s['surplus_monthly'])}/mo</b></div>
<div class="kv">Equity yr {len(a['projection'])}<b>{_money(a['projection'][-1]['equity'] if a['projection'] else None)}</b></div>
</div>
<div class="grid"><div><b class="v-good">Pros</b><ul>{pros or '<li>None noted</li>'}</ul></div>
<div><b class="v-bad">Cons</b><ul>{cons or '<li>None noted</li>'}</ul></div></div></div>""")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>WA Property Shortlist</title><style>{CSS}</style></head><body><main>
<h1>WA investment shortlist</h1>
<p class="muted">Generated {e(data['generated'])}. Max purchase price {_money(data['max_purchase_price'])}. Scanned {data['scanned']} listings, {data['matched']} matched your criteria. Screening estimates only, not financial, tax or credit advice.</p>
{''.join(cards) or '<p>No listings matched. Loosen your criteria or add listings to data/inbox/.</p>'}
</main></body></html>"""
