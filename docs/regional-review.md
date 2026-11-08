# Regional review

How to run the scorecard every month and use it in the regional review. The tool only reads exports; the fixes are made by the site leads, the service desk, the network, workplace and BCP owners through the usual processes.

## Who does what

| Role | In the review |
|---|---|
| Regional IT lead | Runs the exports and the scorecard, chairs the review, owns the targets and the weights, follows the actions |
| Site IT leads | Explain their reds and ambers, bring the recovery plan, own the site actions |
| Service desk lead | SLA, FCR, reopen, escalation, backlog, ageing and CSAT; queue rules and capacity |
| Network lead | Availability: outages, provider tickets, RFOs, service credits, failover tests |
| Workplace (Intune) lead | Compliance, stale devices, ageing hardware and the refresh plan |
| BCP coordinator | DR/BCP test calendar and results |

## The monthly cycle

| When | What | Output |
|---|---|---|
| First working day | Export devices and tickets (`scripts/Export-SiteScorecardData.ps1 -Append`), the outage report from monitoring, the actions and the DR register | `data/` |
| Same day | Run the scorecard for the month that just closed | `output/` |
| Day 2 | Send each site lead their section of the pack; they add the context and the plan for each red | `regional-review-pack.md` |
| Day 3 to 5 | Regional review, 60 minutes (below) | decisions, owners, dates |
| After the review | Actions in the tracker with the reference `YYYY-MM-SITE-KPI`; append `trend.csv` to the history | `actions.csv`, `trend.csv` |

```powershell
.\scripts\Export-SiteScorecardData.ps1 -OutputFolder .\data -SiteFromDeviceName -Append `
    -JiraSite https://contoso.atlassian.net -Project ITSD -SiteField customfield_10120 -SlaField customfield_10030 -SatisfactionField customfield_10031
```

```bash
python -m sitescorecard review data/ --month 2026-10
```

## Agenda (60 minutes)

| Minutes | Topic | From the pack | Who |
|---|---|---|---|
| 5 | Regional score, sites by status, what changed | Decisions per site, Headlines | Regional IT lead |
| 10 | Heatmap: patterns across sites (one KPI amber everywhere is a target or process question, not a site question) | Regional heatmap | All |
| 30 | Red sites first, then amber: reasons and recovery plan | One section per site | Site leads with the owners |
| 10 | Not rated: read the few tickets of the small sites | Findings marked n/a | Service desk lead |
| 5 | Decisions, owners, dates; anything for the steering group | Actions | Regional IT lead |

## How to read RAG and trends

- **Green** meets the target, **amber** is between the target and the red threshold, **red** is past the red threshold. **n/a** is not green: there is no data or too little to rate (SLA on nine tickets says nothing; read the nine tickets).
- **The arrow** compares with the previous month. A green KPI with a worse arrow two months in a row is the early warning; an amber that improves may need nothing.
- **New red** means it was not red last month. A red that is not new needs a different conversation: why did last month's plan not work?
- **The score** summarises; the reds decide. A site with a red is never green, whatever its score.
- **The region** pools tickets and devices, shows the worst site for availability and the worst status for actions and DR tests, so one site's outage or overdue test is never averaged away.

## What to do with each red

| KPI | First questions | Typical action |
|---|---|---|
| SLA | Which priorities? Breaches on assignment or on resolution? Out of hours? | Queue and assignment rules, cover for absences, escalation path |
| FCR, escalation | What did the first line hand over and why? | Knowledge articles, remote tools, admin rights for the local engineer, a runbook |
| Reopen | Closed without confirming with the user? | Closure check, sample of reopened tickets in the weekly team meeting |
| Backlog, ageing | Waiting on whom: user, vendor, purchase, another team? | Weekly ageing review: every old ticket has an owner, a next step and a date, or is closed |
| CSAT | What do the 1 and 2 scores say? Did something change at the site (people, hours, a move)? | Call the users back; restore on-site presence or a visit schedule |
| Availability | Which service, how many outages, provider references? Did the failover work? | RFO from the provider, service credits under the contract, diverse route, failover test |
| Compliance | One setting or one build behind most failures? | Fix the policy or pause the ring; remediation script; track to the target |
| Stale devices | Lost, replaced, on leave? | Contact the user; retire from Intune after the agreed period |
| Ageing hardware | In the refresh plan and the budget? | Next refresh wave |
| Overdue actions | Blocked or forgotten? | New date with a reason, or close; escalate the blocked ones |
| DR test | Booked? Who from the business must attend? | Book the test, run it, record the result and the follow-ups |

## How targets are set

- Start from the contract or the OLA where there is one (SLA, provider availability), and from last year's regional median where there is not.
- Same targets for every site; differences belong in the reasons, not in the thresholds. The exception is availability per service, because a backup circuit and a printer do not deserve the same target.
- Review the targets and the weights once a year with the site leads, not in the month a site turns red.
- Keep the minimum volumes: a small office is rated on what it has (backlog, availability, devices, DR) and its tickets are read one by one.

## Avoiding gaming the KPIs

- **SLA** can be met by closing and reopening: watch the reopen rate next to it.
- **FCR** can be inflated by not escalating: watch CSAT and reopens.
- **Backlog** can be cut by closing tickets without the user: watch reopens and CSAT, and sample closed tickets.
- **Ageing** can be reset by cloning old tickets: the oldest ticket keys in the reason make that visible.
- **Availability** can be improved by marking outages as planned: planned means announced in advance with a change reference; the planned minutes are listed in the reason.
- **Compliance** can be improved by excluding devices from the policy: compare the device count with last month.

The scorecard is for finding where to help, not for ranking people. Read each red with the site lead before the meeting, not in front of everybody for the first time.
