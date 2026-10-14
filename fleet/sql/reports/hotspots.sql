-- report.py "Hotspots": top 20 (zone, cell) by countable episode count, ties by zone then cell.
SELECT zone, JSONExtractInt(cell, 1) AS x, JSONExtractInt(cell, 2) AS y, count() AS episodes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
GROUP BY zone, x, y
ORDER BY episodes DESC, zone ASC, x ASC, y ASC
LIMIT 20
