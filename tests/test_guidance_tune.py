"""scripts/guidance_tune.py (S8M): the transform, the search list, resume, the held-out refusals, imported stats, loaders.

Plain unittest, run from the repo root. Everything is written under tempfile dirs; evaluate.py is only really run in the
identity == map_a4 test (2 seeds, small map)."""
import importlib.util
import json
import math
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("guidance_tune_script", ROOT / "scripts" / "guidance_tune.py")
gt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gt)
ev, cl = gt.ev, gt.cl
from warehouse_rl.disturb import resolve_disturb  # noqa: E402  (src is on sys.path once guidance_tune is loaded)

SMALL = cl.SMALL
GRID = (25, 14)  # (rows, cols) of the small map
HEADER = {"schema_version": "fleet-costmap/1", "run": "t", "generated_at": "2026-01-01T00:00:00Z", "window_hours": 1.0,
          "half_life_h": 1.0, "min_stalls": 1, "exclude_occupied": True}
MEAN_KEYS = cl.MEANS


def _tracked_state():
    """`git status --porcelain` plus the file listing of results/ (pycache excluded), as in tests/test_closed_loop.py."""
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    base = ROOT / "results"
    listing = sorted(str(p.relative_to(ROOT)) for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts) \
        if base.exists() else []
    return status, listing


def _hand_zone(salt):
    return {f"{x},{y}": round(0.15 + ((x * 7 + y * 3 + salt) % 17) / 20, 3) for x in range(14) for y in range(25)
            if (x + y) % 2 == 0}


def _doc(zones):
    d = dict(HEADER)
    d["zones"] = zones
    return d


def _rows(values, seeds):
    return [dict({"seed": s, "pick_rate": v}, **{k: float(s) for k in MEAN_KEYS}) for s, v in zip(seeds, values)]


def _write_results(path, rows, extra=None):
    doc = dict(env=SMALL, steps=500, rows=rows, **(extra or {}))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc))


class Fixture:
    """A fake phase A + baseline arms for seeds 0-5, all under one tempdir."""

    def __init__(self, tmp, seeds=range(6)):
        self.tmp = Path(tmp)
        self.seeds = list(seeds)
        self.base = self.tmp / "base"
        pa = self.base / "phaseA"
        pa.mkdir(parents=True)
        self.meta = dict(env=SMALL, seeds=len(self.seeds), steps=500, disturb=cl.FLOOR_REGIME)
        (pa / "phaseA_meta.json").write_text(json.dumps(self.meta))
        (pa / "costmap.json").write_text(json.dumps(_doc({str(s): _hand_zone(s) for s in self.seeds})))
        self.pa = pa
        pr = {"none": [10.0 + s for s in self.seeds], "map_a4": [11.0 + s for s in self.seeds],
              "map_a32": [10.5 + 2 * s for s in self.seeds], "oracle": [12.0 + s for s in self.seeds],
              "undisturbed": [15.0 + s for s in self.seeds]}
        for arm, vals in pr.items():
            tag, config = resolve_disturb("none" if arm == "undisturbed" else cl.FLOOR_REGIME)
            _write_results(self.base / arm / f"stuck_aware_cta_{SMALL}_500_{arm}.json", _rows(vals, self.seeds),
                           {"costmap_alpha": {"map_a4": 4.0, "map_a32": 32.0, "oracle": 4.0}.get(arm),
                            "policy": "stuck_aware_cta", "recovery_tag": "timeout", "disturb_tag": tag, "disturb": config})
        self.out = self.tmp / "out"


def fake_run_evaluate(calls, pick=lambda s, alpha: 12.0 + 0.1 * s + alpha / 100):
    """Stands in for gt.run_evaluate: writes a complete results file for the command's seeds and counts the call."""
    def run(cmd):
        calls.append(list(cmd))
        c = [str(x) for x in cmd]
        seeds = ev.parse_seeds(c[c.index("--seeds") + 1])
        alpha = float(c[c.index("--costmap-alpha") + 1])
        d = Path(c[c.index("--results-dir") + 1])
        _write_results(d / "stuck_aware_cta_fake.json", _rows([pick(s, alpha) for s in seeds], seeds))
        return ""
    return run


