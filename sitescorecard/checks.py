"""The KPIs of the monthly multi-site IT scorecard, per site and for the region: service desk (SLA attainment by priority, first-contact
resolution, reopen and escalation rates, backlog per 100 users and its ageing, satisfaction), availability per service (unplanned minutes
only against the target), devices (compliance, stale check-ins, ageing hardware), overdue actions and DR test freshness. Every KPI gets a
RAG status against its target and red threshold, or n/a when the volume is too small to rate, the trend against the previous month and,
when it is not green, the reason found in the data. A weighted site score and a site status, and the findings for the regional review."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .model import Data, Site, month_end, month_label, month_minutes, month_start

GREEN, AMBER, RED, NA = "green", "amber", "red", "n/a"
RANK = {RED: 0, AMBER: 1, GREEN: 2, NA: 3}
POINTS = {GREEN: 100, AMBER: 50, RED: 0}
REGION = "REGION"
# code, name, short label, unit, higher is better, owner area
KPIS = [
    ("SLA", "SLA attainment", "SLA", "pct", True, "service desk"),
    ("FCR", "First-contact resolution", "FCR", "pct", True, "service desk"),
    ("REO", "Reopen rate", "Reopen", "pct1", False, "service desk"),
    ("ESC", "Escalated to the central team", "Escal.", "pct", False, "service desk"),
    ("BKL", "Backlog per 100 users", "Backlog", "num", False, "service desk"),
    ("AGE", "Backlog older than the ageing limit", "Ageing", "pct", False, "service desk"),
    ("CSAT", "Satisfaction (1-5)", "CSAT", "num2", True, "service desk"),
    ("AVL", "Unplanned availability", "Avail.", "pct2", True, "network"),
    ("CMP", "Device compliance", "Compl.", "pct", True, "workplace"),
    ("STL", "Devices with a stale check-in", "Stale", "pct1", False, "workplace"),
    ("HWA", "Devices older than the hardware limit", "HW age", "pct", False, "workplace"),
    ("ACT", "Overdue actions", "Overdue", "int", False, "site"),
    ("DRT", "Months since the last DR test", "DR test", "months", False, "bcp"),
]
CODES = [k[0] for k in KPIS]
META = {k[0]: {"name": k[1], "short": k[2], "unit": k[3], "higher": k[4], "area": k[5]} for k in KPIS}
EPS = {"pct": 0.005, "pct1": 0.001, "pct2": 0.0005, "num": 0.05, "num2": 0.05, "int": 0.5, "months": 99}
FIX = {
    "SLA": "Go through the breached tickets by priority with the service desk lead; check assignment, queue rules and cover for the site.",
    "FCR": "Look at the incidents closed after a hand-off: which could the first line have closed with a knowledge article or remote "
           "access?",
    "REO": "Sample the reopened tickets with the engineers; agree a closure check with the user.",
    "ESC": "List what was escalated and why: local skills, admin rights, a missing runbook or nobody on site.",
    "BKL": "Backlog review with the queue owner: close or merge stale requests, plan the capacity for the site.",
    "AGE": "Every ticket over the ageing limit gets an owner, a next step and a date, or is closed with the user.",
    "CSAT": "Read the low scores and call the users back; check response times and on-site presence.",
    "AVL": "Review the outages with the provider (references in the reason): root cause, RFO, service credits and the failover test.",
    "CMP": "Group the noncompliant devices by setting and OS build; fix the build or the policy and track to the target.",
    "STL": "Contact the users of devices with no check-in; retire lost or replaced devices from Intune.",
    "HWA": "Put the oldest devices in the next refresh wave and the budget.",
    "ACT": "Agree new dates or close; escalate what is blocked.",
    "DRT": "Book the DR/BCP test with the site and the business owners; record the result and the follow-ups.",
}


def pct(x: float | None, k: int = 0) -> str:
    return "–" if x is None else f"{x * 100:.{k}f}%"


def _n(k: int, word: str, plural: str | None = None) -> str:
    return f"{k} {word if k == 1 else (plural or word + 's')}"


def fmt(code: str, v: float | None) -> str:
    if v is None:
        return "–"
    u = META[code]["unit"]
    if u == "pct":
        return pct(v)
    if u == "pct1":
        return pct(v, 1)
    if u == "pct2":
        return pct(v, 2)
    if u == "num":
        return f"{v:.1f}"
    if u == "num2":
        return f"{v:.2f}"
    if u == "months":
        return f"{v:.0f} mo"
    return f"{v:.0f}"


def rag(v: float, target: float, red: float, higher: bool) -> str:
    if higher:
        return GREEN if v >= target - 1e-9 else RED if v < red - 1e-9 else AMBER
    return GREEN if v <= target + 1e-9 else RED if v > red + 1e-9 else AMBER


def target_text(code: str, target: float, red: float) -> str:
    h = META[code]["higher"]
    a, b = ("≥", "<") if h else ("≤", ">")
    return f"{a} {fmt(code, target)}, red {b} {fmt(code, red)}"


@dataclass
class Kpi:
    code: str
    value: float | None = None
    status: str = NA
    numerator: float | None = None
    denominator: float | None = None
    reason: str = ""
    target: float | None = None
    red: float | None = None
    item: str = ""
    detail: list = field(default_factory=list)       # sub-rows: Kpi with item set
    previous: "Kpi | None" = None
    trend: str = ""                                   # up, down, same or ''
    better: bool | None = None

    @property
    def rated(self) -> bool:
        return self.status != NA


def _kpi(code: str, v: float | None, s, num_=None, den=None, reason="", item="", target=None, red=None) -> Kpi:
    t = s.target(code)
    target = t.get("target") if target is None else target
    red = t.get("red") if red is None else red
    st = NA if v is None else rag(v, target, red, META[code]["higher"])
    return Kpi(code, v, st, num_, den, reason, target, red, item)


def _na(code: str, s, reason: str) -> Kpi:
    t = s.target(code)
    return Kpi(code, None, NA, reason=reason, target=t.get("target"), red=t.get("red"))


def _end(m: str) -> datetime:
    return datetime.combine(month_end(m) + timedelta(days=1), time())


# ---------------------------------------------------------------- one scope (a site or the region) for one month

def compute(d: Data, m: str, sites: list[Site]) -> dict[str, Kpi]:
    s = d.settings
    codes = {x.code for x in sites}
    users = sum(x.users for x in sites)
    single = sites[0] if len(sites) == 1 else None
    no_staff = bool(single and single.staff == 0)
    ms, me, end = month_start(m), month_end(m), _end(m)
    out: dict[str, Kpi] = {}
    tickets = [t for t in d.tickets if t.site in codes]
    resolved = [t for t in tickets if t.resolved and ms <= t.resolved.date() <= me]

    def staff_note(k: Kpi) -> Kpi:
        if no_staff and k.status in (RED, AMBER):
            k.reason += "; no local IT staff at the site (sites.csv)"
        return k

    def volume(code: str, n: int, what: str) -> Kpi | None:
        mn = int(s.target(code).get("min") or 0)
        if n < mn:
            return _na(code, s, f"{_n(n, what)}, under the minimum of {mn}: not rated")
        return None

    # SLA by priority
    rated = [t for t in resolved if t.sla is not None]
    k = volume("SLA", len(rated), "resolved ticket")
    if not k:
        met = sum(t.sla for t in rated)
        k = _kpi("SLA", met / len(rated), s, met, len(rated), f"{met} of {len(rated)} resolved tickets within SLA")
        low = []
        for p in sorted({t.priority for t in rated}):
            xs = [t for t in rated if t.priority == p]
            pm = sum(t.sla for t in xs)
            sub = _kpi("SLA", pm / len(xs), s, pm, len(xs), f"{pm} of {len(xs)}", item=p or "(no priority)")
            k.detail.append(sub)
            if sub.status != GREEN and len(xs) >= 5:
                low.append(f"{p} {pct(sub.value)} ({pm}/{len(xs)})")
        if low and k.status != GREEN:
            k.reason += "; under target: " + ", ".join(low)
    out["SLA"] = k
    # FCR on incidents
    inc = [t for t in resolved if t.incident and t.fcr is not None]
    k = volume("FCR", len(inc), "resolved incident")
    if not k:
        f = sum(t.fcr for t in inc)
        k = staff_note(_kpi("FCR", f / len(inc), s, f, len(inc), f"{f} of {len(inc)} incidents resolved at first contact"))
    out["FCR"] = k
    # reopen and escalation
    k = volume("REO", len(resolved), "resolved ticket")
    if not k:
        r = sum(t.reopened for t in resolved)
        k = _kpi("REO", r / len(resolved), s, r, len(resolved), f"{r} of {len(resolved)} resolved tickets reopened")
    out["REO"] = k
    k = volume("ESC", len(resolved), "resolved ticket")
    if not k:
        e = sum(t.escalated for t in resolved)
        k = staff_note(_kpi("ESC", e / len(resolved), s, e, len(resolved), f"{e} of {len(resolved)} resolved tickets escalated to the "
                                                                              "central team"))
    out["ESC"] = k
    # backlog and ageing at month end
    open_ = [t for t in tickets if t.opened < end and (t.resolved is None or t.resolved >= end)]
    if users:
        out["BKL"] = _kpi("BKL", len(open_) / users * 100, s, len(open_), users,
                          f"{_n(len(open_), 'ticket')} open on {me:%d %b} for {users:,} users")
    else:
        out["BKL"] = _na("BKL", s, "no users in sites.csv")
    lim = s.ageing_days
    k = volume("AGE", len(open_), "open ticket")
    ages = [(me - t.opened.date()).days for t in open_]
    buckets = [("0-7 days", 0, 7), (f"8-{lim} days", 8, lim), (f"{lim + 1}-60 days", lim + 1, 60), ("61+ days", 61, 10 ** 6)]
    if not k:
        old = [t for t, a in zip(open_, ages) if a > lim]
        k = _kpi("AGE", len(old) / len(open_), s, len(old), len(open_), f"{len(old)} of {len(open_)} open tickets older than {lim} days")
        if old:
            by_type = Counter("incident" if t.incident else "request" for t in old)
            oldest = min(old, key=lambda t: (t.opened, t.key))
            k.reason += (" (" + ", ".join(_n(v, n) for n, v in sorted(by_type.items(), key=lambda x: (-x[1], x[0])))
                         + f"; {sum(a > 60 for a in ages)} over 60 days; oldest {oldest.key} opened {oldest.opened:%d %b %Y})")
    for name, lo, hi in buckets:
        c = sum(lo <= a <= hi for a in ages)
        k.detail.append(Kpi("AGE", float(c), NA, c, len(open_), item=name))
    out["AGE"] = k
    # satisfaction
    sc = [t.csat for t in resolved if t.csat is not None]
    k = volume("CSAT", len(sc), "satisfaction response")
    if not k:
        low = sum(x <= 2 for x in sc)
        k = staff_note(_kpi("CSAT", sum(sc) / len(sc), s, sum(sc), len(sc), f"average of {_n(len(sc), 'response')}, {low} of them 1 or 2"))
    out["CSAT"] = k
    # availability per service, unplanned minutes only
    if d.sources.get("availability.csv") is None and not d.outages:
        out["AVL"] = _na("AVL", s, "no availability.csv")
    else:
        mins = month_minutes(m) * max(1, len(sites))
        ev = [o for o in d.outages if o.site in codes and ms <= o.start.date() <= me]
        services = list(s.availability_targets) + sorted({o.service for o in ev} - set(s.availability_targets))
        subs = []
        for sv in services:
            un = [o for o in ev if o.service == sv and not o.planned]
            pl = sum(o.minutes for o in ev if o.service == sv and o.planned)
            down = sum(o.minutes for o in un)
            tg = s.availability_targets.get(sv, 0.995)
            sub = _kpi("AVL", 1 - down / mins, s, down, mins, item=sv, target=tg, red=tg - s.availability_red_margin)
            refs = sorted({o.reference for o in un if o.reference})
            why = [c for c, _ in Counter(o.cause for o in un if o.cause).most_common(2)]
            sub.reason = (f"{sv} {pct(sub.value, 2)}: down {down:,.0f} min unplanned in {_n(len(un), 'outage')}"
                          + (f", {pl:,.0f} min planned" if pl else "") + (f"; {' and '.join(why)}" if why else "")
                          + (f" (refs {', '.join(refs)})" if refs else ""))
            subs.append(sub)
        worst = min(subs, key=lambda x: (RANK[x.status], x.value - x.target, x.item))
        k = Kpi("AVL", worst.value, worst.status, worst.numerator, worst.denominator, worst.reason, worst.target, worst.red, worst.item, subs)
        if worst.status == GREEN:
            k.reason = f"every service at target; lowest {worst.item} {pct(worst.value, 2)}"
        else:
            others = [x.reason for x in subs if x is not worst and x.status != GREEN]
            if others:
                k.reason += "; also " + "; ".join(others)
        out["AVL"] = k
    # devices: the latest snapshot of the month
    snaps = sorted({x.snapshot for x in d.devices if x.snapshot and ms <= x.snapshot <= me})
    devs = [x for x in d.devices if snaps and x.snapshot == snaps[-1] and x.site in codes]
    if not devs:
        for c in ("CMP", "STL", "HWA"):
            out[c] = _na(c, s, f"no device snapshot for {month_label(m)}" if d.devices else "no devices.csv")
    else:
        snap = snaps[-1]
        k = volume("CMP", len(devs), "device")
        if not k:
            ok = sum(x.compliant for x in devs)
            k = _kpi("CMP", ok / len(devs), s, ok, len(devs), f"{ok} of {len(devs)} devices compliant on {snap:%d %b}")
            bad = [x for x in devs if not x.compliant]
            if bad and k.status != GREEN:
                b, c = Counter(x.os for x in bad if x.os).most_common(1)[0] if any(x.os for x in bad) else ("", 0)
                on_b = sum(x.os == b for x in devs)
                if b and c >= len(bad) / 2:
                    k.reason += f"; {c} of the {len(bad)} noncompliant devices on OS build {b} ({on_b} devices run it, {pct(c / on_b)} of them noncompliant)"
                nenc = sum(x.encrypted is False for x in bad)
                if nenc:
                    k.reason += f"; {nenc} report no encryption"
        out["CMP"] = k
        k = volume("STL", len(devs), "device")
        if not k:
            stale = [x for x in devs if x.checkin is None or (snap - x.checkin).days > s.stale_days]
            k = _kpi("STL", len(stale) / len(devs), s, len(stale), len(devs),
                     f"{len(stale)} of {len(devs)} devices with no check-in for more than {s.stale_days} days")
        out["STL"] = k
        aged = [x for x in devs if x.age is not None]
        k = volume("HWA", len(aged), "device with an age")
        if not k:
            old = [x for x in aged if x.age > s.hardware_years]
            k = _kpi("HWA", len(old) / len(aged), s, len(old), len(aged),
                     f"{len(old)} of {len(aged)} devices older than {s.hardware_years:g} years")
        out["HWA"] = k
    # overdue actions at month end
    if d.sources.get("projects.csv") is None and not d.projects:
        out["ACT"] = _na("ACT", s, "no projects.csv")
    else:
        od = sorted([p for p in d.projects if p.site in codes and p.due and p.due < me and not (p.closed and p.closed <= me)
                     and not (p.done and not p.closed)], key=lambda p: (p.due, p.id))
        k = _kpi("ACT", float(len(od)), s, len(od), None, (f"{_n(len(od), 'action')} overdue on {me:%d %b}: " + "; ".join(
            f"{p.id} {p.title} (due {p.due:%d %b}, {p.owner or 'no owner'})" for p in od[:4]) + ("…" if len(od) > 4 else ""))
                 if od else "nothing overdue")
        out["ACT"] = k
    # DR test freshness
    if d.sources.get("dr_tests.csv") is None and not d.dr_tests:
        out["DRT"] = _na("DRT", s, "no dr_tests.csv")
    else:
        worst = None
        for site in sites:
            ts = sorted([t for t in d.dr_tests if t.site == site.code and t.day <= me], key=lambda t: t.day)
            if not ts:
                k = Kpi("DRT", None, RED, reason=f"{site.name}: no DR test recorded", target=s.dr_months, red=s.dr_months)
            else:
                t = ts[-1]
                mo = (me - t.day).days / 30.44
                res = (t.result or "").lower()
                due = t.day + timedelta(days=round(s.dr_months * 30.44))
                st = RED if mo > s.dr_months or res.startswith("fail") else AMBER if res.startswith("partial") or (due - me).days <= s.dr_warning_days else GREEN
                k = Kpi("DRT", mo, st, reason=f"last test {t.day:%d %b %Y} ({mo:.0f} months), {t.scope or 'scope not recorded'}, "
                                              f"result {t.result or 'not recorded'}" + (f" ({t.reference})" if t.reference else "")
                                              + (f"; next due by {due:%d %b %Y}" if st != RED else ""), target=s.dr_months, red=s.dr_months)
                if not single:
                    k.reason = f"{site.name}: {k.reason}"
            if worst is None or (RANK[k.status], -(k.value if k.value is not None else 999)) < (RANK[worst.status], -(worst.value if worst.value is not None else 999)):
                worst = k
        out["DRT"] = worst
    return out


def score(d: Data, kp: dict[str, Kpi]) -> float | None:
    w = d.settings.weights
    rated = [(w.get(c, 0), POINTS[k.status]) for c, k in kp.items() if k.rated and w.get(c, 0)]
    tot = sum(a for a, _ in rated)
    return sum(a * b for a, b in rated) / tot if tot else None


def site_status(d: Data, sc: float | None, kp: dict[str, Kpi]) -> str:
    w = d.settings.weights
    total = sum(w.get(c, 0) for c in CODES)
    rated = sum(w.get(c, 0) for c, k in kp.items() if k.rated and c in CODES)
    if sc is None or (total and rated / total < d.settings.min_coverage):
        return NA
    st = GREEN if sc >= d.settings.score_green else AMBER if sc >= d.settings.score_amber else RED
    if st == GREEN and any(k.status == RED for k in kp.values()):
        st = AMBER
    return st


def _trend(code: str, cur: Kpi, prev: Kpi) -> None:
    cur.previous = prev
    if cur.value is None or prev.value is None or META[code]["unit"] == "months":
        return
    delta = cur.value - prev.value
    if abs(delta) < EPS[META[code]["unit"]]:
        cur.trend, cur.better = "same", None
    else:
        cur.trend = "up" if delta > 0 else "down"
        cur.better = (delta > 0) == META[code]["higher"]


def _scope(d: Data, sites: list[Site]) -> dict:
    cur = compute(d, d.month, sites)
    prev = compute(d, d.previous, sites)
    for c in CODES:
        _trend(c, cur[c], prev[c])
        for sub in cur[c].detail:
            ps = next((x for x in prev[c].detail if x.item == sub.item), None)
            if ps:
                _trend(c, sub, ps)
    sc, psc = score(d, cur), score(d, prev)
    w = d.settings.weights
    total = sum(w.get(c, 0) for c in CODES)
    return {"kpis": cur, "prev": prev, "score": sc, "prev_score": psc, "status": site_status(d, sc, cur),
            "prev_status": site_status(d, psc, prev), "rated": sum(cur[c].rated for c in CODES),
            "coverage": sum(w.get(c, 0) for c in CODES if cur[c].rated) / total if total else None}


def review(d: Data) -> dict:
    rows = []
    for site in d.sites:
        r = _scope(d, [site])
        r["site"] = site
        rows.append(r)
    reg = _scope(d, d.sites)
    # availability: the region shows the worst site (a pooled figure would hide a site's outage behind seven good ones);
    # overdue actions and DR tests: the region takes the status of the worst site
    worst = [r for r in rows if r["kpis"]["AVL"].rated]
    if worst:
        w = min(worst, key=lambda r: (RANK[r["kpis"]["AVL"].status], r["kpis"]["AVL"].value - r["kpis"]["AVL"].target, r["site"].code))
        k = w["kpis"]["AVL"]
        reg["kpis"]["AVL"] = Kpi("AVL", k.value, k.status, k.numerator, k.denominator, f"{w['site'].name}: {k.reason}", k.target, k.red,
                                 f"{w['site'].name}, {k.item}", [], k.previous, k.trend, k.better)
    for c in ("ACT", "DRT"):
        rs = [r["kpis"][c] for r in rows if r["kpis"][c].rated]
        if rs:
            reg["kpis"][c].status = min(rs, key=lambda k: RANK[k.status]).status
    users = sum(r["site"].users for r in rows if r["score"] is not None)
    reg["score"] = sum(r["score"] * r["site"].users for r in rows if r["score"] is not None) / users if users else None
    pusers = sum(r["site"].users for r in rows if r["prev_score"] is not None)
    reg["prev_score"] = sum(r["prev_score"] * r["site"].users for r in rows if r["prev_score"] is not None) / pusers if pusers else None
    reg["status"] = site_status(d, reg["score"], reg["kpis"])
    reg["prev_status"] = site_status(d, reg["prev_score"], reg["prev"])
    reg["site"] = Site(REGION, "Region", "", sum(x.users for x in d.sites), sum(x.staff or 0 for x in d.sites))
    return {"sites": rows, "region": reg, "month": d.month, "previous": d.previous}


# ---------------------------------------------------------------- findings

@dataclass
class Finding:
    severity: str          # red, amber or info (not rated)
    site: str
    site_name: str
    code: str
    kpi: str
    value: str
    target: str
    previous: str
    trend: str
    reason: str
    fix: str
    owner: str
    new: bool = False
    weight: float = 0


def trend_word(k: Kpi) -> str:
    if not k.trend:
        return ""
    if k.trend == "same":
        return "same"
    return ("up" if k.trend == "up" else "down") + (", better" if k.better else ", worse")


def run_all(d: Data, rv: dict | None = None) -> list[Finding]:
    rv = rv if rv is not None else review(d)
    s = d.settings
    out = []
    for r in rv["sites"]:
        site = r["site"]
        for c in CODES:
            k = r["kpis"][c]
            volume_na = k.status == NA and "not rated" in k.reason
            if k.status not in (RED, AMBER) and not volume_na:
                continue
            sev = {RED: "red", AMBER: "amber"}.get(k.status, "info")
            owner = s.owner(META[c]["area"]) + (f" with {site.lead}" if site.lead else "")
            prev = k.previous
            out.append(Finding(sev, site.code, site.name, c, META[c]["name"] + (f" ({k.item})" if k.item else ""), fmt(c, k.value),
                               target_text(c, k.target, k.red) if k.target is not None else "", fmt(c, prev.value) if prev else "",
                               trend_word(k), k.reason, FIX[c] if sev != "info" else "Not rated this month; read the tickets one by one at the review.",
                               owner, sev == "red" and (prev is None or prev.status != RED), s.weights.get(c, 0)))
    order = {"red": 0, "amber": 1, "info": 2}
    out.sort(key=lambda f: (order[f.severity], -f.weight, f.site, CODES.index(f.code)))
    return out


def proposal(r: dict) -> str:
    return {RED: "recovery plan: an owner and a date for every red", AMBER: "actions on the reds and ambers, check next month",
            GREEN: "no action; keep", NA: "not rated"}[r["status"]]


def summary(d: Data, rv: dict, findings: list[Finding]) -> dict:
    rows = rv["sites"]
    reg = rv["region"]
    return dict(month=d.month, previous=d.previous, sites=len(rows), users=sum(r["site"].users for r in rows),
                region_score=reg["score"], region_prev=reg["prev_score"], region_status=reg["status"],
                status=Counter(r["status"] for r in rows), red=sum(f.severity == "red" for f in findings),
                amber=sum(f.severity == "amber" for f in findings), not_rated=sum(f.severity == "info" for f in findings),
                new_red=sum(f.new for f in findings), worst=min(rows, key=lambda r: (r["score"] if r["score"] is not None else 999, r["site"].code)),
                tickets=reg["kpis"]["SLA"].denominator or 0)


def top_reasons(findings: list[Finding], k: int = 8) -> list[Finding]:
    return [f for f in findings if f.severity == "red"][:k]


__all__ = ["KPIS", "CODES", "META", "GREEN", "AMBER", "RED", "NA", "REGION", "Kpi", "Finding", "compute", "review", "run_all", "summary",
           "proposal", "fmt", "pct", "target_text", "trend_word", "top_reasons", "score"]
