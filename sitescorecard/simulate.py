"""Fictional demo: Contoso Europe, a made-up professional services company with about 2,500 people in eight European offices (Madrid,
Paris, Amsterdam, Copenhagen, Frankfurt, Geneva, Milan and Lisbon). The scorecard covers October 2026 against September 2026 and is run
on Sunday 8 November 2026, the day after the exports. Every person, ticket, device, circuit and number is made up. The problems are placed
on purpose among the everyday ones."""
from __future__ import annotations

import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

ORG = "Contoso Europe"
SEED = 47
EXPORT = datetime(2026, 11, 8, 7, 30)
SNAPSHOTS = (date(2026, 9, 30), date(2026, 10, 31))

SETTINGS = {
    "organisation": ORG,
    "as_of": "2026-11-08 09:00",
    "report_month": "2026-10",
    "next_review": "2026-12-10",
    "targets": {
        "SLA": {"target": 0.90, "red": 0.80, "min": 20}, "FCR": {"target": 0.70, "red": 0.60, "min": 15},
        "REO": {"target": 0.05, "red": 0.10, "min": 20}, "ESC": {"target": 0.15, "red": 0.25, "min": 20},
        "BKL": {"target": 7.0, "red": 10.0}, "AGE": {"target": 0.15, "red": 0.25, "min": 10},
        "CSAT": {"target": 4.2, "red": 3.8, "min": 10}, "CMP": {"target": 0.95, "red": 0.90, "min": 20},
        "STL": {"target": 0.03, "red": 0.08, "min": 20}, "HWA": {"target": 0.15, "red": 0.25, "min": 20},
        "ACT": {"target": 0, "red": 2}, "DRT": {"target": 12, "red": 12},
    },
    "availability_targets": {"WAN primary": 0.999, "WAN backup": 0.995, "Wi-Fi": 0.998, "Printing": 0.99, "Meeting rooms": 0.99,
                             "File and print": 0.998},
    "availability_red_margin": 0.005,
    "weights": {"SLA": 15, "FCR": 8, "REO": 5, "ESC": 5, "BKL": 8, "AGE": 8, "CSAT": 12, "AVL": 15, "CMP": 10, "STL": 4, "HWA": 4,
                "ACT": 3, "DRT": 3},
    "score_green": 85,
    "score_amber": 70,
    "min_coverage": 0.4,
    "ageing_days": 30,
    "stale_days": 14,
    "hardware_years": 4,
    "dr_months": 12,
    "dr_warning_days": 60,
    "owners": {"service desk": "Service desk lead (Marta Vidal)", "network": "Network lead (Jonas Weber)",
               "workplace": "Workplace lead (Sofie Jansen)", "site": "Regional IT lead (Laura Méndez)", "bcp": "BCP coordinator (Paolo Ricci)"},
}

# code, city, country, users, local IT staff, comms room, time zone, site lead
SITES = [
    ("MAD", "Madrid", "Spain", 480, 2, "Yes", "Europe/Madrid", "Carlos Ibáñez"),
    ("PAR", "Paris", "France", 620, 3, "Yes", "Europe/Paris", "Claire Dubois"),
    ("AMS", "Amsterdam", "Netherlands", 410, 2, "Yes", "Europe/Amsterdam", "Daan de Vries"),
    ("CPH", "Copenhagen", "Denmark", 190, 0, "No", "Europe/Copenhagen", "Mette Larsen (remote, from Amsterdam)"),
    ("FRA", "Frankfurt", "Germany", 350, 2, "Yes", "Europe/Berlin", "Lukas Becker"),
    ("GVA", "Geneva", "Switzerland", 210, 1, "Yes", "Europe/Zurich", "Nicolas Favre"),
    ("MIL", "Milan", "Italy", 180, 1, "Yes", "Europe/Rome", "Giulia Conti"),
    ("LIS", "Lisbon", "Portugal", 60, 0, "No", "Europe/Lisbon", "Inês Rocha (remote, from Madrid)"),
]
GOOD = {"rate": 0.40, "sla": {"P1": 0.95, "P2": 0.93, "P3": 0.93, "P4": 0.95}, "fcr": 0.75, "reo": 0.03, "esc": 0.12, "csat": 4.45,
        "stuck": 0.006, "carry": 0.008}
