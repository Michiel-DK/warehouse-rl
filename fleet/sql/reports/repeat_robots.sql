-- report.py "Repeat robots": robots with at least 3 countable episodes, most first, ties by robot name.
SELECT robot, count() AS episodes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
GROUP BY robot
HAVING episodes >= 3
ORDER BY episodes DESC, robot ASC