class TestTransform(unittest.TestCase):
    def test_tau_and_gamma(self):
        zone = {"1,1": 0.9, "2,2": 0.05, "3,3": 0.5, "4,4": 0.2, "5,5": 0.3}
        out = gt.transform_zone(zone, dict(alpha=4.0, gamma=2.0, tau=0.2, dilate=0), GRID)
        self.assertEqual(set(out), {"1,1", "3,3", "4,4", "5,5"})  # 0.05 < tau dropped; 0.2 == tau kept (raw compare)
        for k, v in out.items():
            self.assertAlmostEqual(v, zone[k] ** 2.0)
        self.assertEqual(sorted(out, key=lambda k: zone[k]), sorted(out, key=lambda k: out[k]))  # order of kept costs kept

    def test_dilate(self):
        zone = {"0,0": 0.8, "1,0": 0.4, "5,5": 0.6, "6,6": 0.2}
        p = dict(alpha=4.0, gamma=2.0, tau=0.0, dilate=1)
        out = gt.transform_zone(zone, p, GRID)
        c = {k: v ** 2 for k, v in zone.items()}
        for k in zone:
            self.assertEqual(out[k], c[k])  # kept cells are never overwritten
        added = {k: v for k, v in out.items() if k not in zone}
        expect = {"0,1": 0.5 * c["0,0"], "2,0": 0.5 * c["1,0"], "1,1": 0.5 * c["1,0"],  # (-1,0), (0,-1), (1,-1) out of grid
                  "5,4": 0.5 * c["5,5"], "4,5": 0.5 * c["5,5"], "7,6": 0.5 * c["6,6"], "6,7": 0.5 * c["6,6"],
                  "5,6": 0.5 * max(c["5,5"], c["6,6"]), "6,5": 0.5 * max(c["5,5"], c["6,6"])}
        self.assertEqual(set(added), set(expect))  # 4-neighbours only: no diagonals, none already kept
        for k, v in expect.items():
            self.assertAlmostEqual(added[k], v, msg=k)
        self.assertEqual(set(gt.transform_zone(zone, dict(p, dilate=0), GRID)), set(zone))

    def test_dilate_stays_in_grid(self):
        rows, cols = GRID
        zone = {f"{cols - 1},{rows - 1}": 1.0, "0,0": 1.0}
        out = gt.transform_zone(zone, dict(alpha=4.0, gamma=1.0, tau=0.0, dilate=1), GRID)
        for k in out:
            x, y = map(int, k.split(","))
            self.assertTrue(0 <= x < cols and 0 <= y < rows, k)
        self.assertEqual(len(out), 2 + 2 + 2)

    def test_identity(self):
        zone = _hand_zone(3)
        self.assertEqual(gt.transform_zone(zone, gt.IDENTITY, GRID), zone)  # same keys and no others, equal values


class TestWriteAndLoad(unittest.TestCase):
    def test_loader_accepts_dilated_costmap(self):
        from warehouse_rl.disturb import validate_cost_map

        with tempfile.TemporaryDirectory() as tmp:
            src = _doc({"0": _hand_zone(0), "1": _hand_zone(1), "2": _hand_zone(2)})
            params = dict(alpha=8.0, gamma=1.5, tau=0.2, dilate=1)
            p = gt.write_costmap(src, params, [0, 2], GRID, Path(tmp) / "c" / "costmap.json")
            _, gen, zones = ev._load_costmap(p)
            self.assertEqual(list(json.loads(p.read_text())), list(src))  # top-level keys, same order
            self.assertEqual(gen, src["generated_at"])
            self.assertEqual(sorted(zones), ["0", "2"])
            for s in (0, 2):
                cm = ev._cost_map_for_seed(zones, s, 0)
                self.assertEqual(validate_cost_map(cm, GRID), cm)
            with self.assertRaises(ValueError):
                ev._cost_map_for_seed(zones, 1, 0)
            p2 = gt.write_costmap(src, params, [0, 2], GRID, Path(tmp) / "d.json")
            self.assertEqual(p.read_bytes(), p2.read_bytes())  # byte-deterministic

    def test_grid_size(self):
        self.assertEqual(gt.grid_size_for(SMALL), GRID)


