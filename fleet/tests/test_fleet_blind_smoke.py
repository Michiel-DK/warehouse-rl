"""fleet/blind_smoke.py: the pure overlap function on a hand-built message fixture, and the output-dir refusal."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fleet"))

import blind_smoke  # noqa: E402
from fleet_analyser.parse import Message  # noqa: E402

T0 = 1_000_000
STEP_S = 5
RIGHT = 0.0  # theta of heading +x; front of (x, y) is (x + 1, y)


def msg(serial, hid, step, x=3, y=3, order="o1", theta=RIGHT, nodes=True, nxt=(4, 3), zone="0"):
    return Message(serial=serial, zone=zone, header_id=hid, ts=T0 + step * STEP_S, order_id=order, x=x, y=y,
                   driving=False, faulted=False, loaded=False, raw_len=1, theta=theta,
                   next_x=nxt[0] if nxt else None, next_y=nxt[1] if nxt else None, nodes_reported=nodes)


class TestOverlap(unittest.TestCase):
    WINDOWS = {"0": [dict(cell="4,3", start_step=10, end_step=20, known=False)]}

    def run_overlap(self, msgs, windows=None):
        return blind_smoke.overlap(msgs, self.WINDOWS if windows is None else windows, T0, STEP_S)

    def test_in_window_out_of_window_and_current_attribution(self):
        msgs = [
            # robot A: stalls into 4,3 at step 12 (cur), inside [10, 20)
            msg("Z0-01", 1, 11), msg("Z0-01", 2, 12),
            # robot B: same stall into 4,3 at step 25, after the window
            msg("Z0-02", 1, 24), msg("Z0-02", 2, 25),
            # robot C: no route reported on prev (old schema) -> 'current' attribution, excluded from both counts
            msg("Z0-03", 1, 11, nodes=False, nxt=None), msg("Z0-03", 2, 12, nodes=False, nxt=None),
            # robot D: moved (cur at another cell), not a stall at all
            msg("Z0-04", 1, 11), msg("Z0-04", 2, 12, x=4, y=3),
        ]
        r = self.run_overlap(msgs)
        self.assertEqual((r["numerator"], r["denominator"]), (1, 2))
        self.assertEqual(r["share"], 0.5)

    def test_window_end_is_exclusive_and_start_inclusive(self):
        r = self.run_overlap([msg("Z0-01", 1, 9), msg("Z0-01", 2, 10), msg("Z0-02", 1, 19), msg("Z0-02", 2, 20)])
        self.assertEqual((r["numerator"], r["denominator"]), (1, 2))  # cur step 10 in, cur step 20 out

    def test_other_cell_and_other_zone_do_not_count(self):
        msgs = [msg("Z0-01", 1, 11, nxt=(4, 3)), msg("Z0-01", 2, 12, nxt=(4, 3)),
                msg("Z1-01", 1, 11, zone="1"), msg("Z1-01", 2, 12, zone="1")]
        r = self.run_overlap(msgs, {"0": [dict(cell="9,9", start_step=0, end_step=100)], "1": []})
        self.assertEqual((r["numerator"], r["denominator"]), (0, 2))
        self.assertEqual(r["share"], 0.0)

    def test_no_stalls_gives_none_share(self):
        r = self.run_overlap([msg("Z0-01", 1, 11)])
        self.assertEqual((r["numerator"], r["denominator"], r["share"]), (0, 0, None))

    def test_message_order_does_not_matter(self):
        msgs = [msg("Z0-01", 2, 12), msg("Z0-01", 1, 11)]
        self.assertEqual(self.run_overlap(msgs)["numerator"], 1)


class TestOutDirRefusal(unittest.TestCase):
    def test_refuses_results_and_fleet_data(self):
        for bad in (ROOT / "results" / "x", ROOT / "fleet" / "data", ROOT / "fleet" / "data" / "run"):
            with self.subTest(bad=str(bad)):
                with self.assertRaises(ValueError):
                    blind_smoke._check_out_dir(bad)
        blind_smoke._check_out_dir("/tmp/blind_smoke_ok")


if __name__ == "__main__":
    unittest.main()
