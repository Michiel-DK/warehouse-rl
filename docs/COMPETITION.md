# Competition sweep: does anyone else ship what the fleet stuck analyser does? (2026-10-18)

Scope: nineteen vendors, nine capabilities each, in three passes: two on 2026-10-18 (eight vendors, then AutoStore,
Symbotic, Körber/Infios, Zebra/Fetch, 6 River Systems and GreyOrange) and one on 2026-10-22 (Amazon Robotics, Hai
Robotics, Brightpick, Vecna Robotics, Seegrid). WebFetch/WebSearch only (no browser, no
logins), at most 12 fetches per vendor. The search logs (every URL fetched, with its result, and the count per vendor)
are in `laptop-scheduler/reports/wr-dev-competition-sweep.md`, `wr-dev-competition-sweep-2.md` and
`wr-dev-competition-sweep-3.md`, not here. Rules:
`~/.claude/skills/outward-claim-discipline`.

## How to read a cell

| value | meaning |
|---|---|
| `yes (A)` | shown in the vendor's own docs or manual (rank A) |
| `yes (B)` | shown only in first-party marketing copy: proves the claim, not the depth |
| `not found in docs (A)` | absent after the vendor's public doc tree was searched. The row names which of the four surfaces were read: footer-linked docs tree, /docs, /support or help subdomain, changelog |
| `UNTESTED` | doc tree behind a login, missing or unreachable, or only marketing or press available. Absence on marketing pages is never written as "not found" |

Press and trade-press material (rank C) is not a cell value. Where it exists, the cell stays `UNTESTED` and the press
quote goes in the evidence column. Quotes are short and verbatim from the page named, as returned by WebFetch.

## The nine capabilities (same bar for every vendor)

1. **Heatmap**: stalls, incidents, errors or stops shown by floor location (a map, or a per-place breakdown).
2. **Recurring-location trend**: which places keep coming back, not just incident counts over time.
3. **Forecast**: a predicted *future* location of stalls. Predictive maintenance of a robot part and demand forecasts
   do not count.
4. **Forecast grading**: a measured hit rate of that forecast against what happened later.
5. **Graded lessons**: generated rules or recommendations whose truth is re-checked in a later window.
6. **Time-to-detect**: how long detection took (MTTD). MTTR alone does not count.
7. **Decision ledger**: the system's calls logged with an outcome grade. Incident acknowledge/resolve status does
   not count; it is noted as "incident status only".
8. **Avoid-zones / cost maps to routing**: zones or costs that routing uses. Each cell says whether the zones are
   drawn by hand or derived from incident data.
9. **Log upload for a client's own fleet**: vendor-agnostic ingest of another fleet's data for analysis.

Borderline cells were scored toward presence, i.e. against us, except three in the second pass that a precedent or
the bar ruled out; all are listed in the direction test at the end.

## Summary matrix

H = heatmap, T = trend, F = forecast, G = forecast grading, L = graded lessons, D = time-to-detect,
R = decision ledger, Z = avoid-zones to routing, U = log upload. `A`/`B` = yes at that rank, `n` = not found in
docs (A), `?` = UNTESTED. Cells verified@2026-10-18 (first fourteen rows) or verified@2026-10-22 (last five).

| vendor | doc tree | H | T | F | G | L | D | R | Z | U |
|---|---|---|---|---|---|---|---|---|---|---|
| Formant | public | A | A | n | n | n | n | n | n | A |
| InOrbit | public | A | A | n | n | n | n | n | A | A |
| OTTO Motors (Fleet Analytics) | public tech docs; help centre behind login | A | A | ? | ? | ? | ? | ? | A | ? |
| MiR (Insights) | login | B | ? | ? | ? | ? | ? | ? | ? | ? |
| Locus Robotics | none (portal being redesigned) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Geek+ | partner portal | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Exotec | none | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Dematic (iQ) | login | ? | ? | ? | ? | ? | ? | ? | ? | B |
| AutoStore (CubeAnalytics) | none public | ? | ? | ? | ? | ? | ? | ? | ? | B |
| Symbotic | none public | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Körber (Infios) | login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Zebra / Fetch | none found | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| 6 River Systems (Ocado IA) | none public | ? | ? | ? | ? | ? | ? | ? | B | ? |
| GreyOrange (GreyMatter) | login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Amazon Robotics (DeepFleet; RoboRunner discontinued) | site redirects to a login; no tree | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Hai Robotics (HaiQ) | partner portal | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Brightpick (Intuition) | legal docs only | ? | ? | B | ? | ? | ? | B | B | ? |
| Vecna Robotics (Pivotal) | portal + partner login | B | ? | ? | ? | ? | ? | ? | B | ? |
| Seegrid (Fleet Central, Supervisor) | help centre unreachable; LMS login | ? | ? | ? | ? | ? | ? | ? | ? | ? |

## Per vendor

### Formant
Surfaces read: footer-linked docs tree https://docs.formant.io, searched by title through its full index
https://docs.formant.io/llms.txt plus the pages below; /docs pages /docs/incident-management,
/docs/getting-started-map-heatmap-overlay.md, /docs/heatmap-module.md, /docs/ingest-from-the-python-cloud-sdk.md;
support: https://formant.ai/support (contact page only, no help centre); changelog:
https://docs.formant.io/reference/sdk-versions-distributions-changelogs-and-licensing.md is an SDK changelog with no
entries on these topics, and no product changelog was found (a web search found none). Limit: absences rest on page
titles in llms.txt plus the pages above, not a full-text read of every page. 10 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A) verified@2026-10-18 | https://docs.formant.io/docs/getting-started-map-heatmap-overlay.md | "useful for spotting where robots repeatedly stop, get stuck, or dwell across a site"; a dwell-density layer, not an incident layer |
| Recurring-location trend | yes (A) verified@2026-10-18 | same page | "repeatedly stop" within "the selected time range only"; no comparison across windows. Scored yes to stay on the unflattering side |
| Forecast | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/llms.txt, https://docs.formant.io/docs/incident-management | read: tree (llms.txt), /docs, support, changelog (SDK only); no title with predict/forecast/insight/anomaly; the incident page names "predicting, and preventing potential issues" as a goal, with no feature behind it |
| Forecast grading | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/llms.txt | read: tree (llms.txt), /docs, support, changelog (SDK only); no prediction pages |
| Graded lessons | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/llms.txt | read: tree (llms.txt), /docs, support, changelog (SDK only); no insight or recommendation pages |
| Time-to-detect | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/docs/incident-management | read: tree (llms.txt), /docs, support, changelog (SDK only); MTTR only: "track time to resolution of incidents" |
| Decision ledger | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/llms.txt | read: tree (llms.txt), /docs, support, changelog (SDK only); no decision or outcome pages |
| Avoid-zones to routing | not found in docs (A) verified@2026-10-18 | https://docs.formant.io/llms.txt | read: tree (llms.txt), /docs, support, changelog (SDK only); no title with zone, geofence, keep-out, route or navigation |
| Log upload | yes (A) verified@2026-10-18 | https://docs.formant.io/docs/ingest-from-the-python-cloud-sdk.md | "sometimes you may want to ingest directly without requiring an agent"; live ingest, historical backfill not described |

