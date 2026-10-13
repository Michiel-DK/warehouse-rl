-- report.py "Episodes per event hour": countable episodes by the UTC hour of their start (epoch seconds of the hour).
SELECT intDiv(toInt64(`start`), 3600) * 3600 AS hour, count() AS episodes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
GROUP BY hour
ORDER BY hour ASC
