# wr-dev-competition-sweep — 2026-10-18 (run 2, eight-vendor brief)

Unattended docs job. Output: `warehouse-rl/docs/COMPETITION.md` and the README prior-art paragraph (line 510).
Commits on master, pushed: 0038119 (run 1, earlier today, had not been pushed), e51115b and d4dd8b3 (this run;
d4dd8b3 applies the review fixes below). Wall clock: approximately 45 min of the 100 budgeted (estimate, not timed).

## What happened
- Run 1 (12:25 today) had already committed a COMPETITION.md for a wider brief (17 vendors plus VDA 5050 providers,
  `yes (C)` cells, all-UNTESTED vendors written as prose) but never pushed it. This run rebuilt the doc to the
  current brief rather than shipping run 1 as is:
  - exactly eight vendors;
  - nine rows per vendor, each with its own URL and `verified@2026-10-18`;
  - only the four allowed cell values;
  - "Not checked" at the end;
  - closing section of eight sentences.
- Every rank-A and rank-B quote in the doc was re-fetched in this session; none is carried over from run 1.
- README: a header plus three sentences and the link. The 15 Oct facts are kept: InOrbit Incidents/Position/SEV, and
  Formant incident management covering threshold events, timelines and dashboards. The 13 Oct clause "vendor-agnostic
  plugin ... not on the shelf" was dropped because Formant's Cloud SDK and InOrbit's connectors contradict it at
  rank A. The Sprint 8 "measured loop" clause, an unchecked absence claim, was also dropped.

## Result
- Documented at rank A by at least one vendor:
  - heatmap: Formant, InOrbit, OTTO; MiR at B;
  - recurring-location trend: Formant, OTTO, both borderline;
  - hand-drawn avoid or cost zones: InOrbit, OTTO;
  - vendor-agnostic ingest: Formant, InOrbit; Dematic at B.
- Not found in the two fully searchable doc trees (Formant, InOrbit), nor on OTTO's public pages: location forecast,
  forecast grading, graded lessons, time-to-detect, graded decision ledger, and incident-derived zones.
- OTTO (help centre login, /support 404), MiR, Locus, Geek+, Exotec and Dematic: every absence row is UNTESTED.
- InOrbit recurring-location trend: flipped to yes (A), per robot, within one window. It is the same kind of view as
  Formant's, which was already scored yes.

## Judgement calls (operator may overrule)
- Rank-C press is not an allowed cell value. Exotec's forecast claim (robotics247, Jan 2023) is therefore UNTESTED,
  with the quote kept in the evidence column.
- Direction test: dropping GreyOrange (A heatmap, B "anticipating bottlenecks") and SYNAOS (A avoid-zones) under the
  eight-vendor scope removes presence evidence only. That is flattering, so the closing section names the Forecast
  gap as scope plus walled docs, and cites GreyOrange from run 1 as outside the table.
- Borderline cells scored as presence, against us:
  - Formant within-window repeat stops → trend;
  - OTTO "correlated with endpoint" → heatmap;
  - OTTO "recurring events" → trend;
  - Dematic Command Center "vendor-agnostic", "collects scattered data" → log upload (B).
- RESOLVED: OTTO's six absence rows are now UNTESTED. help.ottomotors.com is a Confluence login and
  ottomotors.com/support returns 404, so the brief's support surface could not be searched.
- Formant absences rest on llms.txt page titles plus 4 pages, not a full-text read. formant.ai/support is a contact
  page with no help centre. Changelog: only an SDK changelog page exists (read), with no entries on these topics.
- Every `not found in docs (A)` row now names the surfaces read. The GreyOrange clause was removed from the closing
  section: it was out of scope and not re-fetched.
- In run 1, the "FAILED Task Place Breakdown" dashboard name was quoted for OTTO. This run did not re-confirm it (the
  page read from offset 170000 does not show it), so it is no longer in the doc.

## Contradiction sweep (not edited; docs page wording is the operator's)
- `docs/overview/index.html:152` "most fleet managers show the stop, not the pattern". This is contradicted where we
  could look: Formant (repeat-stop heatmap), OTTO (failures by place, recurring events) and InOrbit (incidents map)
  show location patterns at rank A. "This one grades its own calls" holds for 3 vendors and is UNTESTED for 5.
- `docs/overview/index.html:138` "Robots get stuck. Nobody knows why." This is a headline, not a market claim, but
  it overstates against OTTO's "filtered by robot and root cause".
- `docs/SCOPE.md` "nobody has published this curve for the RWARE family" is a literature claim, not covered here.

## Search log (this run; every URL, with result)
Formant (10):
1. WF docs.formant.io/docs/getting-started-map-heatmap-overlay.md: ok, "repeatedly stop, get stuck, or dwell"; selected time range only
2. WF docs.formant.io/docs/incident-management: ok, "predicting, and preventing" as a goal; "track time to resolution"; no MTTD, no severity
3. WF docs.formant.io/llms.txt: ok, 27 keyword titles; none with predict/forecast/insight/anomaly/zone/geofence/route/navigation/MTTD/release; "SDK Versions, Distributions, Changelogs, and Licensing" present
4. WF formant.io/support: 308 redirect to formant.ai/support
5. WF formant.ai/support: ok, contact page (book a call, email), no docs/help/changelog links
6. WF docs.formant.io/docs/ingest-from-the-python-cloud-sdk.md: ok, "ingest directly without requiring an agent"; backfill not stated
7. WS "Formant changelog release notes": no Formant results
8. WF docs.formant.io/docs/heatmap-module.md: ok, location over a time range; no incidents, stops or comparisons
9. WF docs.formant.io/llms.txt (again): URL of the SDK changelog page
10. WF docs.formant.io/reference/sdk-versions-distributions-changelogs-and-licensing.md: ok, SDK changelog, no entries on these topics, links to repos

