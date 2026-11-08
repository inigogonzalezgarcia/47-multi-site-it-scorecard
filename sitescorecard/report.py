"""Outputs: report.html (regional heatmap of sites by KPI, a card per site, the top reasons and every finding), regional-review-pack.md
(the pack for the regional review, one section per site with decisions and owners), and the CSVs: site-scorecard, kpi-detail, trend,
actions and findings."""
from __future__ import annotations

import csv
import html
from pathlib import Path

from .checks import (AMBER, CODES, GREEN, META, NA, RED, Finding, fmt, pct, proposal, summary, target_text, top_reasons)
from .model import FILES, Data, month_end, month_label

e = html.escape
TODO = "**[TO COMPLETE]**"
ARROW = {"up": "↑", "down": "↓", "same": "→", "": ""}


# ---------------------------------------------------------------- csv

def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _f(x, k=4) -> str:
    return "" if x is None else f"{x:.{k}f}"


def _rows_all(rv: dict) -> list[dict]:
    return rv["sites"] + [rv["region"]]


def write_scorecard(d: Data, rv: dict, path: Path) -> None:
    head = ["month", "site", "city", "country", "users", "local_it_staff", "score", "previous_score", "status", "previous_status", "red",
            "amber", "green", "not_rated", "proposal"]
    for c in CODES:
        head += [f"{c.lower()}_value", f"{c.lower()}_status"]
    out = []
    for r in _rows_all(rv):
        st = [r["kpis"][c].status for c in CODES]
        row = [d.month, r["site"].code, r["site"].city, r["site"].country, r["site"].users, "" if r["site"].staff is None else r["site"].staff,
               _f(r["score"], 1), _f(r["prev_score"], 1), r["status"], r["prev_status"], st.count(RED), st.count(AMBER), st.count(GREEN),
               st.count(NA), proposal(r)]
        for c in CODES:
            row += [_f(r["kpis"][c].value), r["kpis"][c].status]
        out.append(row)
    _w(path, head, out)


def write_detail(d: Data, rv: dict, path: Path) -> None:
    w = d.settings.weights
    rows = []
    for r in _rows_all(rv):
        for c in CODES:
            k = r["kpis"][c]
            p = k.previous
            rows.append([d.month, r["site"].code, c, META[c]["name"], "kpi", k.item, _f(k.value), _f(k.numerator, 2), _f(k.denominator, 0),
                         _f(k.target), _f(k.red), k.status, _f(p.value) if p else "", p.status if p else "", k.trend, w.get(c, 0), k.reason])
            for sub in k.detail:
                ps = sub.previous
                rows.append([d.month, r["site"].code, c, META[c]["name"], "detail", sub.item, _f(sub.value), _f(sub.numerator, 2),
                             _f(sub.denominator, 0), _f(sub.target), _f(sub.red), sub.status, _f(ps.value) if ps else "",
                             ps.status if ps else "", sub.trend, "", sub.reason])
    _w(path, ["month", "site", "kpi", "name", "level", "item", "value", "numerator", "denominator", "target", "red_threshold", "status",
              "previous_value", "previous_status", "trend", "weight", "reason"], rows)


def write_trend(d: Data, rv: dict, path: Path) -> None:
    rows = []
    for m, key, sk, stk in ((d.previous, "prev", "prev_score", "prev_status"), (d.month, "kpis", "score", "status")):
        for r in _rows_all(rv):
            rows.append([m, r["site"].code, "SCORE", _f(r[sk], 1), r[stk]])
            rows += [[m, r["site"].code, c, _f(r[key][c].value), r[key][c].status] for c in CODES]
    _w(path, ["month", "site", "kpi", "value", "status"], rows)


def write_findings(findings: list[Finding], path: Path) -> None:
    _w(path, ["severity", "site", "city", "kpi", "name", "value", "target", "previous", "trend", "new_red", "reason", "next_step", "owner"],
       [[f.severity, f.site, f.site_name, f.code, f.kpi, f.value, f.target, f.previous, f.trend, "yes" if f.new else "", f.reason, f.fix,
         f.owner] for f in findings])


