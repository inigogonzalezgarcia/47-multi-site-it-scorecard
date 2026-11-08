import csv
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from sitescorecard import cli
from sitescorecard.checks import AMBER, GREEN, NA, RED, compute, review, run_all, summary
from sitescorecard.model import (Data, Device, DrTest, Outage, Project, Site, Ticket, load, load_devices, load_outages, load_sites,
                                 load_tickets, settings_from_dict)

AS_OF = datetime(2026, 11, 8, 9, 0)
OCT, SEP = "2026-10", "2026-09"


def write(path: Path, header: list[str], rows: list[list]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return path


def rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def site(code="MAD", users=200, staff=1) -> Site:
    return Site(code, code.title(), "Spain", users, staff, True, "Europe/Madrid", "Lead")


def ticket(n, day=10, month=10, site_="MAD", sla=True, fcr=True, incident=True, reopened=False, escalated=False, csat=None, open_=False,
           opened=None) -> Ticket:
    o = opened or datetime(2026, month, day, 9)
    return Ticket(f"SD-{n}", site_, o, None if open_ else o + timedelta(hours=5), "P3", incident, None if open_ else sla,
                  None if open_ or not incident else fcr, reopened, escalated, csat)


def data(sites=(), tickets=(), outages=(), devices=(), projects=(), dr=(), **raw) -> Data:
    d = Data(settings_from_dict(raw), AS_OF, raw.get("report_month", OCT), list(sites) or [site()], list(tickets), list(outages),
             list(devices), list(projects), list(dr))
    d.sources = {"sites.csv": len(d.sites), "tickets.csv": len(d.tickets)}
    for n, xs in (("availability.csv", outages), ("projects.csv", projects), ("dr_tests.csv", dr)):
        if xs:
            d.sources[n] = len(xs)
    return d


class TestLoading(unittest.TestCase):
    def test_sites_tickets_outages_and_devices_from_export_columns(self):
        with tempfile.TemporaryDirectory() as t:
            s = write(Path(t) / "sites.csv", ["Site", "City", "Users", "LocalITStaff", "CommsRoom"], [["mad", "Madrid", "480", "2", "Yes"]])
            tk = write(Path(t) / "tickets.csv", ["Issue key", "Location", "Created", "Resolved", "Priority", "Issue Type", "SLAMet", "FCR",
                                                 "Reopened", "Escalated", "Satisfaction"],
                       [["SD-1", "MAD", "2026-10-01T09:00:00.000+0200", "2026-10-01T11:00:00Z", "p2", "Service request", "Yes", "", "2", "No", "4"],
                        ["SD-2", "MAD", "01/10/2026 10:00", "", "P3", "Incident", "", "", "0", "Yes", "9"]])
            av = write(Path(t) / "availability.csv", ["Site", "Service", "Start", "MinutesDown", "Planned"],
                       [["MAD", "WAN backup", "2026-10-06 14:10", "290", "No"], ["MAD", "Wi-Fi", "2026-10-07 22:00", "60", "Maintenance"]])
            dv = write(Path(t) / "devices.csv", ["DeviceName", "Site", "ComplianceState", "OSVersion", "IsEncrypted", "LastSyncDateTime",
                                                 "PurchaseDate"],
                       [["MAD-L1", "MAD", "compliant", "10.0.26100.6899", "True", "2026-10-30T08:00:00Z", "2021-10-31"],
                        ["MAD-L2", "MAD", "inGracePeriod", "10.0.26200.6899", "False", "", ""]])
            sites = load_sites(s)
            tickets = load_tickets(tk)
            outages = load_outages(av)
            devs = load_devices(dv, date(2026, 10, 31))
        self.assertEqual((sites[0].code, sites[0].users, sites[0].staff, sites[0].comms_room), ("MAD", 480, 2, True))
        self.assertFalse(tickets[0].incident)
        self.assertTrue(tickets[0].reopened and tickets[0].sla)
        self.assertEqual(tickets[0].priority, "P2")
        self.assertIsNone(tickets[1].resolved)
        self.assertIsNone(tickets[1].csat)          # out of the 1-5 scale
        self.assertTrue(tickets[1].escalated)
        self.assertEqual([o.planned for o in outages], [False, True])
        self.assertTrue(devs[0].compliant)
        self.assertFalse(devs[1].compliant)         # in grace period is not compliant
        self.assertEqual(devs[0].snapshot, date(2026, 10, 31))
        self.assertEqual(devs[0].age, 5.0)


class TestKpis(unittest.TestCase):
    def test_sla_rag_and_priority_breakdown(self):
        ts = [ticket(i, sla=i >= 6) for i in range(30)]       # 24 of 30 = 80%: amber
        k = compute(data(tickets=ts), OCT, [site()])["SLA"]
        self.assertAlmostEqual(k.value, 0.8)
        self.assertEqual(k.status, AMBER)
        self.assertEqual(k.detail[0].item, "P3")
        self.assertIn("P3 80%", k.reason)
        k = compute(data(tickets=[ticket(i, sla=i >= 10) for i in range(30)]), OCT, [site()])["SLA"]
        self.assertEqual(k.status, RED)

    def test_minimum_volume_is_not_rated_not_green(self):
        d = data(tickets=[ticket(i) for i in range(9)])
        kp = compute(d, OCT, [site()])
        self.assertEqual(kp["SLA"].status, NA)
        self.assertIn("9 resolved tickets, under the minimum of 20", kp["SLA"].reason)
        f = [x for x in run_all(d) if x.code == "SLA"]
        self.assertEqual(f[0].severity, "info")

    def test_fcr_escalation_reopen_csat_and_no_local_staff(self):
        ts = [ticket(i, fcr=i < 10, escalated=i >= 20, reopened=i < 3, csat=3 if i < 12 else None) for i in range(30)]
        kp = compute(data(sites=[site(staff=0)], tickets=ts), OCT, [site(staff=0)])
        self.assertAlmostEqual(kp["FCR"].value, 10 / 30)
        self.assertEqual(kp["FCR"].status, RED)
        self.assertIn("no local IT staff", kp["FCR"].reason)
        self.assertAlmostEqual(kp["ESC"].value, 10 / 30)
        self.assertEqual(kp["REO"].status, GREEN if 3 / 30 <= 0.05 else AMBER)
        self.assertEqual((kp["CSAT"].value, kp["CSAT"].status), (3.0, RED))

    def test_backlog_and_ageing_at_month_end(self):
        old = [ticket(100 + i, opened=datetime(2026, 9, 1, 9), open_=True) for i in range(6)]
        new = [ticket(200 + i, day=28, open_=True) for i in range(10)]
        later = [ticket(300, opened=datetime(2026, 11, 2, 9), open_=True)]    # opened after the month: not in the backlog
        kp = compute(data(sites=[site(users=200)], tickets=old + new + later), OCT, [site(users=200)])
        self.assertAlmostEqual(kp["BKL"].value, 16 / 200 * 100)
        self.assertEqual(kp["BKL"].status, AMBER)
        self.assertAlmostEqual(kp["AGE"].value, 6 / 16)
        self.assertEqual(kp["AGE"].status, RED)
        self.assertIn("oldest SD-100", kp["AGE"].reason)
        self.assertEqual([x.numerator for x in kp["AGE"].detail], [10, 0, 6, 0])

    def test_availability_counts_unplanned_minutes_per_service(self):
        ev = [Outage("MAD", "WAN backup", datetime(2026, 10, 6, 14), 290, False, "NWT-1", "fibre cut"),
              Outage("MAD", "WAN backup", datetime(2026, 10, 21, 9), 230, False, "NWT-2", "router fault"),
              Outage("MAD", "WAN primary", datetime(2026, 10, 17, 22), 600, True, "CHG-1"),
              Outage("MAD", "Wi-Fi", datetime(2026, 9, 3, 9), 900, False)]
        k = compute(data(outages=ev), OCT, [site()])["AVL"]
        self.assertEqual((k.item, k.status), ("WAN backup", RED))
        self.assertAlmostEqual(k.value, 1 - 520 / 44640)
        self.assertIn("2 outages", k.reason)
        self.assertIn("NWT-1, NWT-2", k.reason)
        prim = next(x for x in k.detail if x.item == "WAN primary")
        self.assertEqual((prim.value, prim.status), (1.0, GREEN))       # planned minutes are not held against the target

    def test_device_compliance_build_stale_and_age(self):
        snap = date(2026, 10, 31)
        devs = [Device(f"D{i}", "MAD", snap, i >= 12, "", "10.0.26200.6899" if i < 15 else "10.0.26100.6899", i >= 8,
                       snap - timedelta(days=30 if i < 2 else 1), 5.0 if i < 6 else 2.0) for i in range(40)]
        devs += [Device(f"D{i}", "MAD", date(2026, 9, 30), True, "", "", True, date(2026, 9, 29), 2.0) for i in range(40)]
        kp = compute(data(devices=devs), OCT, [site()])
        self.assertAlmostEqual(kp["CMP"].value, 28 / 40)
        self.assertEqual(kp["CMP"].status, RED)
        self.assertIn("12 of the 12 noncompliant devices on OS build 10.0.26200.6899", kp["CMP"].reason)
        self.assertIn("8 report no encryption", kp["CMP"].reason)
        self.assertAlmostEqual(kp["STL"].value, 2 / 40)
        self.assertAlmostEqual(kp["HWA"].value, 6 / 40)
        self.assertEqual(compute(data(devices=devs), SEP, [site()])["CMP"].status, GREEN)

    def test_overdue_actions_and_dr_test_freshness(self):
        pj = [Project("A1", "MAD", "Old", "x", date(2026, 9, 30)), Project("A2", "MAD", "Closed late", "x", date(2026, 10, 1), date(2026, 11, 3)),
              Project("A3", "MAD", "Done", "x", date(2026, 10, 1), date(2026, 10, 20), True), Project("A4", "MAD", "Future", "x", date(2026, 11, 30))]
        dr = [DrTest("MAD", date(2025, 6, 14), "WAN failover", "Pass"), DrTest("PAR", date(2026, 4, 1), "Full", "Partial"),
              DrTest("GVA", date(2025, 12, 1), "Full", "Pass")]
        sites = [site(), site("PAR"), site("GVA"), site("LIS")]
        d = data(sites=sites, projects=pj, dr=dr)
        self.assertEqual(compute(d, OCT, [sites[0]])["ACT"].numerator, 2)            # A1 and A2 (closed after month end)
        self.assertEqual(compute(d, OCT, [sites[0]])["DRT"].status, RED)
        self.assertEqual(compute(d, OCT, [sites[1]])["DRT"].status, AMBER)           # partial result
        self.assertEqual(compute(d, OCT, [sites[2]])["DRT"].status, AMBER)           # due within 60 days
        self.assertIn("no DR test recorded", compute(d, OCT, [sites[3]])["DRT"].reason)

    def test_trend_score_and_site_status(self):
        ts = [ticket(i, month=9, csat=5) for i in range(30)] + [ticket(100 + i, csat=3, fcr=i < 25) for i in range(30)]
        d = data(tickets=ts)
        rv = review(d)
        r = rv["sites"][0]
        csat = r["kpis"]["CSAT"]
        self.assertEqual((csat.previous.value, csat.value, csat.trend, csat.better), (5.0, 3.0, "down", False))
        self.assertLess(r["score"], r["prev_score"])
        self.assertNotEqual(r["status"], GREEN)                                      # a red KPI never leaves a site green
        f = [x for x in run_all(d, rv) if x.code == "CSAT"][0]
        self.assertTrue(f.new)
        self.assertEqual(f.trend, "down, worse")

    def test_settings_override_targets_weights_and_month(self):
        d = data(tickets=[ticket(i, sla=i >= 6) for i in range(30)], targets={"SLA": {"target": 0.8, "red": 0.7}}, weights={"SLA": 50})
        self.assertEqual(compute(d, OCT, [site()])["SLA"].status, GREEN)
        self.assertEqual(d.settings.weights["SLA"], 50)
        self.assertEqual(d.settings.target("SLA")["min"], 20)                        # the default stays when not overridden
        d2 = data(tickets=[ticket(i, month=9) for i in range(25)], report_month=SEP)
        self.assertEqual(review(d2)["sites"][0]["kpis"]["SLA"].status, GREEN)


class TestRegion(unittest.TestCase):
    def test_region_pools_tickets_and_takes_the_worst_site_for_availability(self):
        a, b = site("AAA", users=300), site("BBB", users=100)
        ts = [ticket(i, site_="AAA") for i in range(30)] + [ticket(100 + i, site_="BBB", sla=i >= 15) for i in range(30)]
        ev = [Outage("BBB", "WAN backup", datetime(2026, 10, 6, 14), 600, False, "NWT-9")]
        rv = review(data(sites=[a, b], tickets=ts, outages=ev))
        reg = rv["region"]
        self.assertAlmostEqual(reg["kpis"]["SLA"].value, 45 / 60)
        self.assertEqual(reg["kpis"]["AVL"].status, RED)
        self.assertIn("Bbb", reg["kpis"]["AVL"].reason)
        sa, sb = rv["sites"][0]["score"], rv["sites"][1]["score"]
        self.assertAlmostEqual(reg["score"], (sa * 300 + sb * 100) / 400)
        self.assertEqual(reg["site"].users, 400)


class TestEndToEnd(unittest.TestCase):
    def test_demo_end_to_end_is_deterministic(self):
        with tempfile.TemporaryDirectory() as t:
            hashes = []
            for k in range(2):
                out = Path(t) / f"out{k}"
                self.assertEqual(cli.main(["demo", "--data", str(Path(t) / f"data{k}"), "--out", str(out)]), 0)
                self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(cli.OUTPUTS))
                h = {n: hashlib.sha1((out / n).read_bytes()).hexdigest() for n in cli.OUTPUTS}
                h.update({n.name: hashlib.sha1(n.read_bytes()).hexdigest() for n in (Path(t) / f"data{k}").iterdir()})
                hashes.append(h)
            self.assertEqual(hashes[0], hashes[1])
            self.assertEqual(json.loads((Path(t) / "data0" / "settings.json").read_text(encoding="utf-8"))["report_month"], OCT)
            self.assertLess(sum(p.stat().st_size for p in (Path(t) / "data0").iterdir()), 700_000)
            d = load(Path(t) / "data0")
        rv = review(d)
        f = run_all(d, rv)
        st = {r["site"].code: r for r in rv["sites"]}
        self.assertEqual((len(rv["sites"]), sum(s.users for s in d.sites)), (8, 2500))
        reds = {(x.site, x.code) for x in f if x.severity == "red"}
        for planted in (("FRA", "AVL"), ("AMS", "CMP"), ("CPH", "CSAT"), ("MIL", "DRT"), ("PAR", "AGE")):
            self.assertIn(planted, reds)
        self.assertEqual(st["LIS"]["kpis"]["SLA"].status, NA)
        self.assertEqual(st["FRA"]["kpis"]["AVL"].item, "WAN backup")
        self.assertIn("NWT-48213", st["FRA"]["kpis"]["AVL"].reason)
        self.assertIn("10.0.26200", st["AMS"]["kpis"]["CMP"].reason)
        self.assertEqual(st["AMS"]["kpis"]["CMP"].previous.status, GREEN)
        self.assertEqual(st["CPH"]["prev_status"], GREEN)
        self.assertEqual(st["CPH"]["status"], RED)
        self.assertEqual(rv["region"]["kpis"]["AVL"].status, RED)
        sm = summary(d, rv, f)
        self.assertEqual(sm["worst"]["site"].code, "CPH")

    def test_pack_and_csv_outputs(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["demo", "--data", str(Path(t) / "d"), "--out", str(Path(t) / "o")]), 0)
            o = Path(t) / "o"
            pack = (o / "regional-review-pack.md").read_text(encoding="utf-8")
            html = (o / "report.html").read_text(encoding="utf-8")
            sc = rows(o / "site-scorecard.csv")
            det = rows(o / "kpi-detail.csv")
            tr = rows(o / "trend.csv")
            act = rows(o / "actions.csv")
            fd = rows(o / "findings.csv")
        for h in ("## Decisions per site", "## Headlines", "## Regional heatmap", "## 1. Amsterdam (AMS)", "## 8. Paris (PAR)", "## Actions",
                  "## Sign-off"):
            self.assertIn(h, pack)
        self.assertEqual([r["site"] for r in sc][-1], "REGION")
        self.assertEqual(len(sc), 9)
        self.assertTrue(any(r["level"] == "detail" and r["item"] == "WAN backup" and r["site"] == "FRA" for r in det))
        self.assertEqual({r["month"] for r in tr}, {SEP, OCT})
        self.assertTrue(all(a["decision"] == "" and a["due"] == "2026-12-10" for a in act))
        self.assertEqual(fd[0]["severity"], "red")
        self.assertIn("Regional heatmap", html)
        self.assertNotIn("\r", pack)

    def test_review_reports_missing_files(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)
            self.assertEqual(cli.main(["review", "--out", str(Path(t) / "o")]), 2)
            write(Path(t) / "sites.csv", ["Site", "Users"], [["MAD", "100"]])
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o")]), 2)          # no tickets.csv
            write(Path(t) / "tickets.csv", ["Key", "Site", "Created", "Resolved", "SLAMet"], [["SD-1", "MAD", "2026-10-02 09:00", "2026-10-02 10:00", "Yes"]])
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o"), "--month", "2026-13x"]), 2)
            self.assertEqual(cli.main(["review", t, "--out", str(Path(t) / "o"), "--as-of", "2026-11-08"]), 0)
            sc = rows(Path(t) / "o" / "site-scorecard.csv")
        self.assertEqual(sc[0]["sla_status"], "n/a")
        self.assertEqual(sc[0]["avl_status"], "n/a")
        self.assertEqual(sc[0]["status"], "n/a")        # under min_coverage of the weights rated: no site status


if __name__ == "__main__":
    unittest.main()
