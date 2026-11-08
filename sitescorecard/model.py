"""Loading: the sites with their users and local IT staff; the ITSM ticket export (Jira Service Management or any tool with the same
columns); the outage events from monitoring (Zabbix, SolarWinds or similar); the Intune or MECM device exports, one snapshot per month;
and, optionally, the open projects and actions per site and the DR/BCP tests. Forgiving column names, into plain dataclasses."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

SITE_ALIASES = {
    "code": ["Site", "SiteCode", "site code", "code", "office"],
    "city": ["City", "town"],
    "country": ["Country"],
    "users": ["Users", "user count", "headcount", "people"],
    "staff": ["LocalITStaff", "local it staff", "it staff", "local engineers", "engineers"],
    "comms_room": ["CommsRoom", "comms room", "server room", "communications room"],
    "timezone": ["TimeZone", "time zone", "tz"],
    "lead": ["SiteLead", "site lead", "it lead", "site owner"],
}
TICKET_ALIASES = {
    "key": ["Key", "Issue key", "ticket", "number", "id"],
    "site": ["Site", "Location", "site code", "office"],
    "opened": ["Created", "Opened", "opened at", "created at"],
    "resolved": ["Resolved", "Resolution date", "resolved at", "closed"],
    "priority": ["Priority"],
    "type": ["Type", "Issue Type", "ticket type", "category"],
    "sla": ["SLAMet", "sla met", "within sla", "sla"],
    "fcr": ["FCR", "first contact resolution", "resolved at first contact"],
    "reopened": ["Reopened", "reopen count", "reopens"],
    "escalated": ["Escalated", "escalated to central", "escalated to central team", "escalated to l2"],
    "csat": ["Satisfaction", "CSAT", "satisfaction score", "rating"],
}
OUTAGE_ALIASES = {
    "site": ["Site", "Location", "host group", "site code"],
    "service": ["Service", "check", "item", "component"],
    "start": ["Start", "Started", "event start", "problem start", "time"],
    "minutes": ["MinutesDown", "minutes down", "duration minutes", "duration", "minutes"],
    "planned": ["Planned", "maintenance", "planned outage", "in maintenance"],
    "reference": ["Reference", "provider ticket", "ticket", "ref"],
    "cause": ["Cause", "notes", "note", "description"],
}
DEVICE_ALIASES = {
    "snapshot": ["Snapshot", "export date", "as of", "snapshot date"],
    "device": ["DeviceName", "Device", "device name", "name"],
    "site": ["Site", "Location", "site code", "office"],
    "compliance": ["ComplianceState", "compliance state", "compliant", "compliance"],
    "os": ["OSVersion", "OsVersion", "os build", "os version", "build"],
    "encrypted": ["IsEncrypted", "encrypted", "encryption", "bitlocker"],
    "checkin": ["LastSyncDateTime", "last sync", "last check-in", "last checkin", "last contact"],
    "age": ["AgeYears", "age years", "age"],
    "purchased": ["PurchaseDate", "purchase date", "in service", "warranty start"],
}
PROJECT_ALIASES = {
    "id": ["Id", "Key", "ref", "reference"],
    "site": ["Site", "Location", "site code"],
    "title": ["Title", "Summary", "action", "name"],
    "owner": ["Owner", "Assignee"],
    "due": ["Due", "Due date", "due date", "target date"],
    "closed": ["Closed", "Done", "Resolved", "closed date", "completed"],
    "status": ["Status", "state"],
}
DR_ALIASES = {
    "site": ["Site", "Location", "site code"],
    "date": ["TestDate", "test date", "date", "last test"],
    "scope": ["Scope", "test", "type"],
    "result": ["Result", "outcome", "status"],
    "reference": ["Reference", "report", "ref"],
}
YES = {"yes", "y", "true", "1", "on", "si", "compliant", "encrypted", "met", "planned", "maintenance"}
DONE = {"done", "closed", "resolved", "complete", "completed", "cancelled", "canceled"}
DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M", "%m/%d/%Y")
DEFAULT_OWNERS = {"service desk": "Service desk lead", "network": "Network and connectivity lead", "workplace": "Workplace (Intune) lead",
                  "site": "Site IT lead", "bcp": "BCP coordinator"}
# code: target (green at or better), red (red when worse), min (minimum volume to rate)
DEFAULT_TARGETS = {
    "SLA": {"target": 0.90, "red": 0.80, "min": 20},
    "FCR": {"target": 0.70, "red": 0.60, "min": 15},
    "REO": {"target": 0.05, "red": 0.10, "min": 20},
    "ESC": {"target": 0.15, "red": 0.25, "min": 20},
    "BKL": {"target": 7.0, "red": 10.0, "min": 0},
    "AGE": {"target": 0.15, "red": 0.25, "min": 10},
    "CSAT": {"target": 4.2, "red": 3.8, "min": 10},
    "CMP": {"target": 0.95, "red": 0.90, "min": 20},
    "STL": {"target": 0.03, "red": 0.08, "min": 20},
    "HWA": {"target": 0.15, "red": 0.25, "min": 20},
    "ACT": {"target": 0, "red": 2, "min": 0},
    "DRT": {"target": 12, "red": 12, "min": 0},
}
DEFAULT_AVAILABILITY = {"WAN primary": 0.999, "WAN backup": 0.995, "Wi-Fi": 0.998, "Printing": 0.99, "Meeting rooms": 0.99,
                        "File and print": 0.998}
DEFAULT_WEIGHTS = {"SLA": 15, "FCR": 8, "REO": 5, "ESC": 5, "BKL": 8, "AGE": 8, "CSAT": 12, "AVL": 15, "CMP": 10, "STL": 4, "HWA": 4,
                   "ACT": 3, "DRT": 3}


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in s if not unicodedata.combining(ch))).strip()


def parse_dt(v) -> datetime | None:
    s = str(v or "").strip()
    if not s or _norm(s) in {"n a", "na", "none", "null", "never"}:
        return None
    s = re.sub(r"(\.\d+)?(Z|[+-]\d{2}:?\d{2})$", "", s)
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def parse_d(v) -> date | None:
    x = parse_dt(v)
    return x.date() if x else None


def tri(v) -> bool | None:
    """yes / no / unknown (empty)."""
    n = _norm(v)
    if not n:
        return None
    return n in YES


def num(v) -> float | None:
    s = str(v or "").strip().replace("%", "").replace(" ", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _read(path: Path) -> tuple[list[str], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = fh.readline()
        fh.seek(0)
        delim = max(",;\t", key=header.count)
        reader = csv.DictReader(fh, delimiter=delim)
        return list(reader.fieldnames or []), list(reader)


def _map(fields: list[str], aliases: dict[str, list[str]]) -> dict[str, str]:
    heads = {_norm(h): h for h in fields}
    cols = {}
    for k, names in aliases.items():
        for n in names + [k.replace("_", " ")]:
            if _norm(n) in heads and heads[_norm(n)] not in cols.values():
                cols[k] = heads[_norm(n)]
                break
    return cols


def _rows(path: Path, aliases: dict[str, list[str]]) -> list[dict]:
    fields, raw = _read(path)
    cols = _map(fields, aliases)
    return [{k: (r.get(c) or "").strip() for k, c in cols.items()} for r in raw]


def _site(v) -> str:
    return str(v or "").strip().upper()


# ---------------------------------------------------------------- months

def month_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_start(m: str) -> date:
    y, mo = (int(x) for x in m.split("-"))
    return date(y, mo, 1)


def month_end(m: str) -> date:
    s = month_start(m)
    return (s.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def previous_month(m: str) -> str:
    return month_of(month_start(m) - timedelta(days=1))


def month_minutes(m: str) -> int:
    return ((month_end(m) - month_start(m)).days + 1) * 24 * 60


def month_label(m: str) -> str:
    return f"{month_start(m):%B %Y}"


# ---------------------------------------------------------------- records

@dataclass
class Site:
    code: str
    city: str = ""
    country: str = ""
    users: int = 0
    staff: int | None = None
    comms_room: bool | None = None
    timezone: str = ""
    lead: str = ""

    @property
    def name(self) -> str:
        return self.city or self.code


@dataclass
class Ticket:
    key: str
    site: str
    opened: datetime
    resolved: datetime | None = None
    priority: str = ""
    incident: bool = True
    sla: bool | None = None
    fcr: bool | None = None
    reopened: bool = False
    escalated: bool = False
    csat: float | None = None


@dataclass
class Outage:
    site: str
    service: str
    start: datetime
    minutes: float
    planned: bool = False
    reference: str = ""
    cause: str = ""


@dataclass
class Device:
    device: str
    site: str
    snapshot: date | None = None
    compliant: bool = False
    state: str = ""
    os: str = ""
    encrypted: bool | None = None
    checkin: date | None = None
    age: float | None = None


@dataclass
class Project:
    id: str
    site: str
    title: str = ""
    owner: str = ""
    due: date | None = None
    closed: date | None = None
    done: bool = False


@dataclass
class DrTest:
    site: str
    day: date
    scope: str = ""
    result: str = ""
    reference: str = ""


@dataclass
class Settings:
    organisation: str = "Multi-site IT scorecard"
    as_of: datetime | None = None
    report_month: str = ""
    targets: dict = field(default_factory=lambda: {k: dict(v) for k, v in DEFAULT_TARGETS.items()})
    availability_targets: dict = field(default_factory=lambda: dict(DEFAULT_AVAILABILITY))
    availability_red_margin: float = 0.005
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    score_green: float = 85.0
    score_amber: float = 70.0
    min_coverage: float = 0.4
    ageing_days: int = 30
    stale_days: int = 14
    hardware_years: float = 4.0
    dr_months: int = 12
    dr_warning_days: int = 60
    next_review: str = ""
    owners: dict = field(default_factory=lambda: dict(DEFAULT_OWNERS))

    def owner(self, area: str) -> str:
        return self.owners.get(area) or DEFAULT_OWNERS.get(area, "Regional IT lead")

    def target(self, code: str) -> dict:
        return {**DEFAULT_TARGETS.get(code, {}), **self.targets.get(code, {})}


def settings_from_dict(raw: dict) -> Settings:
    s = Settings()
    for k, v in raw.items():
        if not hasattr(s, k) or v is None:
            continue
        cur = getattr(s, k)
        if k == "as_of":
            s.as_of = parse_dt(v)
        elif k == "targets":
            for code, t in v.items():
                s.targets.setdefault(str(code).upper(), {}).update({a: float(num(b) or 0) for a, b in t.items()})
        elif k == "availability_targets":
            s.availability_targets = {str(a): float(num(b) or 0) for a, b in v.items()}
        elif k == "weights":
            s.weights.update({str(a).upper(): float(num(b) or 0) for a, b in v.items()})
        elif isinstance(cur, dict):
            cur.update({str(a): b for a, b in v.items()})
        elif isinstance(cur, bool):
            setattr(s, k, bool(v))
        elif isinstance(cur, int):
            setattr(s, k, int(num(v) or 0))
        elif isinstance(cur, float):
            setattr(s, k, float(num(v) or 0))
        else:
            setattr(s, k, str(v))
    return s


@dataclass
class Data:
    settings: Settings
    as_of: datetime
    month: str
    sites: list[Site] = field(default_factory=list)
    tickets: list[Ticket] = field(default_factory=list)
    outages: list[Outage] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    dr_tests: list[DrTest] = field(default_factory=list)
    sources: dict = field(default_factory=dict)

    @property
    def today(self) -> date:
        return self.as_of.date()

    @property
    def previous(self) -> str:
        return previous_month(self.month)


# ---------------------------------------------------------------- loaders

def load_sites(path: Path) -> list[Site]:
    out = []
    for r in _rows(path, SITE_ALIASES):
        if not r.get("code"):
            continue
        staff = num(r.get("staff"))
        out.append(Site(_site(r["code"]), r.get("city", ""), r.get("country", ""), int(num(r.get("users")) or 0),
                        None if staff is None else int(staff), tri(r.get("comms_room")), r.get("timezone", ""), r.get("lead", "")))
    return sorted(out, key=lambda s: s.code)


def load_tickets(path: Path) -> list[Ticket]:
    out = []
    for r in _rows(path, TICKET_ALIASES):
        opened = parse_dt(r.get("opened"))
        if not r.get("key") or not opened:
            continue
        reo = r.get("reopened", "")
        reopened = (num(reo) or 0) > 0 if num(reo) is not None else bool(tri(reo))
        csat = num(r.get("csat"))
        out.append(Ticket(r["key"], _site(r.get("site")), opened, parse_dt(r.get("resolved")), r.get("priority", "").upper(),
                          not ({"request", "sr", "req"} & set(_norm(r.get("type")).split())), tri(r.get("sla")), tri(r.get("fcr")),
                          reopened, bool(tri(r.get("escalated"))), csat if csat and 1 <= csat <= 5 else None))
    return out


def load_outages(path: Path) -> list[Outage]:
    out = []
    for r in _rows(path, OUTAGE_ALIASES):
        st = parse_dt(r.get("start"))
        if not st or not r.get("site") or not r.get("service"):
            continue
        out.append(Outage(_site(r["site"]), r["service"], st, float(num(r.get("minutes")) or 0), bool(tri(r.get("planned"))),
                          r.get("reference", ""), r.get("cause", "")))
    return out


def load_devices(path: Path, default_snapshot: date | None = None) -> list[Device]:
    out = []
    for r in _rows(path, DEVICE_ALIASES):
        if not r.get("device"):
            continue
        snap = parse_d(r.get("snapshot")) or default_snapshot
        age = num(r.get("age"))
        bought = parse_d(r.get("purchased"))
        if age is None and bought and snap:
            age = round((snap - bought).days / 365.25, 1)
        state = r.get("compliance", "")
        out.append(Device(r["device"], _site(r.get("site")), snap, _norm(state) in {"compliant", "yes", "true", "1"}, state, r.get("os", ""),
                          tri(r.get("encrypted")), parse_d(r.get("checkin")), age))
    return out


def load_projects(path: Path) -> list[Project]:
    out = []
    for r in _rows(path, PROJECT_ALIASES):
        if not r.get("id") or not r.get("site"):
            continue
        closed = parse_d(r.get("closed"))
        out.append(Project(r["id"], _site(r["site"]), r.get("title", ""), r.get("owner", ""), parse_d(r.get("due")), closed,
                           bool(closed) or _norm(r.get("status")) in DONE))
    return out


def load_dr(path: Path) -> list[DrTest]:
    return [DrTest(_site(r["site"]), parse_d(r["date"]), r.get("scope", ""), r.get("result", ""), r.get("reference", ""))
            for r in _rows(path, DR_ALIASES) if r.get("site") and parse_d(r.get("date"))]


FILES = {
    "sites.csv": "Sites with users, local IT staff, comms room and time zone",
    "tickets.csv": "ITSM ticket export (Jira Service Management or similar), one row per ticket",
    "availability.csv": "Outage events per site and service from monitoring (Zabbix, SolarWinds or similar)",
    "devices.csv": "Intune or MECM managed devices, one snapshot per month",
    "projects.csv": "Open projects and actions per site with due dates (optional)",
    "dr_tests.csv": "DR/BCP tests per site (optional)",
}


def _find(folder: Path, name: str) -> Path | None:
    p = folder / name
    if p.exists():
        return p
    stem = name.rsplit(".", 1)[0]
    alts = sorted(folder.glob(f"{stem}*.csv"))
    return alts[0] if alts else None


def load(folder: Path, as_of: datetime | None = None, month: str | None = None) -> Data:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"no folder {folder}")
    sp = folder / "settings.json"
    s = settings_from_dict(json.loads(sp.read_text(encoding="utf-8"))) if sp.exists() else Settings()
    when = as_of or s.as_of or datetime.now().replace(second=0, microsecond=0)
    m = month or s.report_month or previous_month(month_of(when.date()))
    if not re.fullmatch(r"\d{4}-\d{2}", m):
        raise ValueError(f"report month must be YYYY-MM: {m}")
    paths = {n: _find(folder, n) for n in FILES}
    for need in ("sites.csv", "tickets.csv"):
        if not paths[need]:
            raise FileNotFoundError(f"{folder}: need {need} ({FILES[need]})")
    d = Data(s, when, m)
    d.sites = load_sites(paths["sites.csv"])
    if not d.sites:
        raise ValueError(f"{paths['sites.csv']}: no sites (check the Site column)")
    d.tickets = load_tickets(paths["tickets.csv"])
    loaders = {"availability.csv": ("outages", load_outages), "devices.csv": ("devices", lambda p: load_devices(p, month_end(m))),
               "projects.csv": ("projects", load_projects), "dr_tests.csv": ("dr_tests", load_dr)}
    for n, (attr, fn) in loaders.items():
        if paths[n]:
            setattr(d, attr, fn(paths[n]))
    d.sources = {"sites.csv": len(d.sites), "tickets.csv": len(d.tickets)}
    d.sources.update({n: len(getattr(d, attr)) for n, (attr, _) in loaders.items() if paths[n]})
    return d


__all__ = ["Data", "Settings", "Site", "Ticket", "Outage", "Device", "Project", "DrTest", "load", "load_sites", "load_tickets",
           "load_outages", "load_devices", "load_projects", "load_dr", "settings_from_dict", "month_start", "month_end", "previous_month",
           "month_minutes", "month_label", "FILES"]