class TestIdentityEqualsMapA4(unittest.TestCase):
    def test_rows_equal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = _doc({"0": _hand_zone(0), "1": _hand_zone(1)})
            orig = tmp / "orig.json"
            orig.write_text(json.dumps(src))
            ident = gt.write_costmap(src, gt.IDENTITY, [0, 1], GRID, tmp / "ident.json")
            res = {}
            for name, path in (("orig", orig), ("ident", ident)):
                r = subprocess.run([sys.executable, str(ROOT / "scripts" / "evaluate.py"), "--policy", "stuck_aware_cta",
                                    "--recovery", "timeout", "--env", SMALL, "--steps", "500", "--seeds", "0,1", "--workers", "2",
                                    "--disturb", cl.FLOOR_REGIME, "--costmap", str(path), "--costmap-alpha", repr(4.0),
                                    "--results-dir", str(tmp / name)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-2000:])
                (f,) = (tmp / name).glob("*.json")
                res[name] = sorted(json.loads(f.read_text())["rows"], key=lambda r: r["seed"])

            def strip(rows):
                return [{k: v for k, v in r.items() if k != "wall_s"} for r in rows]

            self.assertEqual(strip(res["orig"]), strip(res["ident"]))
            self.assertGreater(sum(r["routes_changed_by_map"] for r in res["orig"]), 0, "map inactive: equality is vacuous")


class TestSearch(unittest.TestCase):
    def test_param_list(self):
        a = gt.param_list(0, 48)
        self.assertEqual(a, gt.param_list(0, 48))
        self.assertNotEqual(a, gt.param_list(1, 48))
        self.assertEqual(a[0], gt.IDENTITY)
        self.assertEqual(gt.param_list(0, 3), a[:3])
        self.assertEqual(len(a), 48)
        for p in a[1:]:
            self.assertTrue(1 <= p["alpha"] <= 64 and 0.5 <= p["gamma"] <= 3 and 0 <= p["tau"] <= 0.5 and p["dilate"] in (0, 1), p)
        self.assertEqual({p["dilate"] for p in a[1:]}, {0, 1})


class TestTune(unittest.TestCase):
    def test_resume_makes_no_calls_then_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                gt.tune(fx.pa, [0, 1, 2], 3, 0, fx.out)
                self.assertEqual(len(calls), 3)
                calls.clear()
                gt.tune(fx.pa, [0, 1, 2], 3, 0, fx.out)
                self.assertEqual(len(calls), 0)
                (f,) = (fx.out / "evals" / "1").glob("stuck_aware_cta*.json")
                f.unlink()
                gt.tune(fx.pa, [0, 1, 2], 3, 0, fx.out)
                self.assertEqual(len(calls), 1)
            cmd = [str(c) for c in calls[0]]
            self.assertEqual(cmd[cmd.index("--seeds") + 1], "0,1,2")
            self.assertNotIn("--workers", cmd)
            self.assertEqual(cmd[cmd.index("--costmap-alpha") + 1], repr(gt.param_list(0, 3)[1]["alpha"]))

    def test_mismatches_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                gt.tune(fx.pa, [0, 1], 2, 0, fx.out)
                n = len(calls)
                with self.assertRaises(ValueError):  # another search seed: tune.json differs
                    gt.tune(fx.pa, [0, 1], 2, 1, fx.out)
                with self.assertRaises(ValueError):  # another train set
                    gt.tune(fx.pa, [0, 2], 2, 0, fx.out)
                (fx.out / "tune.json").unlink()
                with self.assertRaises(ValueError):  # params.json of eval 1 differs (search seed 1)
                    gt.tune(fx.pa, [0, 1], 2, 1, fx.out)
                self.assertEqual(len(calls), n)

    def test_workers_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                gt.tune(fx.pa, [0], 1, 0, fx.out, workers=3)
            cmd = [str(c) for c in calls[0]]
            self.assertEqual(cmd[cmd.index("--workers") + 1], "3")

    def test_never_reads_heldout(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            (nf,) = (fx.base / "none").glob("*.json")
            doc = json.loads(nf.read_text())
            for r in doc["rows"]:
                if r["seed"] >= 3:
                    r["pick_rate"] = "poison" if r["seed"] % 2 else float("nan")
            nf.write_text(json.dumps(doc))
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate([])):
                gt.tune(fx.pa, [0, 1, 2], 3, 0, fx.out)
            tj = json.loads((fx.out / "tune.json").read_text())
            self.assertEqual(len(tj["evaluations"]), 3)
            for e in tj["evaluations"]:
                self.assertTrue(math.isfinite(e["objective"]))
                self.assertEqual(sorted(e["pick_rates"]), ["0", "1", "2"])
            for i in range(3):
                zones = json.loads((fx.out / "evals" / str(i) / "costmap.json").read_text())["zones"]
                self.assertEqual(sorted(zones), ["0", "1", "2"])
            self.assertEqual(tj["best_index"], max(range(3), key=lambda i: (tj["evaluations"][i]["objective"], -i)))

    def test_missing_train_seed_in_none_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                with self.assertRaises(ValueError):
                    gt.tune(fx.pa, [0, 1, 9], 1, 0, fx.out)
            self.assertEqual(calls, [])


