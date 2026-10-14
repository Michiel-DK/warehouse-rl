-- report.py "Resolution mix": countable episodes per resolution.
SELECT resolution, count() AS episodes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
GROUP BY resolution
ORDER BY resolution ASC
