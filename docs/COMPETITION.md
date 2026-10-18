# Competition sweep: does anyone else ship what the fleet stuck analyser does? (2026-10-18)

Scope: 17 vendors, nine capabilities each. Every cell was checked on 2026-10-18 with WebFetch/WebSearch only
(no browser, no logins). The full fetch log, every URL with its result, is in
`laptop-scheduler/reports/wr-dev-competition-sweep.md`, not here. Rules: `~/.claude/skills/outward-claim-discipline`.

## How to read a cell

| value | meaning |
|---|---|
| `yes (A)` | shown in the vendor's own docs or manual (rank A) |
| `yes (B)` | shown only in first-party marketing copy: proves the claim, not the depth |
| `yes (C)` | shown only in a press release or trade press |
| `not found in docs (A)` | absent after the vendor's public doc tree was searched; the surfaces read are named per vendor |
| `UNTESTED` | doc tree behind a login, missing or unreachable, or only marketing was available. Absence on marketing pages is never written as "not found" |

Every cell is `verified@2026-10-18` unless it says otherwise. Quotes are short and verbatim from the page named. Some
quotes came through WebFetch's extraction model; the key `yes (A)` quotes for Formant, InOrbit, OTTO and GreyOrange
were re-fetched and re-confirmed by the main session.

## The nine capabilities (same bar for every vendor)

1. **Heatmap**: stalls, incidents, errors or stops shown by floor location (a map, or a per-place breakdown).
2. **Recurring-location trend**: which places keep coming back, not just incident counts over time.
3. **Forecast**: a predicted *future* location of stalls. Predictive maintenance of a robot part does not count.
4. **Forecast grading**: a measured hit rate of that forecast against what happened later.
5. **Graded lessons**: generated rules or recommendations whose truth is re-checked in a later window.
6. **Time-to-detect**: how long detection took (MTTD). MTTR alone does not count.
7. **Decision ledger**: the system's calls logged with an outcome grade. Incident acknowledge/resolve status does
   not count; it is noted as "incident status only".
8. **Avoid-zones / cost maps to routing**: zones or costs that routing uses. Each cell says whether the zones are
   drawn by hand or derived from incident data.
9. **Log upload for a client's own fleet**: vendor-agnostic ingest of another fleet's data for analysis.

Borderline cells were scored toward presence, i.e. against us (see the direction test at the end).

## Summary matrix

H = heatmap, T = trend, F = forecast, G = forecast grading, L = graded lessons, D = time-to-detect,
R = decision ledger, Z = avoid-zones to routing, U = log upload. `A`/`B`/`C` = yes at that rank, `n` = not found in
docs (A), `?` = UNTESTED.