class TestHeldout(unittest.TestCase):
    def _tuned(self, fx):
        with mock.patch.object(gt, "run_evaluate", fake_run_evaluate([])):
            gt.tune(fx.pa, [0, 1, 2], 3, 0, fx.out / "tune")
        return fx.out / "tune" / "best_transform.json"

    def test_refusals_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            tf = self._tuned(fx)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                with self.assertRaises(ValueError):  # overlap with train seeds
                    gt.heldout(fx.pa, tf, [2, 3], fx.out / "h.json", baseline_dir=fx.base)
                (mf,) = (fx.base / "oracle").glob("*.json")
                doc = json.loads(mf.read_text())
                doc["rows"] = [r for r in doc["rows"] if r["seed"] != 4]
                mf.write_text(json.dumps(doc))
                with self.assertRaises(ValueError):  # baseline arm lacks requested seed 4
                    gt.heldout(fx.pa, tf, [3, 4], fx.out / "h.json", baseline_dir=fx.base)
                (fx.pa / "costmap.json").write_text(json.dumps(_doc({"0": {"1,1": 0.5}})))
                with self.assertRaises(ValueError):  # source costmap changed since tune
                    gt.heldout(fx.pa, tf, [3], fx.out / "h.json", baseline_dir=fx.base)
                self.assertEqual(calls, [])

    def test_refuses_baseline_with_another_disturbance(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            tf = self._tuned(fx)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                for arm, field, value in (("map_a32", "disturb", {"floor": {"cells": 40, "p": [0.3, 0.7]}}),
                                          ("undisturbed", "disturb_tag", "cfg-86550f4e27"),
                                          ("oracle", "recovery_tag", "rec-0123456789")):
                    (mf,) = (fx.base / arm).glob("*.json")
                    good = mf.read_text()
                    doc = json.loads(good)
                    doc[field] = value
                    mf.write_text(json.dumps(doc))
                    with self.assertRaisesRegex(ValueError, f"arm {arm} of this phase A needs"):
                        gt.heldout(fx.pa, tf, [3, 4], fx.out / "h.json", baseline_dir=fx.base)
                    mf.write_text(good)
                gt.heldout(fx.pa, tf, [3, 4], fx.out / "h.json", baseline_dir=fx.base)  # restored files pass
            self.assertEqual(len(calls), 1)  # only the final, clean heldout ran evaluate

    def test_imported_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            tf = self._tuned(fx)
            calls = []
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate(calls)):
                gt.heldout(fx.pa, tf, [3, 5, 4], fx.out / "h.json", baseline_dir=fx.base)
            self.assertEqual(len(calls), 1)
            out = json.loads((fx.out / "h.json").read_text())
            hs = [3, 4, 5]
            self.assertEqual(out["heldout_seeds"], hs)
            arms = ("none", "map_a4", "map_a32", "oracle", "undisturbed", "map_tuned")
            self.assertEqual(list(out["arms"]), list(arms))
            self.assertEqual(list(out["in_sample"]["arms"]), list(arms))

            def rows_of(arm, seeds):
                if arm == "map_tuned":
                    f = Path(out["map_tuned_results_file"] if seeds == hs else json.loads(tf.read_text())["eval_results_file"])
                else:
                    (f,) = (fx.base / arm).glob("*.json")
                return sorted((r for r in json.loads(f.read_text())["rows"] if r["seed"] in seeds), key=lambda r: r["seed"])

            for block, seeds in ((out["arms"], hs), (out["in_sample"]["arms"], [0, 1, 2])):
                rows = {a: rows_of(a, seeds) for a in arms}
                for a in arms:
                    alpha = out["transform"]["alpha"] if a == "map_tuned" else block[a]["alpha"]
                    self.assertEqual(block[a]["pick_rate_ci95"], cl.arm_summary(rows[a], alpha)["pick_rate_ci95"])
                    if a in ("none", "undisturbed"):
                        self.assertNotIn("share_of_floor_loss_recovered", block[a])
                        continue
                    d = ev.paired_delta(rows[a], rows["none"])
                    self.assertEqual(block[a]["paired_delta_vs_none"], dict(mean=d["mean"], ci95=[d["ci95_low"], d["ci95_high"]], n=d["n"]))
                    self.assertEqual(block[a]["share_of_floor_loss_recovered"],
                                     cl.share_recovered(rows[a], rows["none"], rows["undisturbed"]))
            zones = json.loads((fx.out / "map_tuned" / "costmap.json").read_text())["zones"]
            self.assertEqual(sorted(zones), ["3", "4", "5"])


