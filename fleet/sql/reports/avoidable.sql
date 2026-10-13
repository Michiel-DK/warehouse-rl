-- report.py "Avoidable": episodes flagged avoidable by the detector (near-tautological at 5 s steps: every closed
-- blocked_by_faulted episode) and their minutes, rounded to 2 decimals.
SELECT countIf(avoidable) AS episodes, round(sumIf(ifNull(avoidable_s, 0), avoidable) / 60, 2) AS minutes
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