### InOrbit
Surfaces read: footer "Docs" https://www.inorbit.ai/docs (read in full, 136k characters); /docs on the developer site
https://developer.inorbit.ai/docs (read in full, 198k characters); support: https://www.inorbit.ai/support
(support-plan marketing that links back to the two doc trees, an FAQ and Discord); changelog: none linked from any
of the three; release news is a /news page, not read. 5 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A) verified@2026-10-18 | https://www.inorbit.ai/docs | Incidents overlay "highlights points on the map where incidents were logged by the robot during the time range"; per robot |
| Recurring-location trend | yes (A), per robot, within one window, verified@2026-10-18 | https://www.inorbit.ai/docs | the Incidents overlay shows "points on the map where incidents were logged by the robot during the time range"; repeat points within one window, no comparison across windows. Scored yes, same rule as Formant |
| Forecast | not found in docs (A) verified@2026-10-18 | same | read: tree, /docs (developer), support, changelog (none found); no predict or forecast in either tree |
| Forecast grading | not found in docs (A) verified@2026-10-18 | same | read: tree, /docs (developer), support, changelog (none found); none |
| Graded lessons | not found in docs (A) verified@2026-10-18 | https://www.inorbit.ai/docs | read: tree, /docs (developer), support, changelog (none found); actions to "recommend to the end user" are configured by hand, not generated or graded |
| Time-to-detect | not found in docs (A) verified@2026-10-18 | https://www.inorbit.ai/docs | read: tree, /docs (developer), support, changelog (none found); the "for sec." field is a configured delay ("the length of time that the warning or error condition must last"), not measured latency |
| Decision ledger | not found in docs (A) verified@2026-10-18 | https://www.inorbit.ai/docs | read: tree, /docs (developer), support, changelog (none found); incident status only: "a severity level between SEV0 (most serious) and SEV3 (least serious)"; Opsgenie two-way sync |
| Avoid-zones to routing | yes (A), drawn by hand, verified@2026-10-18 | https://developer.inorbit.ai/docs | "The `nogo` rule pauses any robot that enters the zone polygon."; "Polygon coordinates are normally obtained when drawing the zone in the app". A pause rule, not a routing cost |
| Log upload | yes (A) verified@2026-10-18 | https://developer.inorbit.ai/docs | "A connector is a custom component that connects a third-party system to InOrbit."; live ingest, no historical file upload described |

### OTTO Motors (OTTO by Rockwell Automation)
Surfaces read: footer "Tech Docs" https://docs.ottomotors.com (public): navigation menu (searched for Cost, Zone,
Analytics, Predict), concepts--fleet-analytics, reading-otto-fleet-analytics, viewing-fm-statistics, exceptions,
creating-zones, assumed-cost-zone; changelog: https://docs.ottomotors.com/en/30495-127031-new-in-this-version.html
(read); help: https://help.ottomotors.com is a Confluence login and https://ottomotors.com/support returns 404, so the
support surface could not be searched. The in-site search needs JavaScript and was not run, and only the first 100k
characters of the navigation menu were read. Because the help centre is behind a login, no absence is claimed: rows
with nothing on the public pages are UNTESTED. 11 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A), per-place breakdown, no map, verified@2026-10-18 | https://docs.ottomotors.com/en/30495-117801-concepts--fleet-analytics.html | "Task failures can be filtered by robot and root cause, as well as correlated with endpoint"; dashboards can show "only the selected place" (reading-otto-fleet-analytics) |
| Recurring-location trend | yes (A) verified@2026-10-18 | same page | "The frequency and contributing factors behind recurring events."; data "from periods of years". A per-place time series is not described; scored yes |
| Forecast | UNTESTED verified@2026-10-18 | same page; navigation menu; release notes | nothing on the public tech-docs pages read; help centre is a login: no predict, forecast or heatmap on the analytics pages; no navigation link containing "Predict" |
| Forecast grading | UNTESTED verified@2026-10-18 | same | nothing on the public tech-docs pages read; help centre is a login: none |
| Graded lessons | UNTESTED verified@2026-10-18 | https://docs.ottomotors.com/en/30495-31068-reading-otto-fleet-analytics.html | nothing on the public tech-docs pages read; help centre is a login: no recommendations on the analytics pages |
| Time-to-detect | UNTESTED verified@2026-10-18 | https://docs.ottomotors.com/en/30495-31048-viewing-fm-statistics.html | nothing on the public tech-docs pages read; help centre is a login: job counts and "Average time that jobs take to execute"; no MTTD or MTTR |
| Decision ledger | UNTESTED verified@2026-10-18 | https://docs.ottomotors.com/en/30495-31050-exceptions.html | nothing on the public tech-docs pages read; help centre is a login: the Exceptions menu "displays relevant robot alerts"; no graded calls |
| Avoid-zones to routing | yes (A), drawn by hand, verified@2026-10-18 | https://docs.ottomotors.com/en/30495-30727-assumed-cost-zone.html | "Assumed Cost Zones assign a cost to specific areas in a facility to help direct traffic."; set by hand, and creating-zones says "Tap or click anywhere on the map to draw a rectangular Zone." Nothing derives zones from failures |
| Log upload | UNTESTED verified@2026-10-18 | https://docs.ottomotors.com/en/30495-127031-new-in-this-version.html | nothing on the public tech-docs pages read; help centre is a login: VDA 5050 control interop only; no ingest of another fleet's data on the analytics pages |

### MiR (MiR Fleet / MiR Insights)
Surfaces read: product page; support: https://supportportal.mobile-industrial-robots.com (sign-in form, nothing
public behind it); footer docs tree, /docs and changelog: none public. Every absence is UNTESTED. 2 fetches. *(Note 2026-10-21, LITERATURE Part 5 §4: a 2020 MiR Fleet 1.2 reference guide exists on a distributor mirror,
https://www.hmi-mbs.fr/wp-content/uploads/2020/07/notice-mir_fleet_reference_guide_12_en.pdf; it says nothing about
what is behind the sign-in, and the cells stay UNTESTED.)*

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (B) verified@2026-10-18 | https://mobile-industrial-robots.com/products/software/mir-insights | "Use heatmaps and time-series analysis to pinpoint bottlenecks and optimize workflows."; traffic, not explicitly stalls |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | "Compare metrics over time", not by location; docs behind login |
| Forecast | UNTESTED verified@2026-10-18 | https://supportportal.mobile-industrial-robots.com | docs behind login |
| Forecast grading | UNTESTED verified@2026-10-18 | same | docs behind login |
| Graded lessons | UNTESTED verified@2026-10-18 | same | docs behind login |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | docs behind login |
| Decision ledger | UNTESTED verified@2026-10-18 | same | docs behind login |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | docs behind login |
| Log upload | UNTESTED verified@2026-10-18 | https://mobile-industrial-robots.com/products/software/mir-insights | "retrieving raw data through a cloud API for use with external systems" is export, not ingest |