class TestQueueCommands(unittest.TestCase):
    TUNE = ("scripts/guidance_tune.py tune --phase-a results/closed_loop_sticky/phaseA --train-seeds 0-9 --evals 48 "
            "--search-seed 0 --workers $SCHED_WORKERS --out-dir results/guidance/sticky")
    HELD = ("scripts/guidance_tune.py heldout --phase-a results/closed_loop_sticky/phaseA --transform "
            "results/guidance/sticky/best_transform.json --heldout-seeds 10-29 --baseline-dir results/closed_loop_sticky "
            "--workers $SCHED_WORKERS --out results/guidance/sticky/heldout.json")

    def test_parse(self):
        def argv(line, workers):  # '$SCHED_WORKERS' becomes ONE argv element, '' when the variable is empty-but-quoted
            return [workers if w == "$SCHED_WORKERS" else w for w in line.split()][1:]

        for workers, want in (("3", 3), ("", None)):
            a = gt.build_parser().parse_args(argv(self.TUNE, workers))
            self.assertEqual((a.cmd, a.train_seeds, a.evals, a.search_seed, a.baseline_dir, a.workers),
                             ("tune", list(range(10)), 48, 0, None, want))
            a = gt.build_parser().parse_args(argv(self.HELD, workers))
            self.assertEqual((a.cmd, a.heldout_seeds, a.workers), ("heldout", list(range(10, 30)), want))
        # unquoted and unset, the shell drops the word: bare --workers
        a = gt.build_parser().parse_args(shlex.split(self.TUNE.replace("$SCHED_WORKERS", ""))[1:])
        self.assertEqual((a.evals, a.workers, a.out_dir), (48, None, "results/guidance/sticky"))


class TestHygiene(unittest.TestCase):
    def test_tree_untouched_by_a_tune(self):
        before = _tracked_state()
        with tempfile.TemporaryDirectory() as tmp:
            fx = Fixture(tmp)
            with mock.patch.object(gt, "run_evaluate", fake_run_evaluate([])):
                gt.tune(fx.pa, [0, 1], 2, 0, fx.out)
        self.assertEqual(before, _tracked_state())


if __name__ == "__main__":
    unittest.main()