| vendor | doc tree | H | T | F | G | L | D | R | Z | U |
|---|---|---|---|---|---|---|---|---|---|---|
| Formant | public | A | A | n | n | n | n | n | n | A |
| InOrbit | public | A | n | n | n | n | n | n | A | A |
| OTTO (Rockwell) | public (support centre: login) | A | A | n | n | n | n | n | A | n |
| GreyOrange | partly public (one customer's manuals) | A | ? | B | ? | ? | ? | ? | A | ? |
| MiR (Insights) | login | B | ? | ? | ? | ? | ? | ? | ? | ? |
| Locus Robotics | none (portal due Nov 2026) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Zebra / Fetch | none reachable | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Geek+ | partner login | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| 6 River Systems (Ocado) | none | ? | ? | ? | ? | ? | ? | ? | B | ? |
| Exotec | none | ? | ? | C | ? | ? | ? | ? | ? | ? |
| AutoStore | integration docs now 404 | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Symbotic | none | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Dematic | login | ? | ? | ? | ? | ? | ? | ? | ? | B |
| Körber (now Infios) | login (ServiceNow) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| Meili FMS | docs site has an expired TLS cert | ? | ? | ? | ? | ? | ? | ? | B | ? |
| BlueBotics ANT server | login | B | ? | ? | ? | ? | ? | ? | ? | ? |
| SYNAOS IMP | none; release notes only | ? | ? | ? | ? | ? | ? | ? | A | ? |

VDA 5050 ecosystem: github.com/VDA5050/VDA5050 and https://www.vda.de/en/topics/automotive-industry/vda-5050 name no
products. The VDMA AGV Mesh-Up pages name the master-control providers MHP and FLEXUS (https://www.vdma.eu/agv-mesh-up)
and KINEXON and SIEMENS (https://www.vdma.eu/kalender/-/event/view/77676); KION supplied the 2021 master control
(KION's own story, first-party). None of the four has a public doc tree we could reach (docs.kinexon.com does not
resolve; Siemens SIMOVE shows only training outlines; the FLEXUS SAP Store listing returned 403; no MHP product docs),
so all four are UNTESTED in every row. Meili, BlueBotics and SYNAOS were added from trade-press VDA 5050 lists, not
official ecosystem pages.

## Per vendor

### Formant
Surfaces read: footer docs link https://docs.formant.io (read); https://docs.formant.io/llms.txt (full index of about
400 pages, used as the title-level search of the whole tree); /docs/incident-management, /docs/analytics,
/docs/getting-started-map-heatmap-overlay.md, /docs/heatmap-module.md, /docs/ingest-from-the-python-cloud-sdk.md,
/docs/uploading-files-to-formant-cloud. Sitemap: 404. Changelog: /changelog 404, none found by search. Limit: the
absence cells rest on page titles in llms.txt plus the pages above, not a full-text read of all 400 pages.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A) | https://docs.formant.io/docs/getting-started-map-heatmap-overlay.md | "useful for spotting where robots repeatedly stop, get stuck, or dwell across a site"; a dwell-density proxy, not an incident layer |
| Recurring-location trend | yes (A) | same page | "repeatedly stop, get stuck" within a chosen time window; a comparison across windows is not described. Scored as yes to stay on the unflattering side |
| Forecast | not found in docs (A) | llms.txt, /docs/incident-management | the incident intro names "predicting, and preventing potential issues" as a goal; no feature or page for it |
| Forecast grading | not found in docs (A) | llms.txt | no prediction pages |
| Graded lessons | not found in docs (A) | llms.txt | no insights/AI pages |
| Time-to-detect | not found in docs (A) | https://docs.formant.io/docs/incident-management | MTTR only: "track time to resolution of incidents" |
| Decision ledger | not found in docs (A) | llms.txt | events and intervention requests only |
| Avoid-zones to routing | not found in docs (A) | llms.txt | no zone, geofence, keep-out or routing pages |
| Log upload | yes (A) | https://docs.formant.io/docs/ingest-from-the-python-cloud-sdk.md | "The primary way of ingesting arbitrary data that is not via the Formant agent is with the Cloud SDK"; live ingest, no historical log backfill described |

### InOrbit
Surfaces read: footer "Docs" https://www.inorbit.ai/docs (read in full); https://developer.inorbit.ai/docs (read in
full); https://www.inorbit.ai/sitemap.xml (first 100k of 442k characters). Changelog: none found; release news is
blog-only. help. subdomain: none found.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A) | https://www.inorbit.ai/docs | "Incidents highlights points on the map where incidents were logged by the robot during the time range."; per robot. "Position (heatmap)" shows time spent, not incidents |
| Recurring-location trend | not found in docs (A) | inorbit.ai/docs, developer.inorbit.ai/docs | only KPI sparklines ("recent trends for each KPI"); RobOps Copilot marketing says "uncover trends" (B, not location) |
| Forecast | not found in docs (A) | same | Space Intelligence marketing: "proactively identify and resolve incidents" (B, no location forecast) |
| Forecast grading | not found in docs (A) | same | none |
| Graded lessons | not found in docs (A) | same | Copilot: "Get details on anomalies or reported incidents"; marketing "actionable insights", ungraded |
| Time-to-detect | not found in docs (A) | https://www.inorbit.ai/docs | the "for sec." field is a configured threshold delay, not measured latency |
| Decision ledger | not found in docs (A) | same | incident status only: "Select a severity level between SEV0 (most serious) and SEV3 (least serious)" |
| Avoid-zones to routing | yes (A), drawn by hand | https://developer.inorbit.ai/docs (Traffic Zones) | "The nogo rule pauses any robot that enters the zone polygon."; "Polygon coordinates are normally obtained when drawing the zone in the app". A pause rule, not a routing cost |
| Log upload | yes (A) | https://developer.inorbit.ai/docs | "A connector is a custom component that connects a third-party system to InOrbit."; live ingest from mixed fleets, no historical file upload |