InOrbit (5):
1. WF www.inorbit.ai/docs (0–100k): ok, Incidents overlay, Position (heatmap), SEV0–SEV3, "for sec." threshold; support@ and FAQ links; no changelog
2. WF developer.inorbit.ai/docs (0–100k): ok, connector definition; no predict/forecast/trend/MTTD/changelog
3. WF www.inorbit.ai/support: ok, support-plan marketing; links to both doc trees, FAQ, Discord, login; no changelog
4. WF www.inorbit.ai/docs (100k–136k): ok, KPI sparklines "recent trends", fleet summary trends by software version, Opsgenie sync, incident webhooks
5. WF developer.inorbit.ai/docs (100k–198k): ok, "The nogo rule pauses any robot that enters the zone polygon"; "Polygon coordinates are normally obtained when drawing the zone in the app"

OTTO (11):
1. WF docs.ottomotors.com concepts--fleet-analytics (@170000): ok, "correlated with endpoint", "recurring events", "periods of years"; no heatmap/predict/forecast/MTTD
2. WF creating-zones (@170000): ok, "Tap or click anywhere on the map to draw a rectangular Zone"; no derived zones
3. WF new-in-this-version (@170000): ok, five features (map size, graph planner, localization, VDA 5050 V2.1); no analytics, prediction or ingest
4. WF viewing-fm-statistics (@170000): ok, Total/Successful/Aborted Jobs and Average Run Time; no MTTD or MTTR
5. WF exceptions (@170000): ok, "displays relevant robot alerts"; no decision log
6. WS "Assumed Cost Zone" docs.ottomotors.com: no relevant results
7. WF help.ottomotors.com: Confluence 6.2.0 login
8. WF creating-zones (0–100k, nav): ok, zone and analytics link list; no "Predict" link in the visible nav
9. WF assumed-cost-zone (@170000): ok, "assign a cost to specific areas in a facility to help direct traffic"; manual setup only
10. WF reading-otto-fleet-analytics (@170000): ok, "only the selected place"; no heatmap/predict/recommendations/import
11. WF ottomotors.com/support: HTTP 404

MiR (2):
1. WF mobile-industrial-robots.com/products/software/mir-insights: ok, "Use heatmaps and time-series analysis to pinpoint bottlenecks"; "Compare metrics over time"; cloud API export; no docs link
2. WF supportportal.mobile-industrial-robots.com: sign-in form, nothing public

Locus (2):
1. WF locusrobotics.com/support/: ok, email and phone; "We're preparing a redesigned portal"
2. WF locusrobotics.com/platform/locusone/: ok, "forecast demand", "recommend actions"; no docs link

Geek+ (4):
1. WF geekplus.com/software: ok, "acknowledge, assign, and track the status of alerts", "identify operational bottlenecks", "Predictive alerts", zone task distribution; no docs link
2. WF gpp.geekplus.com: 301 redirect
3. WF gpp.geekplus.com/static/gppclient: 301 redirect
4. WF gpp.geekplus.com/static/gppclient/: JS shell titled "Geek+ Partner Portal", nothing public

Exotec (4):
1. WF exotec.com/llms.txt: ok, no docs/help/changelog URLs; support page and Deepsky page listed
2. WF robotics247.com Exotec article: ok, 19 Jan 2023, "proactively adapts routes in case of potential failures"
3. WF exotec.com/warehouse-automation-support/: ok, marketing only, "Contact Us"
4. WF exotec.com/system/warehouse-optimization-software/: ok, dashboards; control centres "detect and troubleshoot 90% of issues remotely"; no docs link

Dematic (4):
1. WF docs.dematic.com: Titania Delivery login
2. WF dematic.com/en-us/software/command-center/: ok, "vendor-agnostic", "collects scattered data into a unified view", "root-cause analysis", "where performance is heading next"; customer portal login link
3. WS "Dematic iQ InSights analytics heatmap bottleneck predictive": trade press only (mhwmag iQ 2.5 Material Flow Analysis, mhlnews, dcvelocity); no first-party page
4. WF mhwmag.com iQ 2.5 article: HTTP 403, unverified

## Gaps
- No demo or login accounts, so 5 of 8 vendors are UNTESTED on every absence row.
- Partial reads:
  - Formant: titles plus 4 pages;
  - OTTO: navigation (first 100k) plus 7 pages, help centre is a login (rows UNTESTED);
  - InOrbit: /news not read.
- Quotes pass through WebFetch's extraction model. They are verbatim as returned, not checked against raw HTML.

SCHED_RESULT: OK competition sweep, 8 vendors x 9 capabilities, docs/COMPETITION.md + README pushed (d4dd8b3, 229f70e); absences established for Formant+InOrbit only, 6 of 8 vendors' absence rows UNTESTED