PROFILE = {
    "MAD": {"rate": 0.42},
    "PAR": {"rate": 0.46, "sla": {"P1": 0.92, "P2": 0.86, "P3": 0.87, "P4": 0.88}, "fcr": 0.71, "reo": 0.05, "esc": 0.14, "csat": 4.3,
            "stuck": 0.075, "carry": 0.03},
    "AMS": {},
    "CPH": {},
    "FRA": {"rate": 0.41},
    "GVA": {"rate": 0.37, "fcr": 0.78, "esc": 0.10},
    "MIL": {"fcr": 0.71, "esc": 0.14, "csat": 4.35},
    "LIS": {"rate": 0.15},
}
# Copenhagen lost its only local engineer at the end of September; everything goes through the central team since
CPH_OCTOBER = {"sla": {"P1": 0.85, "P2": 0.82, "P3": 0.85, "P4": 0.86}, "fcr": 0.48, "reo": 0.08, "esc": 0.40, "csat": 3.45}
PRIORITIES = [("P1", 0.02), ("P2", 0.10), ("P3", 0.55), ("P4", 0.33)]
BUILDS = {"24H2-sep": "10.0.26100.6584", "24H2": "10.0.26100.6899", "23H2": "10.0.22631.6060", "25H2": "10.0.26200.6899"}


def _w(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def _ts(x: datetime | None) -> str:
    return x.strftime("%Y-%m-%d %H:%M") if x else ""


def _yn(b: bool | None) -> str:
    return "" if b is None else "Yes" if b else "No"


def _profile(site: str, when: datetime) -> dict:
    p = {**GOOD, **PROFILE[site]}
    if site == "CPH" and when >= datetime(2026, 10, 1):
        p = {**p, **CPH_OCTOBER}
    return p


def _priority(rnd: random.Random) -> str:
    x, acc = rnd.random(), 0.0
    for p, w in PRIORITIES:
        acc += w
        if x < acc:
            return p
    return "P4"


def tickets(rnd: random.Random) -> list[list]:
    raw = []
    for code, *_rest in SITES:
        users = _rest[2]
        # carry-over: tickets opened in July and August still open on 1 September
        p0 = _profile(code, datetime(2026, 9, 1))
        for _ in range(round(users * p0["carry"])):
            opened = datetime(2026, 7, 1, 8) + timedelta(days=rnd.randint(0, 61), hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))
            raw.append((code, opened, True))
        start, days = datetime(2026, 9, 1, 8), 68
        p = _profile(code, start)
        for _ in range(round(users * p["rate"] * days / 30)):
            opened = start + timedelta(days=rnd.randint(0, days - 1), hours=rnd.randint(0, 9), minutes=rnd.randint(0, 59))
            raw.append((code, opened, False))
    raw.sort(key=lambda x: (x[1], x[0]))
    rows = []
    for n, (code, opened, carry) in enumerate(raw, start=4101):
        p = _profile(code, opened)
        pr = _priority(rnd)
        incident = rnd.random() < 0.56
        stuck = carry or rnd.random() < p["stuck"]
        if carry:
            first = datetime(2026, 9, 1, 9)
            resolved = None if rnd.random() < (0.6 if code == "PAR" else 0.15) else first + timedelta(days=rnd.randint(0, 45), hours=rnd.randint(0, 8))
        elif stuck:
            resolved = None if rnd.random() < 0.55 else opened + timedelta(days=rnd.randint(31, 75), hours=rnd.randint(0, 8))
        else:
            mean = {"P1": 0.2, "P2": 0.8, "P3": 2.5, "P4": 5.0}[pr] * (1 if incident else 1.6)
            resolved = opened + timedelta(hours=max(0.3, rnd.expovariate(1 / (mean * 24))))
        if resolved and resolved > EXPORT:
            resolved = None
        esc = rnd.random() < p["esc"]
        fcr = (not esc and rnd.random() < min(1.0, p["fcr"] / (1 - p["esc"]))) if incident and resolved else None
        sla = None if resolved is None else (False if stuck else rnd.random() < p["sla"][pr])
        reo = bool(resolved) and rnd.random() < p["reo"]
        csat = ""
        if resolved and rnd.random() < 0.3:
            csat = str(min(5, max(1, round(rnd.gauss(p["csat"] + (0 if sla else -0.6), 0.75)))))
        rows.append([f"ITSD-{n}", code, _ts(opened), _ts(resolved), pr, "Incident" if incident else "Service request", _yn(sla),
                     _yn(fcr), "1" if reo else "0", _yn(esc), csat])
    return rows