### OTTO Motors (OTTO by Rockwell Automation)
Surfaces read: footer "Tech Docs" https://docs.ottomotors.com (public, release 2.36): about-fleet-manager (nav),
concepts--fleet-analytics, reading-otto-fleet-analytics, concepts--optimizing-your-fleet, viewing-fm-statistics,
exceptions, zones, creating-zones, assumed-cost-zone, using-map-features. Changelog:
https://docs.ottomotors.com/en/30495-127031-new-in-this-version.html (read). help.ottomotors.com: login (Confluence).
docs sitemap.xml: empty. In-site search needs JavaScript, so not run. Limit: pages are 200k+ characters; nav plus the
pages above were read, not every page.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A), per-place breakdown, no map | https://docs.ottomotors.com/en/30495-117801-concepts--fleet-analytics.html | "Task failures can be filtered by robot and root cause, as well as correlated with endpoint ("place")"; a "FAILED Task Place Breakdown" dashboard. Marketing (B) adds "areas in the facility ... slow or failure prone" (https://ottomotors.com/resources/webinars/from-data-to-insight-using-fleet-analytics-for-continuous-optimization-webinar/) |
| Recurring-location trend | yes (A) | same page | "The frequency and contributing factors behind recurring events."; place breakdown over a chosen period, data "from periods of years"; a per-place time series is not described |
| Forecast | not found in docs (A) | concepts, reading and optimizing pages; release notes 2.36 | "heatmap", "predict" and "forecast" absent from the analytics page |
| Forecast grading | not found in docs (A) | same | none |
| Graded lessons | not found in docs (A) | https://docs.ottomotors.com/en/30495-126736-concepts--optimizing-your-fleet.html | static human-written best practice only |
| Time-to-detect | not found in docs (A) | https://docs.ottomotors.com/en/30495-31048-viewing-fm-statistics.html | job counts and "Average time that jobs take to execute"; no MTTD or MTTR |
| Decision ledger | not found in docs (A) | https://docs.ottomotors.com/en/30495-31050-exceptions.html | "The Exceptions menu displays relevant robot alerts"; no graded calls |
| Avoid-zones to routing | yes (A), drawn by hand | https://docs.ottomotors.com/en/30495-30725-creating-zones.html | "Tap or click anywhere on the map to draw a rectangular Zone."; Assumed Cost Zones "assign a cost to specific areas in a facility to help direct traffic". Nothing derives zones from failures |
| Log upload | not found in docs (A) | release notes 2.36 | VDA 5050 control interop only, no ingest of another fleet's logs |