### Locus Robotics (LocusONE, LocusINTELLIGENCE)
Surfaces read: footer support page https://locusrobotics.com/support/ (email and phone; "We're preparing a
redesigned portal"); product page; no public docs tree, /docs or changelog found. Every cell UNTESTED. 2 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://locusrobotics.com/support/ | no public docs |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | no public docs |
| Forecast | UNTESTED verified@2026-10-18 | https://locusrobotics.com/platform/locusone/ | marketing: "analyzes operational data to forecast demand" (demand, not stall location) |
| Forecast grading | UNTESTED verified@2026-10-18 | https://locusrobotics.com/support/ | no public docs |
| Graded lessons | UNTESTED verified@2026-10-18 | https://locusrobotics.com/platform/locusone/ | marketing: "recommend actions that raise throughput"; grading not stated |
| Time-to-detect | UNTESTED verified@2026-10-18 | https://locusrobotics.com/support/ | no public docs |
| Decision ledger | UNTESTED verified@2026-10-18 | same | no public docs |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | no public docs |
| Log upload | UNTESTED verified@2026-10-18 | same | no public docs |

### Geek+ (RMS, IOP)
Surfaces read: software page; partner portal https://gpp.geekplus.com (redirects to a JavaScript client titled
"Geek+ Partner Portal", nothing public); no footer docs tree, /docs or changelog linked from the software page. Every
cell UNTESTED. 4 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://www.geekplus.com/software | marketing: "efficiency analysis framework to identify operational bottlenecks"; location not stated |
| Recurring-location trend | UNTESTED verified@2026-10-18 | https://gpp.geekplus.com | docs behind partner portal |
| Forecast | UNTESTED verified@2026-10-18 | https://www.geekplus.com/software | marketing lists "Predictive alerts" for IOP; location not stated |
| Forecast grading | UNTESTED verified@2026-10-18 | https://gpp.geekplus.com | docs behind partner portal |
| Graded lessons | UNTESTED verified@2026-10-18 | same | docs behind partner portal |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | docs behind partner portal |
| Decision ledger | UNTESTED verified@2026-10-18 | https://www.geekplus.com/software | marketing, incident status only: "acknowledge, assign, and track the status of alerts" |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | marketing: "distributing work intelligently across the same zone" is task allocation, not routing |
| Log upload | UNTESTED verified@2026-10-18 | https://gpp.geekplus.com | docs behind partner portal |

### Exotec (Skypod, Deepsky software)
Surfaces read: https://www.exotec.com/llms.txt (no docs, help or changelog URLs); support page
https://www.exotec.com/warehouse-automation-support/ (marketing, "Contact Us" only); Deepsky product page. No public
doc tree. Every cell UNTESTED. 4 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://www.exotec.com/warehouse-automation-support/ | no public docs |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | no public docs |
| Forecast | UNTESTED verified@2026-10-18 | https://www.robotics247.com/article/exotec_adds_three_modular_technologies_skypod_warehouse_automation/Machine_Learning | press (C), 19 Jan 2023: "The software proactively adapts routes in case of potential failures to ensure continuous operations." Location and depth not stated |
| Forecast grading | UNTESTED verified@2026-10-18 | https://www.exotec.com/warehouse-automation-support/ | no public docs |
| Graded lessons | UNTESTED verified@2026-10-18 | same | no public docs |
| Time-to-detect | UNTESTED verified@2026-10-18 | https://www.exotec.com/system/warehouse-optimization-software/ | marketing: control centres "detect and troubleshoot 90% of issues remotely"; no detection latency |
| Decision ledger | UNTESTED verified@2026-10-18 | https://www.exotec.com/warehouse-automation-support/ | no public docs |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | no public docs |
| Log upload | UNTESTED verified@2026-10-18 | same | no public docs |

### Dematic (KION; iQ, Command Center)
Surfaces read: https://docs.dematic.com (login, Titania Delivery); Command Center product page (links only to a
customer-portal login and a community site); no public /docs, support help centre or changelog. iQ InSights has no
current product page; a web search for it returned trade press only. Every absence UNTESTED. 4 fetches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://docs.dematic.com | docs behind login |
| Recurring-location trend | UNTESTED verified@2026-10-18 | https://www.dematic.com/en-us/software/command-center/ | marketing: "Historical insight and root-cause analysis"; location not stated |
| Forecast | UNTESTED verified@2026-10-18 | same | marketing: "where performance is heading next"; location not stated. A trade-press article on iQ 2.5 bottleneck dashboards (https://www.mhwmag.com/products/dematic-announces-release-of-dematic-iq-2-5/) returned 403 and is unverified |
| Forecast grading | UNTESTED verified@2026-10-18 | https://docs.dematic.com | docs behind login |
| Graded lessons | UNTESTED verified@2026-10-18 | same | docs behind login |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | docs behind login |
| Decision ledger | UNTESTED verified@2026-10-18 | same | docs behind login |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | docs behind login |
| Log upload | yes (B) verified@2026-10-18 | https://www.dematic.com/en-us/software/command-center/ | "Dematic Command Center is vendor-agnostic."; "collects scattered data into a unified view". Multi-vendor data, not a log upload as such; scored yes |

### AutoStore (CubeAnalytics, CubeVerse)
Surfaces read: home page header and footer https://www.autostoresystem.com/ (no docs, support, help or changelog link;
closest are "Solution FAQs" and contact); https://www.autostoresystem.com/sitemap.xml (over 10 MB, not read); the
CubeAnalytics product page, its FAQ https://www.autostoresystem.com/faq/cube-analytics and the product sheet
https://www.autostoresystem.com/hubfs/04%20Website%20Docs/01%20Spec%20Sheets/AutoStore-CubeAnalytics-Product-Sheet-EN.pdf
(marketing, rank B). A web search found no docs portal, manual or release notes. No public doc tree, so every absence
is UNTESTED. 5 fetches, 1 search.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://www.autostoresystem.com/system/cube-analytics | marketing: "Ranks Grids by mean time between failures (MTBF)." A Grid is a whole installation, so this ranks sites, not floor locations; the sheet lists "module behavior across the Grid" without a map. Scored away from presence (see direction test) |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | marketing: "Spot recurring fleet issues."; location not stated |
| Forecast | UNTESTED verified@2026-10-18 | same; product sheet | marketing: "predict issues, surface sites most in need of attention"; sheet: "AI-powered anomaly detection identifies unusual system behavior and emerging issues before they affect operations." Sites, not floor locations |
| Forecast grading | UNTESTED verified@2026-10-18 | same | no public docs; no accuracy figure in marketing |
| Graded lessons | UNTESTED verified@2026-10-18 | https://www.autostoresystem.com/system/cube-analytics | marketing: "AI insights that surface what matters most and recommend clear actions for your team."; grading not stated |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | marketing: "Data updates every 5 minutes; critical system stop events flagged almost instantly in Actions Needed." Product latency, not MTTD reporting |
| Decision ledger | UNTESTED verified@2026-10-18 | same | no public docs; "Actions Needed" is an alert list as described |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | no public docs; routing not mentioned |
| Log upload | yes (B) verified@2026-10-18 | https://www.autostoresystem.com/system/cube-analytics | "Open API options to integrate with third-party data sources". Third-party data, not another fleet's logs; scored yes, same rule as Dematic. The FAQ's API "Allows access to raw real-time AutoStore log data." is export |

