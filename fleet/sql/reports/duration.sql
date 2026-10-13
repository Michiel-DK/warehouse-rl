-- report.py "Duration": nearest-rank p50 / p95 of duration_s (the ceil(q * n)-th smallest, like report.nearest_rank).
WITH arraySort(groupArray(duration_s)) AS d, length(d) AS n
SELECT if(n = 0, NULL, d[greatest(1, toUInt64(ceil(0.5 * n)))]) AS p50,
       if(n = 0, NULL, d[greatest(1, toUInt64(ceil(0.95 * n)))]) AS p95
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
