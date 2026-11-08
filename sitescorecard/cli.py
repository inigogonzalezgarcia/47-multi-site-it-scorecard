"""Command line: `demo` writes the fictional Contoso Europe exports to sample_data/ and builds the outputs; `review` runs on your own
exports."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import report, simulate
from .checks import AMBER, GREEN, RED, review, run_all, summary
from .model import load, month_label, parse_dt

OUTPUTS = ("report.html", "regional-review-pack.md", "site-scorecard.csv", "kpi-detail.csv", "trend.csv", "actions.csv", "findings.csv")


def run(data: Path, out: Path, title: str | None = None, as_of: datetime | None = None, month: str | None = None) -> dict:
    d = load(data, as_of, month)
    rv = review(d)
    findings = run_all(d, rv)
    title = title or f"{d.settings.organisation} · IT scorecard, {month_label(d.month)}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.html").write_text(report.render_html(d, rv, findings, title), encoding="utf-8")
    (out / "regional-review-pack.md").write_text(report.pack_md(d, rv, findings, title), encoding="utf-8")
    report.write_scorecard(d, rv, out / "site-scorecard.csv")
    report.write_detail(d, rv, out / "kpi-detail.csv")
    report.write_trend(d, rv, out / "trend.csv")
    report.write_actions(d, findings, out / "actions.csv")
    report.write_findings(findings, out / "findings.csv")
    sm = summary(d, rv, findings)
    sm["site_status"] = [(r["site"].name, r["status"], r["score"]) for r in rv["sites"]]
    return sm


def _when(value: str) -> datetime:
    d = parse_dt(value)
    if not d:
        raise argparse.ArgumentTypeError(f"not a date (YYYY-MM-DD or 'YYYY-MM-DD HH:MM'): {value}")
    return d


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="sitescorecard", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    dm = sub.add_parser("demo", help="write the fictional exports to sample_data/ and build the outputs")
    dm.add_argument("--data", type=Path, default=Path("sample_data"))
    dm.add_argument("--out", type=Path, default=Path("output"))
    rv = sub.add_parser("review", help="build the outputs from your own exports")
    rv.add_argument("data", type=Path, nargs="?", help="folder with sites.csv, tickets.csv and the other exports")
    rv.add_argument("--data", dest="data_opt", type=Path, help="same as the positional folder")
    rv.add_argument("--out", type=Path, default=Path("output"))
    rv.add_argument("--title", help="title of the report and the pack")
    rv.add_argument("--month", help="month to report, YYYY-MM (default: settings.json, or the month before the reference date)")
    rv.add_argument("--as-of", type=_when, help="reference date (default: settings.json, or now)")
    a = p.parse_args(argv)
    if a.cmd == "demo":
        simulate.write(a.data)
        sm = run(a.data, a.out, f"{simulate.ORG} · regional IT scorecard, October 2026")
    else:
        folder = a.data or a.data_opt
        if not folder:
            print("error: give the folder with sites.csv and tickets.csv", file=sys.stderr)
            return 2
        try:
            sm = run(folder, a.out, a.title, a.as_of, a.month)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    st = sm["status"]
    sites = ", ".join(f"{n} {s.upper()} {0 if sc is None else sc:.0f}" for n, s, sc in sm["site_status"])
    print(f"{month_label(sm['month'])} · region {sm['region_status'].upper()} {0 if sm['region_score'] is None else sm['region_score']:.0f} · "
          f"{st.get(GREEN, 0)} green, {st.get(AMBER, 0)} amber, {st.get(RED, 0)} red sites · {sites} · {sm['red']} red KPIs "
          f"({sm['new_red']} new), {sm['amber']} amber, {sm['not_rated']} not rated")
    print(f"outputs in {a.out}/: {', '.join(OUTPUTS)}")
    return 0
