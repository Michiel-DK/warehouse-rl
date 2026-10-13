-- report.py "Decision grades per kind and verdict": a decision is graded when decision_grades holds a stamp with status
-- 'graded' (the verdict is stored as JSON text); anything else counts as open. Not filtered by the countable rule: the
-- report counts every decision of the run.
SELECT d.kind AS kind, if(g.status = 'graded', JSONExtractString(g.verdict), 'open') AS verdict, count() AS decisions
FROM decisions AS d
LEFT JOIN (SELECT id, status, verdict FROM decision_grades FINAL) AS g ON d.id = g.id
WHERE d.run = {run:String}
GROUP BY kind, verdict
ORDER BY kind ASC, verdict ASC
