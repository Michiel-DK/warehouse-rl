# Competition sweep, third pass (2026-10-22): Amazon Robotics, Hai Robotics, Brightpick, Vecna Robotics, Seegrid

Five vendors, one fresh-context agent each, WebFetch/WebSearch only, cap 12 fetches + 4 searches per vendor. The cells
and evidence are in `warehouse-rl/docs/COMPETITION.md`; this file keeps the fetch logs. Rules: `outward-claim-discipline`.

### Amazon Robotics

Fetch log:
- https://www.amazonrobotics.com/ : 301 to amazon.jobs internal team page
- https://amazon.jobs/en/internal/teams/amazon-robotics : 307 to idp.federate.amazon.com OAuth login
- search "Amazon Robotics products sold to external customers documentation fleet management software" : only AWS IoT RoboRunner (2021-22) and a rank-C profile saying Amazon does not sell robotics to third parties
- search "site:amazonrobotics.com" : zero amazonrobotics.com hits, nine amazon.jobs careers pages
- https://www.amazon.jobs/teams/amazon-robotics : careers page, no docs/support/changelog links
- https://www.aboutamazon.com/news/operations/amazon-robotics-robots-fulfillment-center : marketing, no monitoring, heatmap, forecast or routing claims
- https://docs.aws.amazon.com/iotroborunner/latest/dev/what-is-iotroborunner.html : resolves to the AWS docs index, RoboRunner absent
- https://aws.amazon.com/iot-roborunner/ : HTTP 404
- search "\"AWS IoT RoboRunner\" end of support discontinued" : no official AWS notice; Classmethod 2024-03-23 reports the service retired, CLI client removed in 2.15.30
- https://www.aboutamazon.com/news/operations/amazon-million-robots-ai-foundation-model : DeepFleet marketing, congestion quotes, internal data, no doc links

### Hai Robotics

Fetch log:
- https://www.hairobotics.com/ : footer has no docs or support link, Partner Portal login only
- https://www.hairobotics.com/sitemap.xml (two parts) : no doc or manual URLs
- https://www.hairobotics.com/support : 404
- search "Hai Robotics HaiQ software user manual documentation pdf fleet management heatmap alarm" : only a VCP hardware manual on device.report
- https://www.hairobotics.com/solutions/haiq-software : marketing
- https://www.hairobotics.com/download-center : form-gated brochures and case studies
- https://www.hairobotics.com/faq-glossary : event FAQs and glossary
- https://device.report/m/23bfa0b3... (VCP manual) : 403
- search site:hairobotics.com documentation OR manual OR "user guide" OR "release notes" : no hits
- search "Hai Robotics" HaiQ "data platform" OR dashboard OR heatmap OR alarm : third-party only
- https://www.hairobotics.com/blog/creating-new-era-flexible-and-data-driven-automated-warehouses-haiq : marketing
- https://www.hairobotics.com/solutions/information-security-support : PSIRT page
- search site:hairobotics.com "digital twin" platform HaiQ news : no hairobotics.com hits
- https://docs.hairobotics.com/ : DNS not found
- https://www.businesswire.com/news/home/20250310437180/en : 403

### Brightpick

Fetch log:
- https://www.brightpick.ai/ : footer has only a "Documentation" link
- https://www.brightpick.ai/sitemap.xml : index of 8 sub-sitemaps, nothing flagged
- search "Brightpick Intuition software documentation support help center manual" : no doc portal
- https://brightpick.ai/documentation/ : legal documents index only
- https://brightpick.ai/page-sitemap.xml : 45 pages, no docs-like URL
- https://brightpick.ai/analytics/ : dashboards, bottleneck isolation, early warning signals
- https://brightpick.ai/intuition-ai/ : Time-Space Planning predicts fleet activity; per-pick record
- https://brightpick.ai/ai-and-software/ : same copy as intuition-ai
- https://brightpick.ai/faq/ : 40 questions; dashboards, failure logging, WMS/ERP APIs, 99.5% uptime
- https://docs.brightpick.ai/ : DNS not found
- https://support.brightpick.ai/ : DNS not found
- search site:brightpick.ai "Analytics dashboard heatmap robot errors stuck monitoring" : no heatmap; two blog posts
- search site:brightpick.ai release notes / changelog : none; press releases only
- https://brightpick.ai/resources/meet-brightpick-intuition-the-software-brain-behind-our-robots/ : proactive alerts, operational suggestions
- https://brightpick.ai/resources/how-amrs-work-in-real-warehouse-operations/ : predicting robot movements, proactive route planning