### Symbotic
Surfaces read: home page header and footer https://www.symbotic.com/ (no docs, developer, support, help or changelog
link); https://www.symbotic.com/resources/ (news and events hub); https://www.symbotic.com/news-and-events/blog/ (no
posts listed in the fetch); AI & Software and Robots product pages. A web search for a customer portal, docs or
release notes found none. No public doc tree; every cell UNTESTED. 5 fetches, 1 search.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://www.symbotic.com/solutions/ai-and-software/ | no public docs; nothing in marketing |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | no public docs |
| Forecast | UNTESTED verified@2026-10-18 | https://www.symbotic.com/solutions/robots/ | marketing: "AI supports continuous improvements through pattern recognition and human-lead training."; no forecast stated |
| Forecast grading | UNTESTED verified@2026-10-18 | https://www.symbotic.com/solutions/ai-and-software/ | no public docs |
| Graded lessons | UNTESTED verified@2026-10-18 | same | no public docs |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | marketing: "informing facilities immediately of potential damage"; no latency figure |
| Decision ledger | UNTESTED verified@2026-10-18 | same | no public docs |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | marketing names "complex bot routing"; zones or costs not stated |
| Log upload | UNTESTED verified@2026-10-18 | same | marketing: "integrates seamlessly with existing WMS or ERP systems"; no fleet-data ingest |

### Körber (now Infios)
Surfaces read: home page footer https://www.infios.com/ (Customer Support and Knowledge Center; no docs link);
support https://www.infios.com/en/customer-support, which sends cases to a ServiceNow portal
(https://infios.service-now.com/csm?id=csm_login, login) and links release-notes PDFs for the transportation product
only (not read: out of scope); training https://www.infios.com/en/knowledge-center/training-certification (Infios
Academy, https://theacademy.infios.com/learn, "for customer and partner users that have purchased a subscription");
AMR and Infios AI product pages. Doc tree behind a login; every cell UNTESTED. 5 fetches, 1 search (it returned a
different vendor's docs and is not used).

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://www.infios.com/en/supply-chain-solutions/autonomous-mobile-robots | docs behind login; marketing: "feed a continuous stream of data about the warehouse operation back into the WMS" |
| Recurring-location trend | UNTESTED verified@2026-10-18 | https://infios.service-now.com/csm?id=csm_login | docs behind login |
| Forecast | UNTESTED verified@2026-10-18 | https://www.infios.com/en/supply-chain-solutions/infios-ai | marketing: "Predicts what's likely to happen and where it will hit."; supply-chain events, not robot stalls |
| Forecast grading | UNTESTED verified@2026-10-18 | same | marketing gives no accuracy figure; docs behind login |
| Graded lessons | UNTESTED verified@2026-10-18 | same | marketing: "Infios AI recommends. You approve. Every decision is explained."; grading not stated |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | marketing: "responds faster than your team can act on its own"; no MTTD |
| Decision ledger | UNTESTED verified@2026-10-18 | same | marketing, Automated stage: "every action is tracked and auditable". An audit trail of AI actions, no outcome grade, scoped to orders and transport. Scored away from presence (see direction test) |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | https://infios.service-now.com/csm?id=csm_login | docs behind login |
| Log upload | UNTESTED verified@2026-10-18 | same | docs behind login |

### Zebra Technologies (Fetch Robotics, FetchCore, Symmetry)
Surfaces read: the AMR product page https://www.zebra.com/us/en/products/autonomous-mobile-robots.html (links to
TechDocs and https://support.zebra.com, no robot-software page); footer docs tree https://techdocs.zebra.com/ (no
robotics, AMR, FetchCore or Symmetry section); the product's own tree https://docs.fetchrobotics.com does not resolve
(DNS); https://support.zebra.com was not searched. The 2021 press release on FetchCore features was not reachable (the
English URL returned the newsroom index, the mirrored copy returned 404), so its "pick heatmap" wording, seen only in a
search snippet, is unverified and unused. Context (press, C): The Robot Report, 12 Dec 2025, "Zebra Technologies is
winding down its autonomous mobile robot (AMR) division."
(https://www.therobotreport.com/zebra-technologies-winding-down-fetch-based-mobile-robot-group/). Every cell UNTESTED.
6 fetches, 4 searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://techdocs.zebra.com/ | no robotics docs in TechDocs; Fetch docs domain gone; support.zebra.com not searched |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | same |
| Forecast | UNTESTED verified@2026-10-18 | same | same |
| Forecast grading | UNTESTED verified@2026-10-18 | same | same |
| Graded lessons | UNTESTED verified@2026-10-18 | same | same |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | same |
| Decision ledger | UNTESTED verified@2026-10-18 | same | same |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | same | same |
| Log upload | UNTESTED verified@2026-10-18 | same | same |

### 6 River Systems (Chuck; now Ocado Intelligent Automation)
Surfaces read: https://6river.com/ and https://6river.com/support/ (both returned empty pages); Ocado Intelligent
Automation home https://ocadointelligentautomation.com/ (footer: FAQ, glossary and "Ocado Developer Platform"; no
docs, support, help or changelog link); the developer platform domain (www.ocadodeveloperplatform.com and the bare
domain) does not resolve; Chuck AMR and Ocado IQ product pages. The Ocado IQ page describes the OMRS software and the
site navigation lists Chuck under OMRS. "Ocado IQ routinely releases software updates" but no release notes are
linked. No public doc tree; every absence UNTESTED. 7 fetches, 2 searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://ocadointelligentautomation.com/ocado-iq?hsLang=en | no public docs; no fault or stall locations in marketing |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | no public docs |
| Forecast | UNTESTED verified@2026-10-18 | same | marketing: "leveraging detailed real-time analytics and forecasting dashboards."; operational forecasting, location of stalls not stated |
| Forecast grading | UNTESTED verified@2026-10-18 | same | no public docs |
| Graded lessons | UNTESTED verified@2026-10-18 | same | marketing: "Gives you uplift results, visible with real-time analytics."; recommendations and their grading not stated |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | marketing: "It spots errors in real-time and takes action instantly."; no latency figure |
| Decision ledger | UNTESTED verified@2026-10-18 | same | no public docs |
| Avoid-zones to routing | yes (B), derived from live congestion, verified@2026-10-18 | https://ocadointelligentautomation.com/ocado-iq?hsLang=en | "Zones adjust in real-time based on task volume, urgency, and congestion."; routing is "factoring in aisle activity, congestion, and task urgency to avoid slowdowns". Work zones and routing fed by live congestion, not by stall history; scored yes |
| Log upload | UNTESTED verified@2026-10-18 | same | marketing: "tech-agnostic, supporting diverse software, tools, and accessories."; ingest of another fleet's data not stated |

