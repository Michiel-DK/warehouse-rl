# wr-dev-competition-sweep-2 — 2026-10-18

Docs job, unattended. Second pass of `docs/COMPETITION.md`: added AutoStore, Symbotic, Körber/Infios, Zebra/Fetch,
6 River Systems (Ocado IA), GreyOrange; rewrote the closing section over all 14; adjusted the README prior-art
sentences (vendor count 8 -> 14, anticipation list + AutoStore/GreyOrange, Ocado congestion zones, walled list 6 -> 12).

## Result
- No new rank-A cell. None of the six has a public doc tree: GreyOrange (docs.greyorange.com, customer login) and
  Körber/Infios (ServiceNow + Academy, login) are walled; AutoStore, Symbotic, Ocado/6RS publish none; Zebra's
  docs.fetchrobotics.com does not resolve and techdocs.zebra.com has no robotics section (support.zebra.com NOT searched).
- New yes (B): AutoStore log upload ("Open API options to integrate with third-party data sources", Dematic rule);
  6 River/Ocado avoid-zones ("Zones adjust in real-time based on task volume, urgency, and congestion.").
- Five capabilities (location forecast, forecast grading, graded lessons, time-to-detect, graded decision ledger)
  still not found at rank A anywhere; absence rests on Formant + InOrbit only; 12/14 UNTESTED.
- Three borderline cells scored AWAY from presence (flattering us), named in the doc's direction test: AutoStore MTBF
  grid ranking (not a heatmap), GreyOrange hardware-agnostic control (not log upload, OTTO VDA 5050 rule), Infios
  "every action is tracked and auditable" (not a ledger: no outcome grade, orders/transport scope).
- Closing section: 8 sentences (limit 10).

## Search log (all 2026-10-18)

### AutoStore — 5 fetches, 1 search
1. https://www.autostoresystem.com/ — no docs/support/help/changelog links; Solution FAQs, product pages.
2. https://www.autostoresystem.com/system/cube-analytics — MTBF grid ranking, "Spot recurring fleet issues", "predict issues, surface sites...", "recommend clear actions", "Data updates every 5 minutes...", "Open API options to integrate with third-party data sources"; no docs/manual/release-notes links.
3. https://www.autostoresystem.com/sitemap.xml — FAILED, over 10 MB.
4. https://www.autostoresystem.com/hubfs/04%20Website%20Docs/01%20Spec%20Sheets/AutoStore-CubeAnalytics-Product-Sheet-EN.pdf — binary; text extracted locally with pdftotext: anomaly detection, health summaries, "module behavior across the Grid"; marketing (B).
5. https://www.autostoresystem.com/faq/cube-analytics — API "Allows access to raw real-time AutoStore log data."; no docs links.
- Search "AutoStore documentation portal service partner portal manual CubeAnalytics release notes" — no portal; news + product pages.

### Symbotic — 5 fetches, 1 search
1. https://www.symbotic.com/ — no docs/support links.
2. https://www.symbotic.com/solutions/ai-and-software/ — "informing facilities immediately of potential damage", "complex bot routing", WMS/ERP integration.
3. https://www.symbotic.com/resources/ — news/events hub, no docs.
4. https://www.symbotic.com/news-and-events/blog/ — no posts in fetch.
5. https://www.symbotic.com/solutions/robots/ — "AI supports continuous improvements through pattern recognition and human-lead training."
- Search "Symbotic customer portal documentation software release notes bot fault detection" — nothing relevant (job ads).

### Körber / Infios — 5 fetches, 1 search
1. https://www.infios.com/ — Customer Support, Knowledge Center; no docs link.
2. https://www.infios.com/en/customer-support — ServiceNow login portal; TM release-notes PDFs (transportation, not read); status page; trust centre.
3. https://www.infios.com/en/supply-chain-solutions/autonomous-mobile-robots — "feed a continuous stream of data ... back into the WMS"; nothing on the nine.
4. https://www.infios.com/en/supply-chain-solutions/infios-ai — "Predicts what's likely to happen and where it will hit.", "Every decision is explained.", "every action is tracked and auditable".
5. https://www.infios.com/en/knowledge-center/training-certification — Infios Academy, login, subscription only.
- Search "Infios WMS online help documentation docs.infios.com OR help.infios.com" — returned docs.infor.com (Infor, a different vendor); NOT USED.

