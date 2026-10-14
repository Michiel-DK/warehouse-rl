-- report.py "Cause mix": countable episodes per cause (a NULL cause prints as 'None', like str(None) in the report).
SELECT ifNull(cause, 'None') AS cause_label, count() AS episodes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
GROUP BY cause_label
ORDER BY cause_label ASC