### GreyOrange (GreyMatter)
Surfaces read: home page header and footer https://www.greyorange.com/ (no docs, support, help or changelog link);
knowledge centre https://docs.greyorange.com/ (described as holding user manuals, release notes and training videos,
behind "GO Customer Login"); GreyMatter technology and solutions pages. A site: search on docs.greyorange.com returned no indexed pages,
and a search for release notes returned trade press only. Doc tree behind a login; every cell UNTESTED. 4 fetches, 2
searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-18 | https://docs.greyorange.com/ | docs behind login |
| Recurring-location trend | UNTESTED verified@2026-10-18 | same | docs behind login |
| Forecast | UNTESTED verified@2026-10-18 | https://www.greyorange.com/greymatter/technology/ | marketing: "Predictive analytics for anticipating bottlenecks and future demands"; location not stated |
| Forecast grading | UNTESTED verified@2026-10-18 | https://docs.greyorange.com/ | docs behind login |
| Graded lessons | UNTESTED verified@2026-10-18 | same | docs behind login |
| Time-to-detect | UNTESTED verified@2026-10-18 | same | docs behind login |
| Decision ledger | UNTESTED verified@2026-10-18 | same | docs behind login |
| Avoid-zones to routing | UNTESTED verified@2026-10-18 | https://www.greyorange.com/greymatter/solutions/ | marketing: "predicting demand and dynamically assigning resources" is task allocation, not routing |
| Log upload | UNTESTED verified@2026-10-18 | https://www.greyorange.com/greymatter/technology/ | marketing: "A hardware-agnostic protocol layer for interoperability with a wide range of certified devices". Control interop, same rule as OTTO's VDA 5050; scored away from presence (see direction test) |