### GreyOrange (GreyMatter, Watch Tower)
Surfaces read: https://docs.greyorange.com (Knowledge Center; employee and customer login for most content); its
sitemap.xml lists 5 public publications, mostly one customer's (APOTEK) Watch Tower manuals, of which 9 pages and
the 7.1.0 version history were read. Footer docs link: none. support./help. subdomains: HTTP 530. Absence cells are
UNTESTED because the public part is one customer's subset.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (A) | https://docs.greyorange.com/articles/?_escaped_fragment_=gm-watch-tower-relay-for-apotek/tower-rtp-using-the-highlights-feature-1 | "Identify areas with barcode issues displayed on the map."; "Locate and identify areas with blocked Put operations on the map." |
| Recurring-location trend | UNTESTED | https://docs.greyorange.com/articles/?_escaped_fragment_=gm-watch-tower-relay-for-apotek/tower-rtp-system-alert-manager | generic: "valuable for analyzing trends, identifying recurring issues"; CSV export, no location trend shown |
| Forecast | yes (B), location not stated | https://www.greyorange.com/greymatter/technology/ | "Predictive analytics for anticipating bottlenecks and future demands"; a claim, depth unknown |
| Forecast grading | UNTESTED | none | none |
| Graded lessons | UNTESTED | none | none |
| Time-to-detect | UNTESTED | System Alert Manager page | SLA threshold alerts ("breached SLA of 1m"), not detection latency |
| Decision ledger | UNTESTED | System Alert Manager page | incident status only: "maintains a history of alerts and their resolutions" |
| Avoid-zones to routing | yes (A), drawn by hand | https://docs.greyorange.com/articles/?_escaped_fragment_=gm-watch-tower-relay-for-apotek/tower-rtp-manage-grid-barcodes-1 | "Select Block a Path or Block an Area, block time duration"; manual |
| Log upload | UNTESTED | greymatter/technology | "hardware-agnostic protocol layer" is device control, not log ingest |

### MiR (MiR Fleet / MiR Insights)
Surfaces read: https://supportportal.mobile-industrial-robots.com (login); /support-portal (marketing);
sitemap.xml (index) and __sitemap__/en.xml (first 100k of 733k). Changelog: not found publicly. All absences UNTESTED.

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (B) | https://mobile-industrial-robots.com/products/software/mir-insights | "Use heatmaps and time-series analysis to pinpoint bottlenecks and optimize workflows."; activity and traffic, not explicitly stalls |
| Recurring-location trend | UNTESTED | same | "Compare metrics over time", not location |
| Forecast | UNTESTED | same | none |
| Forecast grading | UNTESTED | none | none |
| Graded lessons | UNTESTED | same | "AI Search" for documentation, ungraded |
| Time-to-detect | UNTESTED | none | none |
| Decision ledger | UNTESTED | none | none |
| Avoid-zones to routing | UNTESTED | none | not found by search; docs behind login |
| Log upload | UNTESTED | press, newequipment.com | "MiR Insights reads data from MiR Fleet" (C); MiR-only |