def write_actions(d: Data, findings: list[Finding], path: Path) -> None:
    due = d.settings.next_review
    xs = [f for f in findings if f.severity == "red" or (f.severity == "amber" and f.trend.endswith("worse"))]
    _w(path, ["ref", "site", "kpi", "action", "next_step", "owner", "severity", "trend", "due", "decision", "done"],
       [[f"{d.month}-{f.site}-{f.code}", f.site, f.code, f"{f.site_name}: {f.kpi} {f.value} (target {f.target})", f.fix, f.owner, f.severity,
         f.trend, due, "", ""] for f in xs])


# ---------------------------------------------------------------- the pack

def _md(x) -> str:
    return str(x).replace("|", "/")


def _cap(x: str) -> str:
    return x[:1].upper() + x[1:]


def _cell(k) -> str:
    if k.value is None:
        return "n/a"
    return f"{fmt(k.code, k.value)} {ARROW[k.trend]}".strip() + ("" if k.status in (GREEN, NA) else f" **{k.status.upper()}**")


def _score(x) -> str:
    return "–" if x is None else f"{x:.0f}"


def pack_md(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s = d.settings
    sm = summary(d, rv, findings)
    reg = rv["region"]
    m, pm = month_label(d.month), month_label(d.previous)
    out = [f"# {title}", "",
           f"> Generated by sitescorecard on {d.as_of:%a %d %b %Y} from the exports listed under *Scope and evidence*. Read-only: nothing was "
           f"changed in any tool. The month is {m}, compared with {pm}; sections marked {TODO} are for the meeting.", "",
           f"**Region: {reg['status'].upper()}, score {_score(reg['score'])} ({_score(reg['prev_score'])} in {pm})**", "",
           "## Decisions per site", "",
           "| Site | Users | Score | Previous | Status | Reds | New reds | Proposal | Owner | Decision |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rv["sites"]:
        reds = [f for f in findings if f.site == r["site"].code and f.severity == "red"]
        out.append(f"| {_md(r['site'].name)} | {r['site'].users:,} | {_score(r['score'])} | {_score(r['prev_score'])} | **{r['status'].upper()}** | "
                   f"{', '.join(f.code for f in reds) or '–'} | {sum(f.new for f in reds)} | {proposal(r)} | {_md(r['site'].lead or '–')} | "
                   f"{TODO if r['status'] == RED else ''} |")
    st = sm["status"]
    out += ["", "## Headlines", "",
            f"- {sm['sites']} sites, {sm['users']:,} users: {st.get(GREEN, 0)} green, {st.get(AMBER, 0)} amber, {st.get(RED, 0)} red; regional "
            f"score {_score(reg['score'])} ({_score(reg['prev_score'])} in {pm}).",
            f"- **{sm['red']} red KPIs** ({sm['new_red']} new this month), {sm['amber']} amber, {sm['not_rated']} not rated for low volume.",
            f"- Lowest site: **{sm['worst']['site'].name}** at {_score(sm['worst']['score'])}."]
    for f in top_reasons(findings, 6):
        out.append(f"- {f.site_name}, {f.kpi}: {f.value} ({'new' if f.new else 'again'}). {_md(_cap(f.reason))}.")
    out += ["", "## Scope and evidence", "", f"- Organisation: {s.organisation}", f"- Month: {m} (to {month_end(d.month):%d %b %Y}), "
            f"compared with {pm}", f"- Reference date: {d.as_of:%a %d %b %Y %H:%M}",
            "- Availability counts unplanned minutes only, 24x7; planned maintenance is listed but not held against the target",
            "", "| Source | File | Records |", "|---|---|---|"]
    out += [f"| {FILES.get(k, k)} | `{k}` | {v:,} |" for k, v in d.sources.items()]
    out += ["", "## Regional heatmap", "", "| Site | Score | " + " | ".join(META[c]["short"] for c in CODES) + " |",
            "|---|---|" + "---|" * len(CODES)]
    for r in _rows_all(rv):
        out.append(f"| {_md(r['site'].name)} | {_score(r['score'])} | " + " | ".join(_cell(r["kpis"][c]) for c in CODES) + " |")
    out += ["", "↑ ↓ against the previous month; a value with no word is green, n/a is not rated (no data or under the minimum volume)."]
    for n, r in enumerate(rv["sites"], start=1):
        site = r["site"]
        out += ["", f"## {n}. {site.name} ({site.code}): {r['status'].upper()}, score {_score(r['score'])}", "",
                f"{site.users:,} users, {'no' if site.staff == 0 else site.staff if site.staff is not None else 'unknown'} local IT staff, "
                f"comms room {'yes' if site.comms_room else 'no' if site.comms_room is False else 'unknown'}; site lead {site.lead or '–'}. "
                f"Previous score {_score(r['prev_score'])} ({r['prev_status']}); {r['rated']} of {len(CODES)} KPIs rated.", "",
                "| KPI | Value | Previous | Target | Status | Reason |", "|---|---|---|---|---|---|"]
        for c in CODES:
            k = r["kpis"][c]
            tgt = target_text(c, k.target, k.red) if k.target is not None else "–"
            out.append(f"| {META[c]['name']}{' (' + _md(k.item) + ')' if k.item else ''} | {fmt(c, k.value)} {ARROW[k.trend]} | "
                       f"{fmt(c, k.previous.value) if k.previous else '–'} | {_md(tgt)} | {k.status.upper() if k.status != NA else 'n/a'} | "
                       f"{_md(k.reason) if k.status != GREEN else ''} |")
        mine = [f for f in findings if f.site == site.code and f.severity in ("red", "amber")]
        out += ["", "| Decision | Owner | Due |", "|---|---|---|"]
        if mine:
            out += [f"| {f.code}: {_md(f.fix)} | {_md(f.owner)} | {(s.next_review or TODO) if f.severity == 'red' else 'next review'} |" for f in mine]
        else:
            out.append("| No action | – | – |")
    out += ["", "## Actions", "", "| Ref | Site | Action | Owner | Due | Decision |", "|---|---|---|---|---|---|"]
    acts = [f for f in findings if f.severity == "red" or (f.severity == "amber" and f.trend.endswith("worse"))]
    out += [f"| {d.month}-{f.site}-{f.code} | {f.site_name} | {_md(f.kpi)} {f.value} | {_md(f.owner)} | {s.next_review or TODO} | |" for f in acts]
    out += ["", "## Notes", "",
            "- RAG: green at or better than the target, red worse than the red threshold, amber in between. A KPI under its minimum volume "
            "(for example SLA on fewer than "
            f"{int(s.target('SLA').get('min') or 0)} resolved tickets) is n/a, not green, and is read ticket by ticket instead.",
            f"- Site score: the weighted share of points (green 100, amber 50, red 0) over the rated KPIs; green from {s.score_green:g}, amber "
            f"from {s.score_amber:g}, and a site with a red KPI is never green. The regional score is the average of the sites weighted by users.",
            "- The trend compares the same KPI with the previous month; *better* or *worse* depends on the direction of the KPI.",
            "- In the regional row, availability shows the worst site, and overdue actions and DR test freshness take the status of the worst site; the other KPIs are computed on the pooled data of all sites.",
            f"- Decisions of the regional review: {TODO}", "",
            "## Sign-off", "", f"- Prepared by (regional IT lead): {TODO}",
            f"- Reviewed with (site leads, service desk, network, workplace, BCP): {TODO}", f"- Date: {TODO}", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- html

CSS = """
:root{--bg:#f6f7f8;--card:#fff;--ink:#1b2128;--muted:#66717c;--line:#e2e5e9;--ok:#1e7a4c;--warn:#a46200;--bad:#b42318;--info:#0b6bcb;
--g:#dff3e8;--a:#fdf0d5;--r:#fbe0dd;--n:#eef0f2}
@media (prefers-color-scheme:dark){:root{--bg:#13171b;--card:#1b2127;--ink:#e7eaee;--muted:#9aa5b0;--line:#2b333b;--ok:#4cc38a;--warn:#f0a83a;
--bad:#f2685c;--info:#5aa9f0;--g:#173527;--a:#3d2f12;--r:#45201d;--n:#232a31}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1100px;margin:0 auto;padding:28px 18px 60px}h1{font-size:26px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 12px}h3{font-size:15px;margin:0 0 4px}
.muted{color:var(--muted)}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}.tile b{display:block;font-size:24px}
.overall{display:inline-block;margin-top:14px;padding:6px 14px;border-radius:99px;font-weight:700;border:2px solid currentColor}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tr:last-child td{border-bottom:0}.wrap{overflow-x:auto}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.heat th,.heat td{text-align:center;padding:6px 4px;font-size:13px;white-space:nowrap}.heat td:first-child,.heat th:first-child{text-align:left;padding-left:10px}
.heat td.green{background:var(--g)}.heat td.amber{background:var(--a)}.heat td.red{background:var(--r);font-weight:700}.heat td.na{background:var(--n);color:var(--muted)}
.heat tr.region td{border-top:2px solid var(--ink);font-weight:600}
.b{color:var(--ok)}.w{color:var(--bad)}
.pill{display:inline-block;white-space:nowrap;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600;border:1px solid currentColor}
.red{color:var(--bad)}.amber{color:var(--warn)}.green{color:var(--ok)}.info,.na{color:var(--info)}
.heat td.red,.heat td.amber,.heat td.green{color:inherit}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-top:5px solid var(--ok);border-radius:10px;padding:12px 16px}
.card.red{border-top-color:var(--bad);color:inherit}.card.amber{border-top-color:var(--warn);color:inherit}.card.green{color:inherit}
.card ul{margin:8px 0 0;padding-left:18px;font-size:13px}.card .sc{font-size:28px;font-weight:700;float:right;line-height:1}
td.subj{min-width:170px}td.nw{white-space:nowrap}td.fix{font-size:13px;color:var(--muted);min-width:200px;max-width:360px}td.sm{font-size:13px}
.brk{overflow-wrap:anywhere;word-break:break-word}
footer{margin-top:40px;font-size:13px}
"""


def _pill(cls: str, text: str) -> str:
    return f"<span class='pill {cls.replace('/', '')}'>{e(text)}</span>"


def _arrow(k) -> str:
    if not k.trend:
        return ""
    cls = "" if k.better is None else "b" if k.better else "w"
    return f" <span class='{cls}'>{ARROW[k.trend]}</span>"


def _table(head: list[str], rows: list[str], cls: str = "") -> str:
    return f"<div class='wrap'><table class='{cls}'><tr>" + "".join(f"<th>{e(h)}</th>" for h in head) + "</tr>" + "".join(rows) + "</table></div>"


def render_html(d: Data, rv: dict, findings: list[Finding], title: str) -> str:
    s = d.settings
    sm = summary(d, rv, findings)
    reg = rv["region"]
    m, pm = month_label(d.month), month_label(d.previous)
    st = sm["status"]
    h = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
         f"<title>{e(title)}</title><style>{CSS}</style></head><body><main>",
         f"<h1>{e(title)}</h1><p class='muted'>{e(s.organisation)} · {e(m)} compared with {e(pm)} · run on {d.as_of:%a %d %b %Y}</p>",
         f"<span class='overall {reg['status'].replace('/', '')}'>Region: {e(reg['status'].upper())} · score {_score(reg['score'])}</span>",
         "<div class='tiles'>"]
    worst = sm["worst"]
    tiles = [("Regional score", _score(reg["score"]), f"{_score(reg['prev_score'])} in {pm}"),
             ("Sites", f"{st.get(GREEN, 0)} · {st.get(AMBER, 0)} · {st.get(RED, 0)}", "green · amber · red"),
             ("Red KPIs", str(sm["red"]), f"{sm['new_red']} new this month"),
             ("Amber KPIs", str(sm["amber"]), f"{sm['not_rated']} not rated (volume)"),
             ("Lowest site", worst["site"].name, f"score {_score(worst['score'])}"),
             ("Users", f"{sm['users']:,}", f"{sm['sites']} sites · {sm['tickets']:,} tickets resolved")]
    h += [f"<div class='tile'><span class='muted'>{e(x)}</span><b>{e(y)}</b><span class='muted'>{e(z)}</span></div>" for x, y, z in tiles]
    h.append("</div><h2>Regional heatmap</h2><p class='muted'>Each cell is the KPI for the month with its RAG and the move against the "
             "previous month (green arrow better, red arrow worse). Hover a cell for the reason; n/a is not rated (no data or under the "
             "minimum volume), not green.</p>")
    head = ["Site", "Score"] + [META[c]["short"] for c in CODES]
    rows = []
    for r in _rows_all(rv):
        cls = " class='region'" if r is reg else ""
        cells = "".join(f"<td class='{r['kpis'][c].status.replace('/', '')}' title='{e(r['kpis'][c].reason, quote=True)}'>"
                        f"{e(fmt(c, r['kpis'][c].value)) if r['kpis'][c].value is not None else 'n/a'}{_arrow(r['kpis'][c])}</td>" for c in CODES)
        rows.append(f"<tr{cls}><td><b>{e(r['site'].name)}</b></td><td class='{r['status'].replace('/', '')}'>{_score(r['score'])}"
                    f"{'' if r['prev_score'] is None or r['score'] is None else ' ' + ('↑' if r['score'] > r['prev_score'] + 0.5 else '↓' if r['score'] < r['prev_score'] - 0.5 else '→')}"
                    f"</td>{cells}</tr>")
    h.append(_table(head, rows, "heat"))
    reds = top_reasons(findings, 8)
    if reds:
        h.append("<h2>Top reasons</h2>")
        h.append(_table(["Site", "KPI", "Value", "Why", "Next step", "Owner"],
                        [f"<tr><td class='nw'><b>{e(f.site_name)}</b>{' ' + _pill('red', 'new') if f.new else ''}</td><td class='subj'>{e(f.kpi)}</td>"
                         f"<td class='num red'>{e(f.value)}</td><td class='sm brk'>{e(f.reason)}</td><td class='fix'>{e(f.fix)}</td>"
                         f"<td class='sm'>{e(f.owner)}</td></tr>" for f in reds]))
    h.append("<h2>Sites</h2><div class='cards'>")
    for r in rv["sites"]:
        site = r["site"]
        mine = [f for f in findings if f.site == site.code and f.severity in ("red", "amber")]
        li = [f"<li class='{'red' if f.severity == 'red' else ''}'><b>{e(f.code)}</b> {e(f.value)}: {e(f.reason)}</li>" for f in mine[:4]]
        more = len(mine) - len(li)
        na = len(CODES) - r["rated"]
        h.append(f"<div class='card {r['status'].replace('/', '')}'><span class='sc'>{_score(r['score'])}</span><h3>{e(site.name)} "
                 f"{_pill(r['status'], r['status'].upper())}</h3><span class='muted'>{site.users:,} users · local IT staff "
                 f"{'–' if site.staff is None else site.staff} · previous {_score(r['prev_score'])}{f' · {na} not rated' if na else ''}</span>"
                 f"<ul>{''.join(li) or '<li>All KPIs at target.</li>'}{f'<li class=muted>and {more} more</li>' if more > 0 else ''}</ul></div>")
    h.append("</div><h2>All findings</h2>")
    h.append(_table(["Status", "Site", "KPI", "Value", "Target", "Previous", "Reason", "Owner"],
                    [f"<tr><td>{_pill(f.severity, f.severity.upper() if f.severity != 'info' else 'N/A')}</td><td class='nw'>{e(f.site_name)}</td>"
                     f"<td class='subj'>{e(f.kpi)}</td><td class='num'>{e(f.value)}</td><td class='sm'>{e(f.target)}</td>"
                     f"<td class='num'>{e(f.previous)} {e(f.trend)}</td><td class='sm brk'>{e(f.reason)}</td>"
                     f"<td class='sm'>{e(f.owner)}</td></tr>" for f in findings]))
    h.append("<footer class='muted'>Generated by sitescorecard. Fictional demo data unless you ran it on your own exports. The pack for the "
             "regional review is regional-review-pack.md.</footer></main></body></html>")
    return "".join(h)


__all__ = ["render_html", "pack_md", "write_scorecard", "write_detail", "write_trend", "write_findings", "write_actions"]