### Amazon Robotics
Surfaces read: amazonrobotics.com (https://www.amazonrobotics.com/) is no longer a product site: it 301-redirects to
https://amazon.jobs/en/internal/teams/amazon-robotics, which 307-redirects to an Amazon Federate OAuth login
(idp.federate.amazon.com), so the former vendor site is behind a login. `site:amazonrobotics.com` returns only
amazon.jobs careers pages; no docs, support, help or changelog host exists. The public careers page
https://www.amazon.jobs/teams/amazon-robotics was read in full: careers only, no docs/support/changelog links, no
sentence about selling to outside customers. First-party marketing on aboutamazon.com (the robot line-up page and the
DeepFleet announcement) was read in full; neither links documentation. The only Amazon fleet software ever documented
for outside customers, AWS IoT RoboRunner, is discontinued: https://aws.amazon.com/iot-roborunner/ returns 404 and the
developer-guide URL redirects to the AWS docs index; a third-party post (Classmethod, 2024-03-23, rank C) reports the
console, guides and endpoints removed. No public doc tree; every cell UNTESTED. 7 fetches, 3 searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-22 | https://www.aboutamazon.com/news/operations/amazon-robotics-robots-fulfillment-center | no doc tree; marketing covers nine robots and AI, nothing on incident maps or dashboards |
| Recurring-location trend | UNTESTED verified@2026-10-22 | same | no doc tree; not mentioned on any first-party page read |
| Forecast | UNTESTED verified@2026-10-22 | https://www.aboutamazon.com/news/operations/amazon-million-robots-ai-foundation-model | marketing, DeepFleet: "As DeepFleet learns from more data, it will continue to get smarter"; no located forecast of stalls |
| Forecast grading | UNTESTED verified@2026-10-22 | same | the only outcome claim is "improve robot fleet travel efficiency by 10%", travel time, not a hit rate |
| Graded lessons | UNTESTED verified@2026-10-22 | https://www.amazon.jobs/teams/amazon-robotics | no doc tree; nothing on any surface read |
| Time-to-detect | UNTESTED verified@2026-10-22 | https://docs.aws.amazon.com/iotroborunner/latest/dev/what-is-iotroborunner.html | the one former doc tree (RoboRunner) is gone; the URL resolves to the AWS docs index |
| Decision ledger | UNTESTED verified@2026-10-22 | same | no doc tree; no incident status surface either |
| Avoid-zones to routing | UNTESTED, leans present, internal only, verified@2026-10-22 | https://www.aboutamazon.com/news/operations/amazon-million-robots-ai-foundation-model | marketing, DeepFleet: "Think of DeepFleet as an intelligent traffic management system for a city filled with cars moving through congested streets."; "less congestion, more efficient paths". Congestion-aware routing claimed, no zone or cost-map wording, no incident-derived statement, used inside Amazon only ("Built using the company's rich and extensive data sets of inventory movement within its sites") |
| Log upload | UNTESTED verified@2026-10-22 | https://aws.amazon.com/iot-roborunner/ | the only external-customer fleet product (RoboRunner) is discontinued, page 404; rank C (Classmethod 2024-03-23): "the English product page was gone, the console was inaccessible, the developer guides were removed, and the service endpoints no longer existed." Amazon Robotics does not sell to third parties (careers page: "They design, test, and build our fleet of robots and mechatronic systems.") |

Direction test: one borderline call, avoid-zones. DeepFleet's marketing describes congestion-aware routing, which a
generous reader could score `yes (B)`; kept UNTESTED because the claim names no zones or cost map, says nothing about
incident-derived inputs, and the system is internal to Amazon, so it is not a product offered to a customer. Counting
internal Amazon technology as the vendor would flip that row to `yes (B)` (against us).

### Hai Robotics
Surfaces read: home and footer https://www.hairobotics.com/ (public, read in full): footer links are Solutions,
Industries, Resources, About, legal pages and /sitemap; no docs, help, manual, changelog, developer or API link; the only
account link is a Partner Portal "Log in". /support returns 404; docs.hairobotics.com does not resolve; help. and
support. subdomains were not probed (budget) and no search pointed at one. sitemap.xml (public, read in full, about 500
URLs): blog, cases, news, videos, solutions, robots, industries, campaign and job pages only; no doc, manual, help or
release URL. /download-center (public, page 1 of 7 by title): form-gated brochures, flyers, case studies and
whitepapers, no manual or software guide. /faq-glossary (public): event FAQs and a generic AMR/ASRS glossary.
/solutions/haiq-software, the HaiQ blog post of 2023-10-31 and the PSIRT page were read in full (marketing). The one
first-party manual found (VCP personnel-vest system, hosted on device.report) returned 403 and is hardware only. No
public documentation tree; product docs sit behind the Partner Portal login. Every cell UNTESTED. 12 fetches, 4
searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-22 | https://www.hairobotics.com/solutions/haiq-software | no doc tree; HaiQ marketing has no fault or stall map, Data Platform only: "the value of data analysis can be demonstrated, such as warehouse traffic, work efficiency." A press release (rank C, BusinessWire 2025-03-10, page 403, seen only as a search paraphrase) describes a digital-twin view with storage-location heatmaps: inventory, not stalls |
| Recurring-location trend | UNTESTED verified@2026-10-22 | same | no doc tree; no recurrence or per-place trend text on any first-party page read |
| Forecast | UNTESTED verified@2026-10-22 | same | no doc tree; Simulation Platform "creates a virtual warehouse by inputting map files, order files, inventory files, and demand configurations." and "conducts a 1:1 simulation": capacity simulation, not a stall-location forecast |
| Forecast grading | UNTESTED verified@2026-10-22 | same | no doc tree; no accuracy or hit-rate text on any page read |
| Graded lessons | UNTESTED verified@2026-10-22 | same | no doc tree; blog: "No more guesswork, just data-driven decisions."; no generated rules, no re-check |
| Time-to-detect | UNTESTED verified@2026-10-22 | https://www.hairobotics.com/solutions/information-security-support | no doc tree; the only latency figure on the site is security-incident handling, "completes an initial assessment within 24 hours.", PSIRT not stall MTTD |
| Decision ledger | UNTESTED verified@2026-10-22 | https://www.hairobotics.com/blog/creating-new-era-flexible-and-data-driven-automated-warehouses-haiq | no doc tree; "HaiQ optimizes order routing and scheduling with incredible precision"; no logging of calls or outcomes, no incident status seen |
| Avoid-zones to routing | UNTESTED verified@2026-10-22 | https://www.hairobotics.com/solutions/haiq-software | no doc tree; Path Planning: "Minimize robot travel distance, achieve robot avoidance, queueing, and other actions, and reduce workstation downtime.": inter-robot avoidance, no zones, no cost map |
| Log upload | UNTESTED verified@2026-10-22 | same | no doc tree; "Multi-type Robot Mixed Field Operation" and an integration list ("conveyors, pick to light system, emergency stop switches, guard doors, etc.") are live orchestration of own or partner equipment, not vendor-agnostic log ingest |

Direction test: two borderline notes, both already UNTESTED because no public doc tree exists. The press-reported
storage-location heatmap is an inventory heatmap, not counted toward Heatmap but recorded. Mixed-fleet scheduling is
not log ingest, recorded under Log upload without counting it. Nothing on a first-party page reached `yes (B)`.

### Brightpick
Surfaces read: the footer of brightpick.ai links one "Documentation" page, https://brightpick.ai/documentation/
(public, read in full): titled "Brightpick legal documentation", eleven legal pages (terms, billing, post-warranty care,
privacy, vulnerability disclosure), no product manual, user guide or software doc. sitemap.xml (index) and
page-sitemap.xml (45 URLs) read in full: no docs, support, help, manual, changelog, api or portal URL. docs.brightpick.ai
and support.brightpick.ai do not resolve; help. was not probed (budget). No changelog or release notes: a site search
returned press releases only. https://brightpick.ai/faq/ (public, 40 questions, read in full) is marketing-grade Q&A.
Product pages read in full: /analytics/, /intuition-ai/, /ai-and-software/, and two blog posts (Meet Brightpick
Intuition, 2024-11-20; How AMRs work in real warehouse operations, 2026-01-08). No public product documentation; every
surface is marketing, so no cell can be "not found in docs". 12 fetches (2 failed DNS), 3 searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-22 | https://brightpick.ai/analytics/, https://brightpick.ai/faq/ | dashboards only, no location view on marketing: "Quickly isolate any bottlenecks impacting performance (inventory, tote buffers, congestion, robot uptime)"; FAQ: "We offer a suite of customizable dashboards that provide live and historical insight into your operation" |
| Recurring-location trend | UNTESTED verified@2026-10-22 | https://brightpick.ai/analytics/ | "HISTORICAL PERFORMANCE / Performance trends" is throughput over time; nothing about places that keep coming back |
| Forecast | yes (B), borderline, verified@2026-10-22 | https://brightpick.ai/intuition-ai/, https://brightpick.ai/resources/how-amrs-work-in-real-warehouse-operations/ | "our AI-powered Time-Space Planning algorithm, which continuously predicts fleet activity"; "More advanced systems like Brightpick Intuition go a step further by predicting robot movements ahead of time." A planner-internal prediction of robot positions and congestion, not a user-facing stall-location forecast; scored toward presence |
| Forecast grading | UNTESTED verified@2026-10-22 | https://brightpick.ai/intuition-ai/ | no hit-rate or accuracy claim for the prediction anywhere on the marketing surface; no doc tree |
| Graded lessons | UNTESTED verified@2026-10-22 | https://brightpick.ai/resources/meet-brightpick-intuition-the-software-brain-behind-our-robots/, https://brightpick.ai/analytics/ | suggestions exist, ungraded: "operational suggestions such as 'Add more totes to XX' or 'Running out of inventory in SKU Y'"; "Validate progress and results from process or software improvements" (the user validates, the system does not re-check its own rules) |
| Time-to-detect | UNTESTED verified@2026-10-22 | https://brightpick.ai/analytics/, same blog post | alerts claimed, no latency figure: "Avoid bottlenecks and achieve desired performance with real-time monitoring and early warning signals"; "With proactive alerts sent directly to your communication channels, you're always in the loop" |
| Decision ledger | yes (B), borderline, verified@2026-10-22 | https://brightpick.ai/intuition-ai/, https://brightpick.ai/faq/ | "Each pick records what the robot saw, the action it chose, the result, and how any exception was handled."; FAQ: "All activity, including failures, is logged and traceable." A pick-level log with its result; no routing or stall decisions, no grade beyond the pick result. Scored toward presence |
| Avoid-zones to routing | yes (B), borderline, derived from predicted occupancy, verified@2026-10-22 | https://brightpick.ai/intuition-ai/, https://brightpick.ai/resources/how-amrs-work-in-real-warehouse-operations/ | "dynamically re-plans robot paths to avoid congestion and maximize throughput."; "Instead of reacting only when congestion happens, the software plans routes based on where every robot is expected". Routing cost from predicted robot positions, not incident history; hand-drawn avoid zones not mentioned |
| Log upload | UNTESTED verified@2026-10-22 | https://brightpick.ai/faq/, https://brightpick.ai/analytics/ | the only integration claim is WMS/ERP: "Brightpick Intuition uses standard interfaces (APIs) to integrate seamlessly with your WMS / ERP."; analytics described for Brightpick's own fleet only |

Direction test: three borderline calls, all toward presence (against us): forecast (the planner predicts fleet
activity, not stalls), decision ledger (a per-pick action and result log, not a graded ledger of system calls) and
avoid-zones (congestion-aware routing from predicted positions, no incident-derived or hand-drawn zones). Graded
lessons and time-to-detect stay UNTESTED: the marketing names suggestions and alerts but says nothing about grading or
latency, and there is no doc tree to disprove them.

### Vecna Robotics
Surfaces read: footer and header of https://www.vecnarobotics.com/ read in full: no support, docs, help, knowledge-base,
changelog or release-notes link; "Technical support" is a phone number. Two login gates: "Go to Portal"
https://www.vecnarobotics.com/portal/ (returned the marketing homepage content, no form, no docs) and the Salesforce
Partner Portal https://vecnarobotics.my.site.com/partner/s/login/ (login template, nothing reachable);
https://www.vecnarobotics.com/login/ returned HTTP 500. sitemap.xml (7 sub-sitemaps) and page-sitemap.xml (105 URLs)
read in full: none containing docs, support, help, manual, release or api; resources-sitemap.xml (155 URLs) read by
title, two flagged ("mobile-robot-fleet-management", "what-data-does-caseflow-collect"), not fetched (cap). No docs.,
help. or support. subdomain surfaced in search. Product pages read in full: Pivotal Software Suite, Pivotal Command
Center, Pivotal Autonomous Navigation, "Make your business go". No public documentation tree; the whole public surface
is marketing, so every absence is UNTESTED. 12 fetches, 3 searches.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (B), borderline, verified@2026-10-22 | https://www.vecnarobotics.com/the-vecna-system/pivotal-software-suite/ | "Tap into performance trends, heatmaps and industry-unique analytics" (Pivotal Insights). The heatmap's subject is not stated; no stall, incident or error-by-location wording anywhere. Scored toward presence |
| Recurring-location trend | UNTESTED verified@2026-10-22 | same | marketing: "Pivotal™ analytics help you track your KPIs over time as well as identifying areas for expansion and improvement."; no location recurrence wording |
| Forecast | UNTESTED verified@2026-10-22 | same | no prediction or forecast wording on any Pivotal page |
| Forecast grading | UNTESTED verified@2026-10-22 | same | no forecast, so no grading; marketing only |
| Graded lessons | UNTESTED verified@2026-10-22 | same | marketing: "user-friendly dashboards help you transform your data into actionable insights"; nothing re-checked later |
| Time-to-detect | UNTESTED verified@2026-10-22 | https://www.vecnarobotics.com/the-vecna-system/pivotal-command-center/ | marketing: "ensures you get the help you need without a wait time"; 99.9% uptime and "< 1%" local assist rate; no MTTD figure |
| Decision ledger | UNTESTED verified@2026-10-22 | same | marketing: "Performance and support data from all Vecna robots is collected."; no incident log or graded calls; not even incident status visible publicly |
| Avoid-zones to routing | yes (B), borderline, hand-programmed, verified@2026-10-22 | https://www.vecnarobotics.com/the-vecna-system/pivotal-autonomous-navigation/ | the map is "programmed with pickup/drop-off locations and rules of the road"; "If congestion is too high on the prescribed route, Vecna's AMRs will pursue alternative available paths to keep moving." Rules set at deployment; no avoid-zone, cost map or incident-derived zone named. Scored toward presence |
| Log upload | UNTESTED verified@2026-10-22 | https://www.vecnarobotics.com/the-vecna-system/pivotal-software-suite/ | marketing: "Pivotal™ uses performance data collected from every robot in Vecna's entire fleet"; a "Pivotal™ Integrations" module is named without detail; no vendor-agnostic ingest shown |

Direction test: two borderline calls, both toward presence (against us): a bare "heatmaps" mention counted as a
heatmap though its subject is unstated, and hand-programmed "rules of the road" plus live congestion rerouting counted
as routing-consumed zones though no avoid-zone or cost map is named. "Beacon" appears on no fetched Vecna page (one
search summary attributed a sentence to a Vecna page that did not contain it), so Beacon stays unverified. Mark 3 /
Free Space Reasoning press (2021) is rank C and used in no cell.

### Seegrid
Surfaces read: footer of https://seegrid.com/ (public, read in full): product and marketing pages, Media Kit, Privacy
Policy, an ISO 27001 PDF; no docs, help centre, knowledge base, manual or changelog link. sitemap.xml (index of 5 child
maps) and page-sitemap.xml (37 page URLs, read by title): nothing resembling docs, manuals, release notes, changelog,
FAQ or knowledge base; "Fleet Geek" survives only as an image filename. https://support.seegrid.com/ 301-redirects to
https://seegrid.kcenter.usu.com/helpcenter (USU Knowledge Center), which does not resolve, so the help centre is
unreachable from the public web. https://seegrid.com/customer-resources/ (public) offers only a support email and
"Seegrid Learning" at https://seegrid.docebosaas.com/learn, a JS-only LMS that rendered "Loading" and is described as
customer access ("Seegrid customers have 24/7 access to materials"): treated as behind a login.
/service-and-support/ (public) has no doc links. Marketing read in full: /fleet-central/ and
/fleet-central/supervisor/. hub.seegrid.com redirects to seegrid.com and the Fleet Geek press-release URL returned 404.
No public documentation tree; every absence is UNTESTED. 12 fetches, 4 searches (cap reached).

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/supervisor/ | marketing: "Map and status views show where your AMRs and materials are going with our fleet tracker." (live positions, not stalls by place); Fleet Central: "Gives industrial engineers and facility managers actionable data to identify inefficiencies"; doc tree unreachable |
| Recurring-location trend | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/ | marketing: "providing data-driven fleet insights for continuous workflow improvement and performance."; trade press (rank C, search summary only) says Fleet Geek tracks "material flow trends", flow not recurring stall locations |
| Forecast | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/supervisor/ | marketing: "subway-style estimated time of arrival projections", ETA of material, not stall location |
| Forecast grading | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/ | marketing only; nothing on measured hit rates |
| Graded lessons | UNTESTED verified@2026-10-22 | same | marketing only; nothing beyond "actionable data to identify inefficiencies" |
| Time-to-detect | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/supervisor/ | alerts exist ("receive instant alerts when action is needed for accurate material movement"; "Automatic text and email alerts can inform when an AMR has a low battery, completes a delivery, and more.") but no MTTD figure |
| Decision ledger | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/ | marketing: "Allows facility operators to check battery status, assign jobs, and view task completions in real-time."; no logged calls with outcomes, no incident status on public pages |
| Avoid-zones to routing | UNTESTED, leans present, hand-drawn, verified@2026-10-22 | https://seegrid.com/fleet-central/supervisor/ | marketing: "Supervisor acts as your automated traffic cop to keep AMRs and employees moving through high-traffic intersections."; "Dynamically re-route AMRs to any location with remote calling". A first-party press release surfaced by search but not fetched (cap) describes a Supervisor "Caution Tape" feature blocking route segments for construction, maintenance or spillage: operator-drawn blocks, not incident-derived costs. One fetch would likely make this `yes (B)` |
| Log upload | UNTESTED verified@2026-10-22 | https://seegrid.com/fleet-central/ | marketing: "As a VDA 5050 interoperable platform, Fleet Central can unify control of Seegrid AMRs"; "This allows you to orchestrate mixed-vendor fleets and manage different brands of automated equipment": mixed-vendor live control, not log ingest for analysis |

Direction test: two borderline calls, both leaning toward presence (against us): avoid-zones, where an unfetched
first-party press release describes hand-drawn "Caution Tape" route blocks, and log upload, where VDA 5050 mixed-vendor
orchestration implies other vendors' vehicle data enters Fleet Central live. The live "Map and status views" is a
position map, not a stall heatmap, kept UNTESTED rather than scored down.

## What changed against the README's 13 Oct note

- "Formant sells ... trend analysis of recurring problems" came from a marketing read. The docs show a heatmap
  overlay for "where robots repeatedly stop, get stuck" (rank A). It stays a presence, now with a docs source.
- "The parts ... not on the shelf: a vendor-agnostic plugin that reads the files a client already has": Formant's
  Cloud SDK and InOrbit's connectors are documented vendor-agnostic ingest (rank A). Only *historical file* upload was
  not found, so the vendor-agnostic half of that sentence is contradicted and is dropped from the README.
- The 15 Oct InOrbit facts (Incidents overlay, SEV levels) were re-confirmed at rank A on 2026-10-18.

## What changed in the second pass

- No new rank-A presence: none of the six added vendors publishes a public doc tree, so all four rank-A columns still
  rest on Formant, InOrbit and OTTO.
- Ocado's congestion-fed zones are the first zones found that are derived from data rather than drawn by hand (rank B,
  live congestion, not stall history), so "zones derived from incident data were not found" now needs that qualifier.