### Vecna Robotics

Fetch log:
- https://www.vecnarobotics.com/ : no docs, support or changelog link; portal and partner login only
- https://www.vecnarobotics.com/sitemap.xml : 7 sub-sitemaps, none doc-like
- search "Vecna Robotics Pivotal fleet software documentation support portal knowledge base release notes" : press only, no doc tree
- https://www.vecnarobotics.com/portal/ : marketing homepage content, no login form, no docs
- https://www.vecnarobotics.com/the-vecna-system/pivotal-software-suite/ : "heatmaps" quote; modules listed; no doc links
- https://www.vecnarobotics.com/the-vecna-system/pivotal-command-center/ : 24/7 monitoring, teleoperation; no MTTD, no logs
- https://www.vecnarobotics.com/page-sitemap.xml : 105 URLs, none docs-like
- https://www.vecnarobotics.com/login/ : HTTP 500
- https://www.vecnarobotics.com/the-vecna-system/pivotal-autonomous-navigation/ : rules of the road, congestion rerouting; no zones or cost map
- search "Vecna Robotics \"Beacon\" software fleet" : thin, unverifiable
- search "site:vecnarobotics.com Pivotal Insights heatmap analytics dashboard" : zero Vecna results
- https://vecnarobotics.com/?p=1202 : "Make your business go", uptime claims only
- https://vecnarobotics.my.site.com/partner/s/login/ : Salesforce login template
- https://www.vecnarobotics.com/resources-sitemap.xml : 155 URLs, 2 flagged by title, not fetched

### Seegrid

Fetch log:
- https://seegrid.com/ : footer, no docs or help links; names Fleet Central, Supervisor, Fleet Geek; "Palion" absent
- https://seegrid.com/sitemap.xml : index, 5 child maps, no docs-like map
- https://support.seegrid.com/ : 301 to https://seegrid.kcenter.usu.com/helpcenter
- https://seegrid.kcenter.usu.com/helpcenter : DNS not found
- https://seegrid.com/fleet-central/ : marketing; monitoring, VDA 5050, intersection traffic; no doc links
- https://seegrid.com/fleet-central/supervisor/ : marketing; map/status views, alerts, ETA projections, traffic cop
- https://seegrid.com/customer-resources/ : support email and LMS link, customers-only wording
- https://seegrid.docebosaas.com/learn : renders "Loading", treated as login
- https://seegrid.com/page-sitemap.xml : 37 pages, none docs-like
- https://seegrid.com/service-and-support/ : service copy, no portal or doc links
- https://hub.seegrid.com/news/seegrid-introduces-fleet-geek-data-analytics-software-to-complement-its-autonomous-mobile-robots : 404
- https://hub.seegrid.com/ : 301 to seegrid.com
- search "Seegrid Fleet Central documentation manual Fleet Geek/Supervisor user guide" : no Seegrid hits
- search "Seegrid \"Fleet Central\" heatmap/analytics/release notes stalls incidents" : one materialhandling247 listing (rank C)
- search "Seegrid \"Fleet Geek\" analytics dashboard Supervisor features manual" : 2021 trade coverage only
- search (seegrid.com, hub.seegrid.com) zone / restricted area / heat map / blocked / stuck : surfaced the Supervisor "Caution Tape" press release (unfetched)