### Locus Robotics (LocusONE, LocusHub)
Surfaces read: footer /support/ ("New Customer Experience Portal Is Expected in November 2026"; email/phone today);
/docs/ 404; docs./help. subdomains: TLS failure; sitemap.xml read, no docs URLs; changelog: none. Every cell UNTESTED.
Marketing and press notes: "forecast demand" (https://locusrobotics.com/platform/locusone/, B, demand not location);
LocusHub "automatically identifies pain points and workflow bottlenecks" and "proactive recommendations"
(https://locusrobotics.com/news/locus_robotics_unveils_locushub, C, no re-check shown); data "sliced according to zone"
(same, C). An "Open Work Heat Map" appeared only in a search snippet (unverified; it maps open picks, not stalls).

### Zebra / Fetch Robotics (Symmetry, FetchCore)
Surfaces read: docs.zebra.com and techdocs.zebra.com (no robotics entries); support.zebra.com (empty shell);
mobile-robots support portal URL 404; Symmetry product pages show generic Workcloud content; docs.fetchrobotics.com
does not resolve; fetchrobotics.com redirects to skild.ai. Every cell UNTESTED. Note: a 2021 release mentions "a pick
heatmap" (https://investors.zebra.com/news-and-events/news/news-details/2021/Zebra-Technologies-Expands-Fetch-Robotics-Portfolio-with-Solution-to-Optimize-Fulfillment-Workflows/default.aspx, C),
which maps picks, not stalls. Trade press (C) reports Zebra decided in Dec 2025 to exit robotics automation.

### Geek+ (RMS, IOP)
Surfaces read: footer (no docs link); /company/service-support (marketing); /resources/knowledge-base (3 educational
articles); /faqs; Partner Portal gpp.geekplus.com (login; "product documentation" after approval); docs.geekplus.com
does not resolve; sitemap first 100k of 8.4M characters; changelog: none. Every cell UNTESTED. Notes: decision ledger
incident status only (B): "acknowledge, assign, and track the status of alerts" (https://www.geekplus.com/software);
"Predictive alerts" and predictive maintenance (https://www.geekplus.com/faqs, B), no location; RMS speaks VDA 5050
(control, not analysis).

### 6 River Systems (now Ocado Intelligent Automation)
Surfaces read: 6river.com (empty body; sitemap lists only /lander); help.6river.com DNS failure; support.6river.com
empty; docs.6river.com TLS mismatch; ocadointelligentautomation.com home, /faq, /services, /ocado-iq,
/systems/chuck-amr, sitemap first 100k of 582k; changelog: none. Every cell UNTESTED except:

| capability | cell | source | evidence |
|---|---|---|---|
| Avoid-zones to routing | yes (B), derived from live congestion, not incidents | https://ocadointelligentautomation.com/ocado-iq | Smart Routing "maps the fastest route in real-time, factoring in aisle activity, congestion, and task urgency." |

### Exotec (Skypod, Deepsky software)
Surfaces read: footer (no docs link); https://www.exotec.com/llms.txt; sitemap.xml and page-sitemap.xml (marketing only);
docs./support. subdomains do not resolve; changelog: none. Every cell UNTESTED except:

| capability | cell | source | evidence |
|---|---|---|---|
| Forecast | yes (C), location not stated | https://www.robotics247.com/article/exotec_adds_three_modular_technologies_skypod_warehouse_automation/Machine_Learning | "The software proactively adapts routes in case of potential failures"; a claim about anticipating failures, depth unknown |

The brief's "Exotec Deus" does not exist; Exotec's software is Deepsky.

### AutoStore (CubeAnalytics, Router)
Surfaces read: homepage nav and footer (no docs link); interface.autostoresystem.com (integration docs: /docs,
/changelog and subpages 404, root is a stub); docs./support. do not resolve; help. redirects to TeamViewer; sitemap
over 10 MB, unreadable. Every cell UNTESTED. Marketing notes (B), https://www.autostoresystem.com/system/cube-analytics:
"Ranks Grids by mean time between failures (MTBF)" and "predict issues, surface sites most in need of attention"
(whole grids or sites, not floor locations); "recommend clear actions" (ungraded); predictive maintenance listed.
FAQ: "raw real-time AutoStore log data" (own logs only, https://www.autostoresystem.com/faq/cube-analytics). Unverified
lead: an old Log Publisher event stream, now 404.

### Symbotic
Surfaces read: footer (no docs link); sitemap.xml and page-sitemap.xml (47 URLs, none for docs); site search
"support": zero results; docs./support. do not resolve; changelog: none. Every cell UNTESTED. Marketing mentions
"complex bot routing" and damage detection (https://www.symbotic.com/solutions/ai-and-software/, B), neither a match.

### Dematic (KION)
Surfaces read: footer (no docs link); docs.dematic.com (login); support.dematic.com does not resolve;
myaccount.dematic.com (login); sitemap.xml 404; changelog: none; iQ InSights has no current product page. Every cell
UNTESTED except:

| capability | cell | source | evidence |
|---|---|---|---|
| Log upload | yes (B), multi-vendor data, not a log upload as such | https://www.dematic.com/en-us/software/command-center/ | "Dematic Command Center is vendor-agnostic."; "Consolidates data from all automated systems" |

Marketing also lists "Historical insight and root-cause analysis" and predictive maintenance (B), no location forecast.

### Körber Supply Chain Software (now Infios)
Surfaces read: koerber-supplychain-software.com redirects to infios.com; footer: /en/customer-support only, which
points to a ServiceNow login; sitemap.xml read in full, no docs or fleet URLs; release notes exist only for the
transport product. Every cell UNTESTED. The robotics page lists partner AMRs; no own fleet manager page was found.

### Meili Robots (Meili FMS)
Surfaces read: footer "Documentation" https://docs.meilirobots.com (TLS certificate expired, unreadable);
api.meilirobots.com (JavaScript shell); /faqs, /product, /resources (marketing). Changelog: none. Every cell UNTESTED
except:

| capability | cell | source | evidence |
|---|---|---|---|
| Avoid-zones to routing | yes (B), not said how drawn | https://www.meilirobots.com/product | "various types of zones (e.g. for charging or restrictions)" |

### BlueBotics (ANT server)
Surfaces read: footer "Support" support.bluebotics.com (login); footer "Academy" (loads empty); marketing pages;
brochure PDFs unreadable. Changelog: none. Every cell UNTESTED except:

| capability | cell | source | evidence |
|---|---|---|---|
| Heatmap | yes (B), by vehicle or station | https://www.antdriven.com/ant-server-agv-amr-fleet-manager | "Errors and alarms (i.e. displayed on a heat map) – useful for identifying problematic vehicles and/or stations" |

### SYNAOS (Intralogistics Management Platform)
Surfaces read: footer (no docs link); docs./support. do not resolve; /docs 404; sitemap.xml read in full; release notes
index plus 8 of 11 release notes (2024.2, 2024.1, 1.8 to 1.13). There is no doc tree, only release notes, so absences
are UNTESTED, not "not found". Every cell UNTESTED except:

| capability | cell | source | evidence |
|---|---|---|---|
| Avoid-zones to routing | yes (A), drawn by hand | https://www.synaos.com/en/blog/release-notes-q3-2023-release-1-11 | "All affected edges (from all navigation graphs) that are crossed by the routing manipulator are avoided"; placed in the Shop Floor Editor |

Near-miss: release 2024.2 adds "A new column shows how long tasks have been stuck in their current status"
(https://www.synaos.com/en/blog/release-notes-imp-2024-2), which is stuck duration, not time-to-detect.

## What changed against the README's 13 Oct note

- "Formant sells ... trend analysis of recurring problems" came from a marketing read. The docs show something more
  specific: a heatmap overlay for "where robots repeatedly stop, get stuck" (rank A). It stays a presence, now with a
  better source.
- "The parts ... not on the shelf: a vendor-agnostic plugin that reads the files a client already has": Formant's
  Cloud SDK and InOrbit's connectors are documented vendor-agnostic ingest (rank A). Only *historical file* upload was
  not found, so the "vendor-agnostic" half of that sentence is contradicted and is dropped from the README.
- The 15 Oct InOrbit and Formant facts were re-confirmed at rank A on 2026-10-18.

## What this means for our claim

Of our nine capabilities, four are documented at rank A by at least one vendor: a stall or incident map (Formant,
InOrbit, OTTO, GreyOrange), a recurring-location view (Formant, OTTO, both within one chosen window), hand-drawn avoid
or cost zones used by routing (OTTO, SYNAOS, GreyOrange, InOrbit), and vendor-agnostic live ingest (Formant, InOrbit).
A location-unspecified forecast of bottlenecks or failures is claimed in marketing or press by GreyOrange (B) and Exotec
(C), with no depth shown. Not found in any doc tree searched: forecast grading, persistence-graded lessons,
time-to-detect reporting, a graded decision ledger, and zones derived from incident data instead of drawn by hand.
That absence rests on three public doc trees only (Formant, InOrbit, OTTO). The other fourteen vendors, including all
the large goods-to-person and AMR players, keep their docs behind a login or publish none, so every one of those rows is
UNTESTED. The market-wide "nobody grades their forecasts" is therefore not established. It is true for three vendors and
unknown for fourteen. Direction test: borderline cells were scored as presence (Formant's within-window repeat stops
counted as a trend, OTTO's place breakdown counted as a heatmap, GreyOrange's bottleneck claim counted as a forecast),
so the errors we know of point against us, not for us. The remaining flattering risk is the Formant absences, which rest
on llms.txt page titles rather than a full-text read, and the fourteen login-walled trees, where a demo account would be
needed before the pitch says "not on the shelf".
