"""Evaluate a policy over many seeds and step budgets; resumable, multiprocess, one env per process.

Usage: python scripts/evaluate.py --policy cta --env tarware-small-4agvs-2pickers-globalobs-v1 --seeds 0-29 --steps 500,2000 [--workers N] [--results-dir DIR] [--disturb PRESET|JSON] [--recovery timeout|'{"name": "tuned_timeout", "replan": R, "abandon": A, "call_human_cost": C}' | '{"name": "informed_timeout"|"informed_timeout_left", "replan": 5, "abandon": 15}' | '{"name": "rule", "back_off_after": B, "reroute_after": R, "abandon_after": A, "call_human_after": H|null, "call_human_cost": C}']
Writes <results-dir>/<policy>_<env>_<steps>.json after every finished seed (parent process only, atomic).
--disturb (default none) runs under the disturbance layer (warehouse_rl.disturb) and writes
<policy>_<env>_<steps>_<tag>.json instead, storing the config; the undisturbed filename is unchanged. An existing file
with the same tag but a different stored config raises. The paired delta reads the CTA file with the same tag.
--recovery learned:<checkpoint.pt> (needs --policy stuck_aware_cta, else ValueError) runs a trained LearnedRecovery
(warehouse_rl.learned_recovery, torch imported only then); the recovery config is {name: 'learned', checkpoint (path as
given), sha256, call_human_cost (from the checkpoint)} and the tag 'learned-<10 hex of the sha256>', so another
checkpoint can never merge into the same file.
--recovery (default unset; needs --policy stuck_aware_cta, else ValueError) builds the RecoveryHook (warehouse_rl.recovery;
disturb {} for --disturb none) and writes <policy>_<env>_<steps>[_<disturbtag>]_<rectag>.json (rectag: 'timeout' for the
preset, 'rec-<10 hex>' for a JSON spec; call_human_cost is optional, default 60). Doc and rows record the recovery
config and the episode sums of the recovery info keys. Resuming into a file with a different stored recovery config
raises. Without --recovery nothing above changes.
Workers: --workers, else SCHED_WORKERS, else os.cpu_count() - 2; capped at the seeds still to run.
pick-rate = deliveries * 3600 / (5 * steps), deliveries from info["shelf_deliveries"].
Policies: cta, stuck_aware_cta, random (registry below; an unknown name raises ValueError).
Warm-up W = 0: no steps are discarded (README "Evaluation resolution").
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

# two-sided 97.5% Student-t quantiles, df 1..30; 1.96 above
T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
        2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def _parse_ints(spec, name, allow_range, minimum):
    if not isinstance(spec, str) or not spec.strip():
        raise ValueError(f"empty {name} spec")
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if allow_range and "-" in part:
            lo, _, hi = part.partition("-")
            if not (lo.isdigit() and hi.isdigit()):
                raise ValueError(f"bad {name} part {part!r}")
            lo, hi = int(lo), int(hi)
            if lo > hi:
                raise ValueError(f"reversed range {part!r}")
            out.update(range(lo, hi + 1))
        elif part.isdigit():
            out.add(int(part))
        else:
            raise ValueError(f"bad {name} part {part!r}")
    if min(out) < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return sorted(out)


def parse_seeds(s):
    """'0-3,7' -> [0, 1, 2, 3, 7]; sorted unique non-negative ints."""
    return _parse_ints(s, "seeds", True, 0)


def parse_steps(s):
    """'500,2000' -> [500, 2000]; positive ints."""
    return _parse_ints(s, "steps", False, 1)


def workers_arg(s):
    """argparse type for --workers: an empty value (e.g. an empty $SCHED_WORKERS) means unset."""
    return int(s) if s.strip() else None


def resolve_workers(cli_value, env=os.environ, n_tasks=None):
    """--workers, else SCHED_WORKERS (empty/invalid = unset), else cpu_count - 2; capped at n_tasks (min 1)."""
    if cli_value is not None:
        if cli_value < 1:
            raise ValueError("--workers must be >= 1")
        n = cli_value
    else:
        n = None
        try:
            v = int(env.get("SCHED_WORKERS", ""))
            if v >= 1:
                n = v
        except ValueError:
            pass
        if n is None:
            n = max(1, (os.cpu_count() or 3) - 2)
    if n_tasks is not None:
        n = min(n, n_tasks)
    return max(1, n)


def summarise(values):
    """n, mean, sample SD (ddof=1), Student-t 95% CI. n=1 -> sd 0 and CI (mean, mean); n=0 -> Nones."""
    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return dict(n=0, mean=None, sd=None, ci95_low=None, ci95_high=None)
    mean = sum(vals) / n
    if n == 1:
        return dict(n=1, mean=mean, sd=0.0, ci95_low=mean, ci95_high=mean)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1))
    t = T975[n - 2] if n - 1 <= 30 else 1.96
    half = t * sd / math.sqrt(n)
    return dict(n=n, mean=mean, sd=sd, ci95_low=mean - half, ci95_high=mean + half)


POLICIES = ("cta", "stuck_aware_cta", "random")


def make_policy(name, seed):
    """Policy registry; ValueError on an unknown name (never a silent fallback to another policy)."""
    from warehouse_rl.policy import CtaPolicy, RandomPolicy, StuckAwareCtaPolicy

    if name == "cta":
        return CtaPolicy()
    if name == "stuck_aware_cta":
        return StuckAwareCtaPolicy()
    if name == "random":
        return RandomPolicy(seed=seed)
    raise ValueError(f"unknown policy {name!r}; known: {list(POLICIES)}")


def paired_delta(rows_a, rows_b, seeds=None):
    """summarise() of (a - b) pick_rate over the seeds present in both row lists, paired BY SEED (never by index).

    seeds restricts the pairing to those seeds; the differences are taken in ascending seed order."""
    a = {r["seed"]: r for r in rows_a}
    b = {r["seed"]: r for r in rows_b}
    common = sorted(set(a) & set(b) & (set(seeds) if seeds is not None else set(a)))
    return summarise([a[s]["pick_rate"] - b[s]["pick_rate"] for s in common])


def run_seed(policy, env_id, steps, seed, disturb=None, assign_care_for_agents=False, recovery=None):
    """One episode; depends only on (policy, env_id, steps, seed, disturb, assign_care_for_agents). Builds its own env.

    disturb=None is the S1 path (row fields unchanged); a dict adds the disturbance episode sums.
    recovery (a normalised config dict, needs disturb) adds the recovery config and RECOVERY_SUMS to the row."""
    from warehouse_rl.env import WarehouseEnv

    t0 = time.time()
    pol = make_policy(policy, seed)
    if recovery is not None and recovery.get("name") == "learned":  # lazy: torch only for a learned policy
        from warehouse_rl.learned_recovery import make_learned_env, policy_from_config

        env = make_learned_env(env_id, steps, disturb, policy_from_config(recovery), recovery["call_human_cost"],
                               assign_care_for_agents)
    else:
        env_kwargs = {} if recovery is None else dict(recovery=recovery)
        env = WarehouseEnv(env_id, max_steps=steps, disturb=disturb, assign_care_for_agents=assign_care_for_agents,
                           **env_kwargs)
    extra = {k: 0 for k in DISTURB_SUMS} if disturb is not None else None
    rec_extra = {k: 0 for k in RECOVERY_SUMS} if recovery is not None else None
    try:
        obs, info = env.reset(seed=seed)
        pol.reset(env)
        deliveries = clashes = stucks = 0
        for _ in range(steps):
            actions = pol.act(obs, info["action_mask"], info)
            obs, _, _, _, info = env.step(actions)
            deliveries += int(info["shelf_deliveries"])
            clashes += int(info["clashes"])
            stucks += int(info["stucks"])
            if extra is not None:
                for out_key, info_key in DISTURB_SUMS.items():
                    extra[out_key] += int(info[info_key])
            if rec_extra is not None:
                for k in RECOVERY_SUMS:
                    rec_extra[k] += int(info[k])
        n_agents = env.num_agents
        delivered_per_agent = list(info["delivered_per_agent"]) if extra is not None else None
    finally:
        env.close()
    row = dict(seed=seed, steps=steps, deliveries=deliveries, pick_rate=deliveries * 3600 / (5 * steps),
               clashes=clashes, stucks=stucks, wall_s=time.time() - t0)
    if extra is not None:
        row.update(extra)
        row["frozen_fraction"] = extra["frozen_agent_steps"] / (steps * n_agents)
        row["delivered_per_agent"] = delivered_per_agent
    if rec_extra is not None:
        row["recovery"] = dict(recovery)
        row.update(rec_extra)
    return row


# row field -> per-step info key, summed over the episode
DISTURB_SUMS = dict(stuck_agent_steps="stuck_agents", stuck_busy_agent_steps="stuck_busy_agents",
                    abandoned_tasks="abandoned_tasks",
                    clash_agent_steps="clash_agents", frozen_agent_steps="frozen_agents",
                    delayed_agent_steps="delayed_agents",
                    floor_skip_steps="floor_skips")  # floor_skip_steps: agent-steps NOOPed by a floor cell, 0 w/o floor

# recovery rows only (kept apart from DISTURB_SUMS so non-recovery disturbed runs never need these info keys)
RECOVERY_SUMS = ("recovery_wait", "recovery_back_off", "recovery_reroute", "recovery_abandon", "recovery_call_human",
                 "recovery_stuck_events", "recovery_clash_events", "recovery_fallbacks", "call_human_steps",
                 "decisions_while_blocker_frozen", "reroutes_while_blocker_frozen")


def _job(args):
    return run_seed(*args)


def _write(path, policy, env_id, steps, rows, tag=None, config=None, rec_tag=None, rec_config=None):
    rows = sorted(rows, key=lambda r: r["seed"])
    s = summarise([r["pick_rate"] for r in rows])
    doc = dict(policy=policy, env=env_id, steps=steps, rows=rows, n=s["n"], pick_rate_mean=s["mean"],
               pick_rate_sd=s["sd"], ci95_low=s["ci95_low"], ci95_high=s["ci95_high"])
    if config is not None:
        doc.update(disturb_tag=tag, disturb=config)
    if rec_config is not None:
        doc.update(recovery_tag=rec_tag, recovery=rec_config)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    os.replace(tmp, path)


def _fmt(s):
    return f"mean={s['mean']:.2f} sd={s['sd']:.2f} 95% CI=[{s['ci95_low']:.2f}, {s['ci95_high']:.2f}] n={s['n']}"


def _check_same_config(path, doc, tag, config):
    if doc.get("disturb") != config or doc.get("disturb_tag") != tag:
        raise ValueError(f"{path} stores disturb config {doc.get('disturb')!r} (tag {doc.get('disturb_tag')!r}), "
                         f"requested {config!r} (tag {tag!r}); refusing to merge")


def _check_same_recovery(path, doc, rec_tag, rec_config):
    if doc.get("recovery") != rec_config or doc.get("recovery_tag") != rec_tag:
        raise ValueError(f"{path} stores recovery config {doc.get('recovery')!r} (tag {doc.get('recovery_tag')!r}), "
                         f"requested {rec_config!r} (tag {rec_tag!r}); refusing to merge")


def evaluate(policy, env_id, steps, seeds, workers_cli, results_dir, disturb="none", recovery=None):
    from warehouse_rl.disturb import resolve_disturb

    rec_tag = rec_config = None
    if recovery is not None:
        from warehouse_rl.recovery import resolve_recovery

        if policy != "stuck_aware_cta":
            raise ValueError(f"--recovery needs --policy stuck_aware_cta (re-dispatch on abandon), got {policy!r}")
        if isinstance(recovery, str) and recovery.startswith("learned:"):
            from warehouse_rl.learned_recovery import resolve_learned

            rec_tag, rec_config = resolve_learned(recovery[len("learned:"):])
        else:
            rec_tag, rec_config = resolve_recovery(recovery)
    tag, config = resolve_disturb(disturb)
    disturbed = tag != "none"  # preset none = the S1 undisturbed path: same filename, no layer
    suffix = f"_{tag}" if disturbed else ""
    layer = disturbed or rec_config is not None  # a recovery run always builds the layer ({} = no disturbance)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    rec_suffix = f"_{rec_tag}" if rec_config is not None else ""
    path = results_dir / f"{policy}_{env_id}_{steps}{suffix}{rec_suffix}.json"
    rows = []
    if path.exists():
        doc = json.loads(path.read_text())
        if layer:
            _check_same_config(path, doc, tag, config)
        if rec_config is not None:
            _check_same_recovery(path, doc, rec_tag, rec_config)
        rows = doc["rows"]
    have = {r["seed"] for r in rows}
    todo = [s for s in seeds if s not in have]
    if todo:
        workers = resolve_workers(workers_cli, os.environ, len(todo))
        print(f"[{policy} {steps} steps] {len(todo)} seeds to run on {workers} workers ({len(have)} already on disk)")
        if rec_config is not None:
            jobs = [(policy, env_id, steps, s, config, False, rec_config) for s in todo]
        else:
            jobs = [(policy, env_id, steps, s, config if disturbed else None) for s in todo]
        with mp.Pool(workers) as pool:
            for row in pool.imap_unordered(_job, jobs):
                rows.append(row)
                _write(path, policy, env_id, steps, rows, tag if layer else None, config if layer else None,
                       rec_tag, rec_config)
    else:
        print(f"[{policy} {steps} steps] all requested seeds already on disk")
    by_seed = {r["seed"]: r for r in rows}
    req = [by_seed[s] for s in seeds]
    print(f"{policy} {steps} steps pick_rate (lines/h): " + _fmt(summarise([r["pick_rate"] for r in req])))
    if rec_config is not None:
        base_path = results_dir / f"{policy}_{env_id}_{steps}{suffix}.json"
        if base_path.exists():
            base_doc = json.loads(base_path.read_text())
            if disturbed:
                _check_same_config(base_path, base_doc, tag, config)
            d = paired_delta(req, base_doc["rows"], seeds)
            if d["n"]:
                print(f"paired delta ({policy}+{rec_tag} - {policy}): n_paired={d['n']} mean_delta={d['mean']:.2f} "
                      f"sd={d['sd']:.2f} 95% CI=[{d['ci95_low']:.2f}, {d['ci95_high']:.2f}]")
            else:
                print("paired delta: n_paired=0 (no common seeds with the no-recovery file)")
        else:
            print(f"paired delta: no no-recovery file at {base_path}")
    elif policy != "cta":
        cta_path = results_dir / f"cta_{env_id}_{steps}{suffix}.json"
        if cta_path.exists():
            cta_doc = json.loads(cta_path.read_text())
            if disturbed:
                _check_same_config(cta_path, cta_doc, tag, config)
            d = paired_delta(req, cta_doc["rows"], seeds)
            if d["n"]:
                print(f"paired delta ({policy} - cta): n_paired={d['n']} mean_delta={d['mean']:.2f} "
                      f"sd={d['sd']:.2f} 95% CI=[{d['ci95_low']:.2f}, {d['ci95_high']:.2f}]")
            else:
                print("paired delta: n_paired=0 (no common seeds with the CTA file)")
        else:
            print(f"paired delta: no CTA file at {cta_path}")
    print(f"wrote {path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", choices=list(POLICIES), required=True)
    p.add_argument("--env", required=True)
    p.add_argument("--seeds", required=True)
    p.add_argument("--steps", required=True)
    p.add_argument("--workers", type=workers_arg, nargs="?", default=None)  # bare/empty = unset
    p.add_argument("--results-dir", default=str(REPO / "results"))
    p.add_argument("--disturb", default="none", help="preset name or JSON object (see warehouse_rl.disturb)")
    p.add_argument("--recovery", default=None,
                   help="preset 'timeout' or JSON {\"name\": \"tuned_timeout\", \"replan\": R, \"abandon\": A, "
                        "\"call_human_cost\"?: C} or {\"name\": \"rule\", \"back_off_after\": B, "
                        "\"reroute_after\": R, \"abandon_after\": A, \"call_human_after\"?: H|null, "
                        "\"call_human_cost\"?: C} or learned:<checkpoint path> "
                        "(needs --policy stuck_aware_cta)")
    a = p.parse_args()
    seeds, steps_list = parse_seeds(a.seeds), parse_steps(a.steps)
    for st in steps_list:
        evaluate(a.policy, a.env, st, seeds, a.workers, a.results_dir, a.disturb, a.recovery)


if __name__ == "__main__":
    main()
