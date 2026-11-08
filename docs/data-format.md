# Data format

Put the files in one folder and run `python -m sitescorecard review <folder>`. `sites.csv` and `tickets.csv` are required; every other file adds its KPIs, and a KPI without its file is *n/a*. Comma, semicolon or tab separated, UTF-8. Column names are matched loosely (case, accents and punctuation are ignored), and the alternatives below are accepted. Dates as ISO 8601 (`2026-10-06 14:10` or `2026-10-06T14:10:00Z`), `dd/mm/yyyy` or `MM/dd/yyyy`; the time zone suffix is ignored. Yes/no columns accept `Yes`, `True`, `1`. Site codes are compared in upper case and must be the same in every file.

`scripts/Export-SiteScorecardData.ps1` writes `devices.csv` (Microsoft Graph, Intune) and `tickets.csv` (Jira Service Management). `availability.csv` comes from the monitoring tool's own report; `sites.csv`, `projects.csv` and `dr_tests.csv` are kept by hand or exported from your tracker.

## How the scorecard works

| Step | Rule |
|---|---|
| Month | `report_month` in `settings.json` (or `--month`), by default the month before the reference date; the previous month is the comparison |
| RAG | Green at or better than `target`, red worse than `red`, amber in between. For KPIs where lower is better (reopen, escalation, backlog, ageing, stale, hardware age, overdue, DR test) the comparison is reversed |
| Minimum volume | A KPI with fewer records than its `min` (resolved tickets for SLA, incidents for FCR, responses for CSAT, open tickets for ageing, devices) is *n/a*: not rated, never green |
| Trend | The same KPI for the previous month: up, down or same, and better or worse by the direction of the KPI. DR test age has no trend |
| Site score | Points per rated KPI (green 100, amber 50, red 0) weighted by `weights`, over the weights of the rated KPIs only |
| Site status | Green from `score_green`, amber from `score_amber`, red below; a site with a red KPI is never green; a site whose rated KPIs carry less than `min_coverage` of the weights has no status (*n/a*) |
| Region | Ticket and device KPIs on the pooled data of all sites; availability shows the worst site; overdue actions and DR tests take the status of the worst site; the score is the average of the site scores weighted by users |
| Reasons | Every KPI that is not green says why, from the data: priorities under target, the OS build behind the noncompliant devices, the outages with their references and causes, the oldest tickets, the overdue actions, the last DR test, and whether the site has no local IT staff |

## sites.csv

| Column | Alternatives | Notes |
|---|---|---|
| Site | SiteCode, code, office | Required; the code used in every other file (`MAD`, `PAR`) |
| City | town | Shown as the site name |
| Country | | |
| Users | user count, headcount | Required for backlog per 100 users and the regional weights |
| LocalITStaff | local it staff, local engineers | `0` adds "no local IT staff at the site" to FCR, escalation and CSAT reasons |
| CommsRoom | comms room, server room | Yes or No |
| TimeZone | time zone | Informational |
| SiteLead | site lead, it lead | Named next to the owner of each finding |

## tickets.csv

One row per ticket, as exported from Jira Service Management (`GET /rest/api/3/search/jql`) or any ITSM tool with the same information. Include tickets created or resolved since the first day of the previous month, and every ticket still open (for the backlog and its ageing).

| Column | Alternatives | Notes |
|---|---|---|
| Key | Issue key, ticket, number | Required |
| Site | Location, office | The site code |
| Created | Opened | Required |
| Resolved | Resolution date, closed | Empty while open; a ticket is in the backlog at month end when created before and resolved after (or not at all) |
| Priority | | `P1`…`P4` or your names (`Highest`, `High`…); SLA is broken down by this value |
| Type | Issue Type | Anything containing *request* (`Service request`, `[System] Service request`) is a request; the rest are incidents. FCR is measured on incidents only |
| SLAMet | sla met, within sla | Yes/No for resolved tickets; in JSM, No when a completed or ongoing cycle of the SLA you report (usually *Time to resolution*) is breached |
| FCR | first contact resolution | Yes/No, resolved incidents only |
| Reopened | reopen count | A number (more than 0 is reopened) or Yes/No |
| Escalated | escalated to central team | Yes when the site's first line handed the ticket to the central team |
| Satisfaction | CSAT, rating | 1 to 5; empty when the user did not answer; other values are ignored |

## availability.csv

One row per outage or maintenance event, from the monitoring tool (Zabbix *Reports > Availability report* or the problem history, SolarWinds event or availability reports, PRTG). Only events that start in the month count for it.

| Column | Alternatives | Notes |
|---|---|---|
| Site | Location, host group | Required |
| Service | check, item | Required. The services in `availability_targets` (`WAN primary`, `WAN backup`, `Wi-Fi`, `Printing`, `Meeting rooms`, `File and print`); others are rated against 99.5% |
| Start | Started, problem start | Required |
| MinutesDown | duration minutes, duration | Minutes the service was down |
| Planned | maintenance | Yes for planned maintenance: listed in the reason, not held against the target |
| Reference | provider ticket, ticket | Provider or change ticket, quoted in the reason |
| Cause | notes, description | Short cause, quoted in the reason |

Availability per service = 1 − unplanned minutes ÷ minutes in the month (24×7). The KPI of a site is its worst service against that service's target; `red` is the target minus `availability_red_margin`.