## What changed in the third pass (2026-10-22)

- No new rank-A presence and no new rank-A absence: none of the five vendors has a public documentation tree.
  Amazon Robotics' own site now redirects to an internal Amazon login and its one externally documented fleet product,
  AWS IoT RoboRunner, is gone (product page 404, developer guide redirects to the AWS docs index). Hai's docs sit
  behind a partner portal, Brightpick's "Documentation" page is legal text only, Vecna's portal and partner site are
  logins, and Seegrid's help centre redirects to a host that does not resolve.
- Four rank-B presences, all borderline and all scored against us: Vecna's "heatmaps" (subject unstated) and
  hand-programmed "rules of the road"; Brightpick's planner that "continuously predicts fleet activity" (a planner's
  own occupancy prediction, not a stall forecast shown to a user), its per-pick log of "what the robot saw, the action
  it chose, the result" (a pick log, not a graded ledger of system calls) and its congestion-aware routing from
  predicted positions.
- The forecast column therefore has its first `B`. It does not touch the four columns our claim rests on (forecast
  grading, graded lessons, time-to-detect, decision ledger with an outcome grade), which stay `not found in docs` for
  Formant and InOrbit and UNTESTED for every other vendor, now seventeen of nineteen.
- Near-misses a demo account could turn into presence: Seegrid Supervisor's "Caution Tape" route blocks (a first-party
  press release surfaced by search, not fetched: operator-drawn, not incident-derived) and Amazon's DeepFleet
  congestion routing (marketing, internal to Amazon, not sold).