def outages(rnd: random.Random) -> list[list]:
    rows = []
    for code, *_ in SITES:
        for m0 in (date(2026, 9, 1), date(2026, 10, 1)):
            def at(day_max=29):
                return datetime.combine(m0 + timedelta(days=rnd.randint(0, day_max)), datetime.min.time()) + timedelta(
                    hours=rnd.randint(6, 20), minutes=rnd.choice([0, 10, 20, 30, 40, 50]))
            for _ in range(rnd.randint(0, 2)):
                rows.append([code, "Wi-Fi", at(), rnd.randint(5, 25), "No", "", "access point reboot"])
            for _ in range(rnd.randint(0, 2)):
                rows.append([code, "Printing", at(), rnd.randint(20, 120), "No", "", "print server queue stuck"])
            if rnd.random() < 0.5:
                rows.append([code, "Meeting rooms", at(), rnd.randint(30, 90), "No", "", "room controller offline"])
            if rnd.random() < 0.4:
                rows.append([code, "WAN primary", at(), rnd.randint(4, 18), "No", "", "brief loss of the primary circuit"])
            if rnd.random() < 0.4:
                rows.append([code, "File and print", at(), rnd.randint(5, 20), "No", "", "file server restart"])
            rows.append([code, rnd.choice(["Wi-Fi", "File and print", "Printing"]), at(), rnd.choice([60, 90, 120, 180]), "Yes",
                         f"CHG-{rnd.randint(2100, 2399)}", "maintenance window"])
    # planted: Frankfurt's backup circuit down twice in October; a planned primary circuit change; Madrid Wi-Fi blips
    rows += [["FRA", "WAN backup", datetime(2026, 10, 6, 14, 10), 290, "No", "NWT-48213", "fibre cut on the backup circuit (provider)"],
             ["FRA", "WAN backup", datetime(2026, 10, 21, 9, 40), 230, "No", "NWT-48377", "provider router fault on the backup circuit"],
             ["FRA", "WAN primary", datetime(2026, 10, 17, 22, 0), 240, "Yes", "CHG-2318", "planned circuit upgrade"],
             ["MAD", "Wi-Fi", datetime(2026, 10, 14, 11, 20), 75, "No", "", "controller failover after a firmware bug"],
             ["MAD", "Wi-Fi", datetime(2026, 10, 15, 9, 5), 55, "No", "", "controller failover after a firmware bug"]]
    rows.sort(key=lambda r: (r[2], r[0], r[1]))
    return [[r[0], r[1], _ts(r[2]), r[3], r[4], r[5], r[6]] for r in rows]


def devices(rnd: random.Random) -> list[list]:
    rows = []
    for code, *_rest in SITES:
        users = _rest[2]
        old_share = {"MIL": 0.21, "GVA": 0.13}.get(code, 0.09)
        stale_p = {"MIL": 0.05}.get(code, 0.012)
        for n in range(1, round(users * 1.02) + 1):
            name = f"{code}-L{n:04d}"
            age = round(rnd.uniform(4.1, 6.5) if rnd.random() < old_share else rnd.uniform(0.1, 3.9), 1)
            on23 = rnd.random() < 0.12
            to25 = code == "AMS" and not on23 and rnd.random() < 0.40
            for snap in SNAPSHOTS:
                oct_ = snap == SNAPSHOTS[1]
                build = BUILDS["23H2"] if on23 else BUILDS["25H2"] if (to25 and oct_) else BUILDS["24H2" if oct_ else "24H2-sep"]
                bad = rnd.random() < 0.022
                enc = True
                if to25 and oct_ and rnd.random() < 0.45:
                    bad = True
                    enc = rnd.random() < 0.2
                stale = rnd.random() < stale_p
                seen = snap - timedelta(days=rnd.randint(16, 70) if stale else rnd.randint(0, 6))
                rows.append([snap.isoformat(), name, code, "noncompliant" if bad else "compliant", build, "True" if enc else "False",
                             seen.isoformat(), round(age - (1 / 12 if not oct_ else 0), 1)])
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows


