# Competition sweep, fourth pass (2026-10-22): three page capabilities on Formant, InOrbit, OTTO

Per-robot time budget, station-aware stall filter, blocking metric per shift. One fresh-context agent per vendor,
WebFetch/WebSearch only, cap 12 fetches + 3 searches (OTTO extended by 5 fetches because every docs page front-loads
~200k characters of navigation). Cells and evidence are in `warehouse-rl/docs/COMPETITION.md`; this file keeps the
fetch logs. Rules: `outward-claim-discipline`.

### Formant (pass 4)

Fetch log:
- https://docs.formant.io/llms.txt : index in full, 41 term matches, none for stuck, stall, zone, station, utilization
- https://docs.formant.io/docs/analytics.md : visualisation types only
- https://docs.formant.io/docs/getting-started-map-heatmap-overlay.md : location-density dwell proxy, "get stuck" use case, no exclusion
- https://docs.formant.io/docs/heatmap-module.md : location stream plus optional weight stream
- https://docs.formant.io/docs/incident-management.md : "uptime by fleet location", threshold events
- https://docs.formant.io/docs/faq-device-states.md : lifecycle states only
- https://docs.formant.io/docs/getting-started-events-and-notifications.md : event examples
- https://docs.formant.io/docs/faq-pull-reports-from-formant.md : event export only
- https://docs.formant.io/docs/getting-started-create-an-event-and-configure-notifications.md : full trigger-type list, no duration, geofence or station
- https://docs.formant.io/docs/custom-sql-queries-for-analytics.md : query_numeric table, per-day examples
- https://docs.formant.io/changelog : 404
- https://docs.formant.io/docs/fleet-observability.md : groups and dashboards
- search (formant.io) "robot utilization idle time stuck blocked fleet report" : generic fleet pages; snippet cites fleet uptime and incident rate reports
- search (formant.io) "utilization OR idle time OR blocked robots analytics" : teleop pages only; "blocked" = UDP ports

### InOrbit (pass 4)

Fetch log:
- https://www.inorbit.ai/docs (offset 0, general) : modes idle/charging/mission, max-time threshold, "for sec."
- https://developer.inorbit.ai/docs (offset 0, general) : `stateTransitions` timeline, missionKPI, incident `statusId`, `sustainedForSeconds`
- https://www.inorbit.ai/docs (offset 100000) : Mission KPIs, Time Capsule, incident webhook and Opsgenie
- https://developer.inorbit.ai/docs (offset 100000) : Traffic Zone Types nogo/soz, blocked threshold, isZoneBlocked, KPI fields, expression functions
- https://www.inorbit.ai/docs (offset 0, status/incident prompt) : threshold data sources, no zone in statuses
- https://developer.inorbit.ai/docs (offset 0, kinds prompt) : StatusDefinition expression/filter, rules, IncidentDefinition fields, no zone filter
- https://developer.inorbit.ai/docs (offset 100000, expressions/traffic/KPI prompt) : full function lists, SOZ pausing, KPI aggregations
- search "InOrbit robot utilization analytics idle charging time per robot report" (inorbit.ai) : modes and custom KPIs only
- search "InOrbit congestion blocked waiting robots traffic metric fleet analytics" (inorbit.ai) : zone blocked threshold, no fleet congestion KPI
- https://developer.inorbit.ai/docs (offset 0, Advanced Incidents verbatim) : `unableToNavigate`, Faulty Dock
- https://developer.inorbit.ai/docs (offset 100000, operators/charging zone/incident KPI) : operators, `charging` zone type, no incident KPI example
- https://www.inorbit.ai/product : "Optimize robot fleet utilization and meet SLAs..."
- https://www.inorbit.ai/intralogistics : "minimizing congestion and improving throughput."

### OTTO Motors (pass 4)

Fetch log:
- 30495-117801 concepts--fleet-analytics (offsets 0, 100000) : nav only; (offset 200000) : body in full, work history monitor, four named dashboards, utilisation hint, time-period filters only
- 30495-31068 reading-otto-fleet-analytics (offsets 0, 100000) : nav only; (offset 200000) : body in full, date-range and place filters, chart descriptions behind an info icon
- 30495-31048 viewing-fm-statistics (offsets 0, 100000) : nav only; (offset 200000) : body in full, 30-day job history, job counts, average run time, CSV export
- 30495-31050 exceptions (offsets 0, 100000) : nav only; (offset 200000) : intro body, alert feed, nuisance messages auto-excluded, last modified 2022-04-13
- 30495-127031 new-in-this-version (offsets 0, 100000) : nav only; (offset 200000) : body in full, release 2.36 (maps, planner, localization, VDA 5050), no analytics change
- 30495-126736 concepts--optimizing-your-fleet (offset 200000) : both sections in full; congestion via duration variation and traffic design, no metric
- search site:docs.ottomotors.com stuck OR blocked OR obstructed OR "waiting for traffic" vehicle : zero docs hits
- search site:docs.ottomotors.com utilization "vehicle state" OR "time in state" OR "idle time" OR "blocked time" : zero docs hits
- search "OTTO Fleet Analytics" docs.ottomotors.com utilization idle blocked "robot" statistics : marketing only (webinar, 2022 snapshot-playback release, "reducing idle time, and optimizing overall utilization")