### Zebra / Fetch — 6 fetches, 4 searches
1. https://www.zebra.com/us/en/products/autonomous-mobile-robots.html — links to TechDocs, support.zebra.com; no robot-software links.
2. https://techdocs.zebra.com/ — no robotics/AMR/FetchCore/Symmetry section.
3. https://docs.fetchrobotics.com/ — FAILED, ENOTFOUND.
4. https://www.zebra.com/us/en/about-zebra/newsroom/press-releases/2021/zebra-technologies-expands-fetch-robotics-portfolio-with-solution-to-optimize-fulfillment-workflows.html — returned newsroom index; release not in first 100k of 177k chars; not read further.
5. https://qac-downloads.zebra.com/cn/zh/about-zebra/newsroom/press-releases/2021/zebra-technologies-expands-fetch-robotics-portfolio-with-solution-to-optimize-fulfillment-workflows.html — FAILED, 404.
6. https://www.therobotreport.com/zebra-technologies-winding-down-fetch-based-mobile-robot-group/ — 12 Dec 2025, "Zebra Technologies is winding down its autonomous mobile robot (AMR) division." (C, context only).
- Search "Zebra Symmetry Fulfillment FetchCore documentation techdocs robot analytics" — snippet of 2021 press ("pick heatmap"), unverified.
- Search "Zebra Technologies robotics automation wind down Fetch AMR business 2025" — trade press on wind-down.
- Search "Zebra Fetch robotics FetchCore support documentation keep-out zones analytics heatmap site:zebra.com" and "Zebra Symmetry Fulfillment FetchCore analytics heatmap restricted areas zebra.com robotics software" — nothing beyond the 2021 snippet.
- NOT done: support.zebra.com search.

### 6 River Systems / Ocado IA — 7 fetches, 2 searches
1. https://6river.com/ — empty response.
2. https://6river.com/support/ — empty response.
3. https://ocadointelligentautomation.com/ — no docs/support/changelog; footer FAQ, glossary, Ocado Developer Platform.
4. https://ocadointelligentautomation.com/ocado-iq?hsLang=en — congestion-fed zones and routing, "forecasting dashboards", "spots errors in real-time", "tech-agnostic", "routinely releases software updates" (no notes linked).
5. https://ocadointelligentautomation.com/systems/chuck-amr?hsLang=en — paraphrased only by the fetch; nothing on the nine; no docs links. No quote used.
6. https://www.ocadodeveloperplatform.com/ — FAILED, ENOTFOUND.
7. https://ocadodeveloperplatform.com/ — FAILED, ENOTFOUND.
- Search "6 River Systems Chuck Ocado Intelligent Automation support documentation analytics" — acquisition news, no docs.
- Search "6 River Systems Chuck support help center knowledge base \"6river\" analytics dashboard" — irrelevant results.

### GreyOrange — 4 fetches, 2 searches
1. https://www.greyorange.com/ — no docs/support links.
2. https://www.greyorange.com/greymatter/technology/ — "Predictive analytics for anticipating bottlenecks and future demands", "A hardware-agnostic protocol layer...".
3. https://docs.greyorange.com/ — Knowledge Center (manuals, release notes), GO Customer Login.
4. https://www.greyorange.com/greymatter/solutions/ — "predicting demand and dynamically assigning resources".
- Search "site:docs.greyorange.com" — no indexed pages.
- Search "GreyOrange GreyMatter release notes analytics heatmap congestion prediction documentation" — trade press only (DeepNav, Foundry), not used.

## Gaps
- support.zebra.com not searched; AutoStore sitemap not read (too large); no demo accounts anywhere.
- No rank-A source for any added vendor; all their absences are UNTESTED.

SCHED_RESULT: OK competition sweep 2 — 14 vendors, 6 added all UNTESTED (no public doc trees), new yes(B): AutoStore log upload, Ocado congestion zones; commits e1eb433 + 8c61b5b pushed
