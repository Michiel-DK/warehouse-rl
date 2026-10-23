# wr-s8e-lessons-long (15 Oct 2026, 18:28-18:30): is 0/13 lesson persistence the window or the rule?

Run: 3 zones x 2,000 steps (2.78 h simulated), medium map, seeds 0-2, floor cells 80 p [0.3, 0.7], stuck_aware_cta +
timeout; ingest + costmap once, then `lessons.py --once --window-h W`, `grade.py --once --truth`, `hotspot_score.py` on
three copies of the same store (W = 0.2, 0.5, 1.0 h). Wall time about 2 minutes on 4 cores. Outputs:
`fleet/data/s8e-long/` (git-ignored; `store-w0.2`, `store-w0.5`, `store-w1.0`) and the committed
`results/fleet/hotspot_s8e-long-w{0.2,0.5,1.0}.json` (`grading_counts.lesson`, `grading_counts.lesson_truth`).

| window | lessons | graded on next window | held ("ok") | hot_cell held | hot_cell real (truth) | cause_mix held |
|---|---|---|---|---|---|---|
| 0.2 h | 16 (hot_cell 14, hot_robot 1, cause_mix 1) | 15 | 1 | 0 / 13 | 13 / 14 | 1 / 1 |
| 0.5 h | 34 (hot_cell 27, cause_mix 7) | 31 | 9 | 3 / 25 | 27 / 27 | 6 / 6 |
| 1.0 h | 33 (hot_cell 29, cause_mix 4) | 15 (18 open: shift ends) | 4 | 3 / 13 | 28 / 29 | 1 / 2 |

Next-window count divided by the lesson's own count (hot_cell): 0.2 h median 0.2, 0.5 h median 0.5, 1.0 h median
0.58. The 3x-over-average bar on the *same count* is rarely met again.

**Answer: mostly the rule, a little the window.** Longer windows lift hot_cell persistence from 0% to 12-23%, but
three quarters of the calls still fail while the truth says the cells are real in 27 of 27 (0.5 h) or 28 of 29 (1.0 h).
A cell is flagged because it was an extreme in its window; the next window regresses to the mean, so "same count
again" is the wrong persistence test for an extreme-value rule. cause_mix lessons (a share, not an extreme) do hold
(8 of 9 across windows). The map itself is unchanged by the window (precision@20 0.983, recall 0.246, 3 zones).

Implications (operator's call): grade hot_cell on "still above the zone's average stalled cell next window" or on the
truth/rank columns already stored, not on the same count; 0.5 h is the window with the most graded lessons and the
best persistence on this shift, and is the evidence for picking `--window-h 0.5` on the demo run (S8J item 4) without
peeking at the demo's own result. Not tested: windows longer than 1 h (the shift is too short), more than 3 zones.
