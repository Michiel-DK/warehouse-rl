-- report.py "Time from stuck to resolution": nearest-rank p50 / p95 of end - t_entry over countable episodes with an end.
WITH arraySort(groupArray(`end` - t_entry)) AS w, length(w) AS n
SELECT if(n = 0, NULL, w[greatest(1, toUInt64(ceil(0.5 * n)))]) AS p50,
       if(n = 0, NULL, w[greatest(1, toUInt64(ceil(0.95 * n)))]) AS p95
FROM stuck_episodes FINAL
WHERE run = {run:String} AND NOT left_censored AND resolution NOT IN ('open', 'interrupted')