## devices.csv

One row per managed device and snapshot, from Intune (`Get-MgDeviceManagementManagedDevice`) or a MECM report. Keep one snapshot per month in the same file (the exporter's `-Append`): the scorecard uses the last snapshot inside the report month and the last one inside the previous month. Without a Snapshot column, every row counts as a snapshot at the end of the report month.

| Column | Alternatives | Notes |
|---|---|---|
| Snapshot | export date | Date of the export |
| DeviceName | Device | Required |
| Site | Location | The site code |
| ComplianceState | compliance state | Intune `complianceState`: only `compliant` counts as compliant (`noncompliant`, `inGracePeriod`, `conflict`, `error`, `unknown` do not) |
| OSVersion | os build | `10.0.26100.6899`; the reason names the build behind most noncompliant devices |
| IsEncrypted | encryption, bitlocker | True/False; the reason counts noncompliant devices without encryption |
| LastSyncDateTime | last check-in | Stale when older than `stale_days` before the snapshot |
| AgeYears | age | Hardware age in years |
| PurchaseDate | in service | Used for the age when AgeYears is missing |

## projects.csv (optional)

| Column | Alternatives | Notes |
|---|---|---|
| Id | Key, ref | Required |
| Site | | Required |
| Title | Summary, action | |
| Owner | Assignee | |
| Due | Due date, target date | |
| Closed | Done, Resolved | Date closed; an action closed after the month end was still open at month end |
| Status | state | `Done`, `Closed`, `Cancelled` without a Closed date count as done |

Overdue = open at the month end with a due date before it.

## dr_tests.csv (optional)

| Column | Alternatives | Notes |
|---|---|---|
| Site | | Required |
| TestDate | test date, last test | Required; the latest test on or before the month end counts |
| Scope | test, type | Full failover, WAN failover, work from home… |
| Result | outcome | `Pass`, `Partial` (amber) or `Fail` (red) |
| Reference | report | The test report |

Red when the last test is older than `dr_months` or failed, or there is none; amber when partial or due within `dr_warning_days`.

## settings.json

| Key | Default | Meaning |
|---|---|---|
| organisation | | Shown in the title |
| as_of | now | Reference date (`2026-11-08 09:00`); fixes the outputs |
| report_month | month before `as_of` | `YYYY-MM` |
| targets | see below | Per KPI: `target`, `red` and `min` |
| availability_targets | WAN primary 0.999, WAN backup 0.995, Wi-Fi 0.998, Printing 0.99, Meeting rooms 0.99, File and print 0.998 | Per service |
| availability_red_margin | 0.005 | Red below target minus this |
| weights | SLA 15, AVL 15, CSAT 12, CMP 10, FCR 8, BKL 8, AGE 8, REO 5, ESC 5, STL 4, HWA 4, ACT 3, DRT 3 | Weights of the site score |
| score_green, score_amber | 85, 70 | Site status from the score |
| min_coverage | 0.4 | Share of the weights that must be rated for a site status |
| ageing_days | 30 | Open tickets older than this are *ageing* |
| stale_days | 14 | Days without check-in for a stale device |
| hardware_years | 4 | Devices older than this |
| dr_months, dr_warning_days | 12, 60 | DR test freshness |
| next_review | | Due date written on the actions |
| owners | | `service desk`, `network`, `workplace`, `site`, `bcp` |

Default targets:

| KPI | Code | Target | Red | Minimum |
|---|---|---|---|---|
| SLA attainment | SLA | ≥ 90% | < 80% | 20 resolved tickets |
| First-contact resolution | FCR | ≥ 70% | < 60% | 15 resolved incidents |
| Reopen rate | REO | ≤ 5% | > 10% | 20 resolved tickets |
| Escalated to the central team | ESC | ≤ 15% | > 25% | 20 resolved tickets |
| Backlog per 100 users | BKL | ≤ 7 | > 10 | |
| Backlog older than `ageing_days` | AGE | ≤ 15% | > 25% | 10 open tickets |
| Satisfaction | CSAT | ≥ 4.2 | < 3.8 | 10 responses |
| Unplanned availability (worst service) | AVL | per service | target − margin | |
| Device compliance | CMP | ≥ 95% | < 90% | 20 devices |
| Stale check-ins | STL | ≤ 3% | > 8% | 20 devices |
| Devices older than `hardware_years` | HWA | ≤ 15% | > 25% | 20 devices |
| Overdue actions | ACT | 0 | > 2 | |
| Months since the last DR test | DRT | ≤ 12 | > 12 | |

## Outputs

| File | Columns |
|---|---|
| `site-scorecard.csv` | month, site, city, country, users, local IT staff, score, previous score, status, previous status, counts of red, amber, green and not rated, proposal, then value and status per KPI; the last row is the region |
| `kpi-detail.csv` | One row per site and KPI (`level` kpi) and per sub-item (`level` detail: SLA per priority, availability per service, ageing buckets) with value, numerator, denominator, target, red threshold, status, previous value and status, trend, weight and reason |
| `trend.csv` | month, site, kpi, value, status for both months, plus the score; append it month after month for a longer history |
| `findings.csv` | Every red, amber and not-rated KPI with value, target, previous, trend, whether the red is new, reason, next step and owner |
| `actions.csv` | Reds, and ambers getting worse, with owner, due (`next_review`) and empty decision and done columns |