PROJECTS = [
    ["PRJ-101", "MAD", "Replace the meeting room displays on floor 3", "Carlos Ibáñez", "2026-10-16", "", "In progress"],
    ["PRJ-102", "MAD", "Second Wi-Fi controller firmware upgrade", "Jonas Weber", "2026-11-20", "", "Open"],
    ["PRJ-103", "PAR", "Move the print server to the new cluster", "Claire Dubois", "2026-09-26", "", "In progress"],
    ["PRJ-104", "PAR", "Clean up the requests queue older than 60 days", "Marta Vidal", "2026-10-09", "", "Open"],
    ["PRJ-105", "PAR", "Badge reader integration for the new floor", "Claire Dubois", "2026-10-23", "", "Blocked"],
    ["PRJ-106", "PAR", "UPS battery replacement in the comms room", "Claire Dubois", "2026-11-27", "", "Open"],
    ["PRJ-107", "AMS", "Windows 11 25H2 pilot ring for Amsterdam", "Sofie Jansen", "2026-10-02", "2026-10-02", "Done"],
    ["PRJ-108", "AMS", "Rack cable management in the comms room", "Daan de Vries", "2026-12-04", "", "Open"],
    ["PRJ-109", "CPH", "Hire a local IT engineer", "Laura Méndez", "2026-12-15", "", "In progress"],
    ["PRJ-110", "CPH", "Smart lockers for laptop swaps", "Mette Larsen", "2026-11-30", "", "Open"],
    ["PRJ-111", "FRA", "Diverse route for the backup circuit (quote from the provider)", "Jonas Weber", "2026-10-30", "", "Open"],
    ["PRJ-112", "FRA", "Replace the core switch fans", "Lukas Becker", "2026-10-09", "2026-10-08", "Done"],
    ["PRJ-113", "GVA", "Meeting room booking panels", "Nicolas Favre", "2026-11-13", "", "Open"],
    ["PRJ-114", "MIL", "Laptop refresh, first batch of 40", "Giulia Conti", "2026-12-11", "", "Open"],
    ["PRJ-115", "MIL", "Book the DR test with the business", "Paolo Ricci", "2026-11-20", "", "Open"],
    ["PRJ-116", "LIS", "Replace the office router", "Jonas Weber", "2026-10-16", "2026-10-14", "Done"],
]
DR_TESTS = [
    ["MAD", "2025-04-12", "Full site failover to Paris", "Pass", "DR-2025-03"],
    ["MAD", "2026-04-18", "Full site failover to Paris", "Pass", "DR-2026-02"],
    ["PAR", "2026-02-07", "Full site failover to Madrid", "Pass", "DR-2026-01"],
    ["AMS", "2026-05-23", "WAN failover and work from home", "Pass", "DR-2026-04"],
    ["CPH", "2026-03-14", "WAN failover and work from home", "Pass", "DR-2026-03"],
    ["FRA", "2026-06-13", "WAN failover and work from home", "Pass", "DR-2026-05"],
    ["GVA", "2026-01-24", "WAN failover and work from home", "Pass", "DR-2026-00"],
    ["MIL", "2025-06-14", "WAN failover and work from home", "Pass", "DR-2025-05"],
    ["LIS", "2025-11-29", "Work from home", "Pass", "DR-2025-09"],
]


def write(folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(SEED)
    _w(folder / "sites.csv", ["Site", "City", "Country", "Users", "LocalITStaff", "CommsRoom", "TimeZone", "SiteLead"], [list(s) for s in SITES])
    _w(folder / "tickets.csv", ["Key", "Site", "Created", "Resolved", "Priority", "Type", "SLAMet", "FCR", "Reopened", "Escalated",
                                "Satisfaction"], tickets(rnd))
    _w(folder / "availability.csv", ["Site", "Service", "Start", "MinutesDown", "Planned", "Reference", "Cause"], outages(rnd))
    _w(folder / "devices.csv", ["Snapshot", "DeviceName", "Site", "ComplianceState", "OSVersion", "IsEncrypted", "LastSyncDateTime",
                                "AgeYears"], devices(rnd))
    _w(folder / "projects.csv", ["Id", "Site", "Title", "Owner", "Due", "Closed", "Status"], PROJECTS)
    _w(folder / "dr_tests.csv", ["Site", "TestDate", "Scope", "Result", "Reference"], DR_TESTS)
    (folder / "settings.json").write_text(json.dumps(SETTINGS, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return folder


__all__ = ["write", "ORG", "SETTINGS"]