## What this means for our claim

Across nineteen vendors, four of our nine capabilities are documented at rank A by at least one vendor: a stall or
incident map (Formant, InOrbit, OTTO), a recurring-location view within one chosen window (the same three),
hand-drawn avoid or cost zones used by routing (InOrbit, OTTO) and vendor-agnostic live ingest (Formant, InOrbit);
marketing adds MiR's and Vecna's heatmaps, Dematic's and AutoStore's third-party data, Ocado's congestion-fed zones,
Vecna's hand-programmed traffic rules and Brightpick's occupancy-predicting planner, pick log and congestion routing. Five were
not found in any doc tree searched: a location forecast, forecast grading, persistence-graded lessons, time-to-detect
reporting and a graded decision ledger. That absence still rests on the two fully searchable trees (Formant, InOrbit):
none of the six vendors added in this pass has a public doc tree (GreyOrange and Körber keep theirs behind a customer
login, AutoStore, Symbotic and Ocado/6 River publish none, and Zebra's Fetch docs domain no longer resolves), and none
of the five added on 22 Oct has one either, so seventeen of nineteen vendors are UNTESTED on all five. The near-misses a demo account could turn into presence are failure or
bottleneck anticipation (Exotec in press; Geek+, Dematic, AutoStore and GreyOrange in marketing), none stating a floor
location or a hit rate; Infios AI's "every action is tracked and auditable", the nearest thing to a decision ledger
found, with no outcome grade and scoped to orders and transport; and Ocado's zones that adjust to live congestion.
So "nobody grades their forecasts" holds for two vendors and is unknown for seventeen, and "not on the shelf" is a claim
about Formant and InOrbit, not the market. Direction test, against us: Formant's and InOrbit's within-window repeats
counted as a trend, OTTO's place filter as a heatmap, Dematic's and AutoStore's third-party data as log upload, and
Ocado's live-congestion zones as avoid-zones. Direction test, in our favour: AutoStore's MTBF ranking of whole Grids
not counted as a heatmap, GreyOrange's hardware-agnostic robot control not counted as log upload (the OTTO VDA 5050
rule), and Infios's auditable actions not counted as a ledger. Those three calls, the Formant absences resting on page
titles, and the twelve walled or missing trees are where the errors could still flatter us, so the walled trees need
demo accounts before a pitch says "not on the shelf".

## Not checked

Every vendor named in the brief and the five named on 22 Oct are in the matrix. No other vendor was checked, and no
cell is claimed for any vendor outside it.
