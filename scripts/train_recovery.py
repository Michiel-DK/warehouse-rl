"""Train a LearnedRecovery (double DQN) on the breakdown-rate disturbance; one run per (rate, seed).

Usage: python scripts/train_recovery.py [--rates 1,2,4] [--seeds 0,1,2] [--workers N] [--episodes E] [--steps 500]
                                        [--smoke] [--resume] [--results-dir DIR] [--max-intervals N]
                                        [--random-share F] [--abort-below F] [--abort-after-frac F]
--results-dir is the TRAINING ROOT (default results/recovery_train, also recovery_heldout.py's --train-dir default);
run (r, s) lives in <results-dir>/rate<r>_seed<s>/ with checkpoint.pt (portable policy, see learned_recovery.py),
log.json ({config, intervals, finished, reward_used, reference_pick_rate[, aborted]}) and train_state.pt (resume state), each written atomically after
every evaluation interval, in that order (checkpoint, log, state). A fresh run writes an initial train_state.pt (episode
0) before its first rollout, so a log never exists without a state file: a kill between two writes can leave the resume
state behind the log (resume drops the log's later intervals and redoes them), never ahead of it and never missing.

Setting: medium map (8 AGVs + 4 pickers), disturbance = sweep.point_spec("breakdown", rate), dispatcher
StuckAwareCtaPolicy, call_human_cost 60. The agent is a semi-MDP DQN over the RecoveryHook decision events; the reward
is defined in learned_recovery.py (fleet deliveries share minus the call-human and abandon costs; the stuck-busy term
is there with coefficient 0; the env reward is never read).

Exploration: with probability epsilon (linear schedule) a training decision is uniform random with probability
random_share (RANDOM_SHARE, --random-share) and otherwise the timeout rule's action (prior "timeout"), so the fleet keeps
delivering while exploring; the stored action is the one actually taken. Evaluations are greedy (epsilon 0, no prior).

Reference + abort: at the start of every run that is not skipped (fresh or resumed) the timeout rule is evaluated on
the 5 EVAL_SEEDS through run_episode in the same pool and stored as log.json["reference_pick_rate"] = {mean, values};
a resumed run recomputes it (deterministic) and raises ValueError if it differs from the stored one. After every
interval at episode >= abort_after_frac * episodes (--abort-after-frac F, default EPS_FRAC: epsilon has reached EPS_END
and the net acts on its own; 0 checks from the first interval), if --abort-below B > 0 and eval_pick_rate_mean < B *
reference mean, the log is written with finished false and aborted = {episode, eval_pick_rate_mean, reference,
abort_below, abort_after_frac}, one ABORT line is printed and train_run returns status "aborted" (the run cannot be
resumed); main runs the remaining runs and exits 1 if any run aborted. B = 0 disables the check.

Rollouts: ONE persistent spawn mp.Pool per run (never per interval); every worker builds one env at a time (a fresh
env per episode, exactly as evaluate.run_seed does) and torch runs on one thread there. Workers return transitions;
all learning happens in the parent. An iteration is ITER_EPISODES episodes mapped with the ordered pool.map, so a run is
reproducible given its seed whatever the worker count. Per iteration the parent does max(1, new_transitions // 4)
gradient steps once the replay holds WARMUP transitions. Evaluation: greedy policy, 5 fixed seeds 1000-1004, at the
run's rate, every EVAL_EVERY episodes and at the last episode (an "interval"). Training episode seeds are
10_000 + 100_000 * run_seed + episode_index: disjoint from the held-out seeds 0-29 and the eval seeds.

--smoke: first of --rates, first of --seeds, 4 episodes, iteration = eval interval = 2 episodes, batch 32, warm-up 32,
2 workers unless --workers is given (--episodes is rejected with --smoke).
Existing run directory: a log whose config version is not learned_recovery.FORMAT_VERSION raises ValueError (with or
without --resume); with --resume a finished run is skipped without touching any file, an unfinished run continues
from its last interval, an aborted run raises ValueError, and a stored config that differs from the requested one
raises ValueError. WITHOUT --resume an
existing run directory (one with a log.json) raises ValueError: nothing is overwritten or skipped silently.
The replay buffer is not saved, so a resumed run is not bit-identical to an uninterrupted one (it re-fills the buffer
and waits for the warm-up again). --max-intervals N stops this invocation after N intervals and leaves the run
unfinished (time-slicing; also how the resume path is tested).
Workers: --workers (bare or empty = unset), else SCHED_WORKERS, else os.cpu_count() - 2; at most ITER_EPISODES.
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import evaluate as ev  # noqa: E402
from sweep import MEDIUM_8, point_spec  # noqa: E402

from warehouse_rl import learned_recovery as lr  # noqa: E402
from warehouse_rl.policy import StuckAwareCtaPolicy  # noqa: E402
from warehouse_rl.recovery import ACTIONS, TimeoutRecovery  # noqa: E402

DISPATCHER = "stuck_aware_cta"
EVAL_SEEDS = [1000, 1001, 1002, 1003, 1004]
TRAIN_SEED_BASE, TRAIN_SEED_STRIDE = 10_000, 100_000
MAX_EPISODES = TRAIN_SEED_STRIDE - 1
DEFAULT_RATES, DEFAULT_SEEDS = "1,2,4", "0,1,2"
DEFAULT_STEPS = 500

# hyper-parameters (all recorded in train_config)
ITER_EPISODES = 8        # episodes per rollout iteration (one per worker on 8 workers)
EVAL_EVERY = 40          # episodes between evaluations
BATCH, WARMUP, CAPACITY = 256, 2000, 200_000
LR, TARGET_SYNC, CLIP_NORM = 1e-3, 1000, 10.0   # TARGET_SYNC in gradient steps (hard sync)
GRAD_PER_NEW = 4         # gradient steps per iteration = max(1, new_transitions // GRAD_PER_NEW)
EPS_START, EPS_END, EPS_FRAC = 1.0, 0.05, 0.5   # linear over the first EPS_FRAC of the episodes
# Budget for 9 runs (3 rates x 3 seeds) in about 10 h on 8 workers. Measured 11 Oct (seed 0, all-in: rollouts + learner +
# evals): 7145 s / 6400 episodes = 1.12 s/episode. 3200 x 1.12 ~ 3570 s ~ 1.0 h per run, so 9 runs ~ 8.9 h. Rollout
# alone at the last-interval rate of 539 steps/s: 3200 x 500 / 539 = 2970 s per run. 3200 is a multiple of EVAL_EVERY
# (40) and ITER_EPISODES (8). Fewer than the 6400 of the first run is defensible: the timeout-prior warm start shows
# deliveries from episode 1.
DEFAULT_EPISODES = 3200
RANDOM_SHARE = 0.1      # of the exploratory decisions (probability epsilon): this share uniform random, rest = timeout
ABORT_BELOW = 0.5       # abort a run when an interval's eval pick-rate mean < ABORT_BELOW * timeout reference mean
ABORT_AFTER_FRAC = EPS_FRAC  # ... checked only at intervals with episode >= this * episodes (exploration has decayed)
SMOKE = dict(episodes=4, iter_episodes=2, eval_every=2, batch=32, warmup=32, target_sync=10)


# ------------------------------------------------------------------------------------------------ reward bookkeeping
class WindowRecorder:
    """Semi-MDP bookkeeping per agent, independent of the env (see learned_recovery.py for the definition).

    decision(aid, t, x, a): the agent decides at step t; an open window of the same agent ends here (Delta = t - t0,
        zero when it is the same step: no step reward, discount 1); an abandon decision opens its window with
        -cost_unit * abandon_cost in R and U (also when that window is superseded in the same step). step_end(k, deliveries, stuck, relocated): step k has
        executed; every open window with t0 <= k accrues GAMMA ** (k - t0) * r_k. finish(t_end): close the windows
        still open at the episode end (done=True)."""

    def __init__(self, consts, n_agents, keep_trace=False):
        self.c, self.n_agents = consts, n_agents
        self.open, self.out = {}, []
        self.trace = [] if keep_trace else None
        self._decisions = []

    def decision(self, aid, t, x, a):
        o = self.open.pop(aid, None)
        if o is not None:
            self._close(aid, o, t, x, False)
        self.open[aid] = dict(x=x, a=a, t=t, R=0.0, U=0.0)
        if ACTIONS[a] == "abandon":
            # Charged once, at decision time, to the new window (offset 0: undiscounted), whatever the hook then does:
            # recovery.py executes "abandon" unconditionally on both the stuck and the clash path (_abandon resets the
            # counter and frees the task; there is no fallback), so the executed and the decided abandon coincide.
            pen = self.c["cost_unit"] * self.c["abandon_cost"]
            self.open[aid]["R"] -= pen
            self.open[aid]["U"] -= pen
        self._decisions.append((aid, t, int(a)))

    def step_end(self, k, deliveries, stuck, relocated):
        c = self.c
        share = c["line_reward"] * deliveries / self.n_agents
        for aid, o in self.open.items():
            r = (share - c["stuck_penalty"] * (aid in stuck)
                 - c["cost_unit"] * c["call_human_cost"] * (aid in relocated))
            o["R"] += c["gamma"] ** (k - o["t"]) * r
            o["U"] += r
        if self.trace is not None:
            self.trace.append(dict(k=k, deliveries=int(deliveries), stuck=sorted(stuck), relocated=sorted(relocated),
                                   decisions=self._decisions))
        self._decisions = []

    def finish(self, t_end):
        for aid, o in list(self.open.items()):
            self._close(aid, o, t_end, None, True)
        self.open = {}

    def _close(self, aid, o, t_next, x_next, done):
        delta = t_next - o["t"]
        x2 = np.zeros_like(o["x"]) if x_next is None else x_next
        self.out.append((o["x"], o["a"], o["R"], self.c["gamma"] ** delta, x2, done, aid, o["t"], delta, o["U"]))


def _arrays(transitions):
    if not transitions:
        return dict(X=np.zeros((0, len(lr.OBS_KEYS)), np.float32), A=np.zeros(0, np.int64), R=np.zeros(0),
                    DISC=np.zeros(0), X2=np.zeros((0, len(lr.OBS_KEYS)), np.float32), DONE=np.zeros(0, bool),
                    AID=np.zeros(0, np.int64), T0=np.zeros(0, np.int64), DELTA=np.zeros(0, np.int64))
    cols = list(zip(*transitions))
    return dict(X=np.stack(cols[0]).astype(np.float32), A=np.array(cols[1], np.int64), R=np.array(cols[2], float),
                DISC=np.array(cols[3], float), X2=np.stack(cols[4]).astype(np.float32),
                DONE=np.array(cols[5], bool), AID=np.array(cols[6], np.int64), T0=np.array(cols[7], np.int64),
                DELTA=np.array(cols[8], np.int64))


# ------------------------------------------------------------------------------------------------ rollouts
def _init_worker():
    torch.set_num_threads(1)


def run_episode(task):
    """One episode in this process. task: state_dict, epsilon, explore_seed, env_id, disturb, steps, seed,
    call_human_cost, consts, collect (bool), trace (bool), prior (None or "timeout"), random_share. collect=False is a
    plain greedy evaluation (the hook is not instrumented). task["policy"] == "timeout" runs the timeout rule itself as
    the hook's policy (the reference; needs collect=False, no state_dict). Returns pick_rate, deliveries, decisions, policy_calls, hook_decide_calls, event counts,
    reward_used and (collect) the transitions as arrays plus the undiscounted episode return."""
    steps, seed = task["steps"], task["seed"]
    if task.get("policy") == "timeout":
        if task["collect"]:
            raise ValueError("the timeout reference cannot collect transitions")
        pol = TimeoutRecovery()
    else:
        prior = task.get("prior")
        if prior == "timeout":
            prior = TimeoutRecovery()
        elif prior is not None:
            raise ValueError(f"unknown exploration prior {prior!r}; known: None, 'timeout'")
        pol = lr.LearnedRecovery.from_state_dict(task["state_dict"], lr.OBS_SCALE, task["epsilon"],
                                                 task["explore_seed"], prior=prior,
                                                 random_share=task.get("random_share", 1.0))
    env = lr.make_learned_env(task["env_id"], steps, task["disturb"], pol, task["call_human_cost"])
    try:
        hook = env.env
        rec = ctx = relocs = None
        if task["collect"]:
            rec = WindowRecorder(task["consts"], env.num_agents, task.get("trace", False))
            ctx, relocs = {"t": 0}, set()
            orig_decide, orig_relocate = hook._decide, hook._relocate  # per-instance wrappers; no class is edited

            def _decide(agent, is_clash):
                action = orig_decide(agent, is_clash)
                rec.decision(agent.id, ctx["t"], pol.last_x.numpy(), pol.last_idx)
                return action

            def _relocate(agent):
                ok = orig_relocate(agent)
                if ok:
                    relocs.add(agent.id)
                return ok

            hook._decide, hook._relocate = _decide, _relocate
        obs, info = env.reset(seed=seed)
        disp = StuckAwareCtaPolicy()
        disp.reset(env)
        deliveries = events = call_human_steps = 0
        busy_stuck_mismatch = 0
        for t in range(steps):
            if ctx is not None:
                ctx["t"] = t
            actions = disp.act(obs, info["action_mask"], info)
            obs, _, _, _, info = env.step(actions)
            d = int(info["shelf_deliveries"])
            deliveries += d
            events += int(info["recovery_stuck_events"]) + int(info["recovery_clash_events"])
            call_human_steps += int(info["call_human_steps"])  # the hook's own counter: executed calls x cost
            if rec is not None:
                stuck = {a.id for a in hook.agents if a.busy and hook.stuck_counters[a.id - 1].count > 0}
                busy_stuck_mismatch += int(len(stuck) != int(info["stuck_busy_agents"]))
                rec.step_end(t, d, stuck, relocs)
                relocs.clear()
        if rec is not None:
            rec.finish(steps)
        res = dict(seed=seed, steps=steps, deliveries=deliveries, pick_rate=deliveries * 3600 / (5 * steps),
                   decisions=events,
                   policy_calls=pol.calls if hasattr(pol, "calls") else hook.decide_calls, hook_decide_calls=hook.decide_calls,
                   reward_used=task["consts"], busy_stuck_mismatch=busy_stuck_mismatch,
                   call_human_steps=call_human_steps)
        if rec is not None:
            res.update(_arrays(rec.out))
            res["ep_return"] = float(sum(o[9] for o in rec.out))
            if rec.trace is not None:
                res["trace"] = rec.trace
        return res
    finally:
        env.close()


# ------------------------------------------------------------------------------------------------ replay + learning
class Replay:
    def __init__(self, capacity):
        n = len(lr.OBS_KEYS)
        self.cap, self.size, self.pos = capacity, 0, 0
        self.X, self.X2 = np.zeros((capacity, n), np.float32), np.zeros((capacity, n), np.float32)
        self.A, self.R = np.zeros(capacity, np.int64), np.zeros(capacity, np.float32)
        self.DISC, self.DONE = np.zeros(capacity, np.float32), np.zeros(capacity, np.float32)

    def add(self, arr):
        for i in range(len(arr["A"])):
            j = self.pos
            self.X[j], self.X2[j], self.A[j] = arr["X"][i], arr["X2"][i], arr["A"][i]
            self.R[j], self.DISC[j], self.DONE[j] = arr["R"][i], arr["DISC"][i], float(arr["DONE"][i])
            self.pos = (self.pos + 1) % self.cap
            self.size = min(self.size + 1, self.cap)

    def sample(self, n):
        idx = torch.randint(0, self.size, (n,)).numpy()  # global torch RNG: seeded by the run, saved in train_state.pt
        t = torch.from_numpy
        return t(self.X[idx]), t(self.A[idx]), t(self.R[idx]), t(self.DISC[idx]), t(self.X2[idx]), t(self.DONE[idx])


def dqn_loss(online, target, batch):
    """Double DQN: argmax from the online net, value from the target net, Huber loss."""
    x, a, r, disc, x2, done = batch
    q = online(x).gather(1, a[:, None]).squeeze(1)
    with torch.no_grad():
        a2 = online(x2).argmax(1, keepdim=True)
        y = r + disc * (1.0 - done) * target(x2).gather(1, a2).squeeze(1)
    return F.smooth_l1_loss(q, y)


def learn(online, target, opt, replay, cfg, n_steps, grad_steps):
    """n_steps double-DQN gradient steps; hard target sync whenever the cumulative grad_steps hits a multiple of
    cfg["target_sync"]. Returns (grad_steps, loss_sum, loss_n)."""
    loss_sum, loss_n = 0.0, 0
    for _ in range(n_steps):
        loss = dqn_loss(online, target, replay.sample(cfg["batch"]))
        opt.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(online.parameters(), cfg["clip_norm"])
        opt.step()
        grad_steps += 1
        loss_sum += float(loss.detach())
        loss_n += 1
        if grad_steps % cfg["target_sync"] == 0:
            target.load_state_dict(online.state_dict())
    return grad_steps, loss_sum, loss_n


def epsilon_at(episode_index, episodes):
    horizon = max(1, int(episodes * EPS_FRAC))
    return max(EPS_END, EPS_START + (EPS_END - EPS_START) * min(1.0, episode_index / horizon))


# ------------------------------------------------------------------------------------------------ run management
def build_config(rate, run_seed, steps, episodes, smoke, random_share=RANDOM_SHARE, abort_below=ABORT_BELOW,
                 abort_after_frac=ABORT_AFTER_FRAC):
    hp = dict(iter_episodes=ITER_EPISODES, eval_every=EVAL_EVERY, batch=BATCH, warmup=WARMUP, target_sync=TARGET_SYNC)
    if smoke:
        hp.update({k: v for k, v in SMOKE.items() if k != "episodes"})
        episodes = SMOKE["episodes"]
    cfg = dict(version=lr.FORMAT_VERSION, algo="double_dqn", rate=rate, seed=run_seed, env=MEDIUM_8,
               dispatcher=DISPATCHER, steps=steps, episodes=episodes, smoke=bool(smoke),
               disturb=point_spec("breakdown", rate)[1], eval_seeds=EVAL_SEEDS, train_seed_base=TRAIN_SEED_BASE,
               train_seed_stride=TRAIN_SEED_STRIDE, capacity=CAPACITY, lr=LR, clip_norm=CLIP_NORM,
               grad_per_new=GRAD_PER_NEW, epsilon=dict(start=EPS_START, end=EPS_END, frac=EPS_FRAC), hidden=lr.HIDDEN,
               call_human_cost=lr.CALL_HUMAN_COST, abandon_cost=lr.ABANDON_COST, reward=lr.reward_constants(),
               explore=dict(prior="timeout", random_share=random_share), abort_below=abort_below,
               abort_after_frac=abort_after_frac, **hp)
    return json.loads(json.dumps(cfg))


def run_dir_name(rate, run_seed):
    return f"rate{rate}_seed{run_seed}"


def _atomic_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _atomic_torch(path, obj):
    tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def reference_pick_rate(pool, cfg, consts):
    """The timeout rule on cfg["eval_seeds"] through run_episode in `pool`: {mean, values}."""
    tasks = [dict(policy="timeout", state_dict=None, epsilon=0.0, explore_seed=0, env_id=cfg["env"],
                  disturb=cfg["disturb"], steps=cfg["steps"], seed=s, call_human_cost=cfg["call_human_cost"],
                  consts=consts, collect=False) for s in cfg["eval_seeds"]]
    values = [float(r["pick_rate"]) for r in pool.map(run_episode, tasks, chunksize=1)]
    return dict(mean=float(np.mean(values)), values=values)


def train_run(rate, run_seed, steps, episodes, smoke, workers, results_dir, resume, max_intervals=None,
              abort_below=ABORT_BELOW, random_share=RANDOM_SHARE, abort_after_frac=ABORT_AFTER_FRAC):
    """Returns a summary dict {status: skipped|finished|stopped|aborted, ...}."""
    if abort_below < 0:
        raise ValueError(f"abort_below must be >= 0, got {abort_below!r}")
    if not 0.0 <= abort_after_frac <= 1.0:
        raise ValueError(f"abort_after_frac must be in [0, 1], got {abort_after_frac!r}")
    if not 0.0 <= random_share <= 1.0:
        raise ValueError(f"random_share must be in [0, 1], got {random_share!r}")
    cfg = build_config(rate, run_seed, steps, episodes, smoke, random_share, abort_below, abort_after_frac)
    run_dir = Path(results_dir) / run_dir_name(rate, run_seed)
    log_path, ckpt_path, state_path = run_dir / "log.json", run_dir / "checkpoint.pt", run_dir / "train_state.pt"
    log = None
    if log_path.exists():
        log = json.loads(log_path.read_text())
        if log["config"].get("version") != lr.FORMAT_VERSION:
            raise ValueError(f"{run_dir}: stored run has format version {log['config'].get('version')!r}, this trainer "
                             f"writes {lr.FORMAT_VERSION} (v1 used a zero-cost abandon reward); not skipped, not "
                             f"continued: move or delete {run_dir} and retrain")
        if not resume:
            raise ValueError(f"{run_dir} already holds a run; pass --resume to skip it (finished) or continue it")
        if log.get("aborted") is not None:
            raise ValueError(f"{run_dir}: aborted run, not continuable; delete {run_dir} to retrain")
        if log["config"] != cfg:
            raise ValueError(f"{log_path} stores config {log['config']!r}, requested {cfg!r}; refusing to resume")
        if log["finished"]:
            print(f"skip rate {rate} seed {run_seed}: finished ({log_path})")
            return dict(status="skipped")
        if not state_path.exists():
            raise ValueError(f"{run_dir}: unfinished run without train_state.pt, cannot resume")
    run_dir.mkdir(parents=True, exist_ok=True)

    online = target = opt = None
    if log is None:
        torch.manual_seed(run_seed)
        online = lr.QNet()  # torch.manual_seed(run_seed) immediately before construction
        target = lr.QNet()
        target.load_state_dict(online.state_dict())
        opt = torch.optim.Adam(online.parameters(), lr=cfg["lr"])
        done_eps = grad_steps = env_steps = 0
        wall_prior, intervals = 0.0, []
    else:
        st = torch.load(state_path, map_location="cpu", weights_only=True)
        online, target = lr.QNet(), lr.QNet()
        online.load_state_dict(st["online"])
        target.load_state_dict(st["target"])
        opt = torch.optim.Adam(online.parameters(), lr=cfg["lr"])
        opt.load_state_dict(st["optimizer"])
        torch.set_rng_state(st["torch_rng"])
        done_eps, grad_steps, env_steps, wall_prior = st["episodes_done"], st["gradient_steps"], st["env_steps"], \
            st["wall_s"]
        intervals = [iv for iv in log["intervals"] if iv["episode"] <= done_eps]
        print(f"resume rate {rate} seed {run_seed} from episode {done_eps} (replay buffer starts empty)")
    def save_state(wall):
        _atomic_torch(state_path, dict(
            online=online.state_dict(), target=target.state_dict(), optimizer=opt.state_dict(),
            torch_rng=torch.get_rng_state(), episodes_done=done_eps, gradient_steps=grad_steps,
            env_steps=env_steps, wall_s=wall))

    if log is None:
        save_state(0.0)  # episode-0 state before any log exists (see the module docstring)
    consts = lr.reward_constants(cfg["call_human_cost"], cfg["abandon_cost"])
    replay = Replay(cfg["capacity"])
    t0 = time.time()
    total = cfg["episodes"]
    reward_used = None
    roll_steps = roll_wall = 0.0
    interval_n = 0
    loss_sum, loss_n = 0.0, 0
    ep_returns, interval_decisions, interval_roll = [], 0, [0.0, 0.0]
    first_iter = True
    ctx = mp.get_context("spawn")

    def task(seed, eps, expl, collect, sd):
        train = collect  # rollouts explore with the timeout prior; evaluations are greedy, no prior
        return dict(state_dict=sd, epsilon=eps, explore_seed=expl, env_id=cfg["env"], disturb=cfg["disturb"],
                    steps=cfg["steps"], seed=seed, call_human_cost=cfg["call_human_cost"], consts=consts,
                    collect=collect, prior=cfg["explore"]["prior"] if train else None,
                    random_share=cfg["explore"]["random_share"])

    def write_log(finished, aborted=None):
        doc = dict(config=cfg, intervals=intervals, finished=finished, reward_used=reward_used,
                   reference_pick_rate=reference)
        if aborted is not None:
            doc["aborted"] = aborted
        _atomic_text(log_path, json.dumps(doc, indent=2))

    with ctx.Pool(workers, initializer=_init_worker) as pool:
        reference = reference_pick_rate(pool, cfg, consts)
        if log is not None and log.get("reference_pick_rate") != reference:
            raise ValueError(f"{log_path}: stored reference_pick_rate {log.get('reference_pick_rate')!r} != "
                             f"recomputed {reference!r}; refusing to resume")
        print(f"[rate {rate} seed {run_seed}] timeout reference pick_rate mean {reference['mean']:.2f} "
              f"values {reference['values']}", flush=True)
        while done_eps < total:
            boundary = min(total, (done_eps // cfg["eval_every"] + 1) * cfg["eval_every"])
            n = min(cfg["iter_episodes"], boundary - done_eps)
            sd = {k: v.detach().clone() for k, v in online.state_dict().items()}
            tasks = []
            for e in range(done_eps, done_eps + n):
                seed = cfg["train_seed_base"] + cfg["train_seed_stride"] * run_seed + e
                tasks.append(task(seed, epsilon_at(e, total), seed, True, sd))
            tr = time.time()
            results = pool.map(run_episode, tasks, chunksize=1)  # ordered
            dt = time.time() - tr
            if not first_iter or n == total:  # the first iteration pays worker spawn + torch import
                roll_steps += n * cfg["steps"]
                roll_wall += dt
                interval_roll[0] += n * cfg["steps"]
                interval_roll[1] += dt
            first_iter = False
            new = 0
            for r in results:
                if r["reward_used"] != consts:
                    raise RuntimeError(f"worker used reward constants {r['reward_used']} != {consts}")
                reward_used = r["reward_used"]
                if r["policy_calls"] != r["hook_decide_calls"] or r["policy_calls"] != r["decisions"]:
                    raise RuntimeError(f"decision accounting broke: {r['policy_calls']} {r['hook_decide_calls']} "
                                       f"{r['decisions']}")
                if r["busy_stuck_mismatch"]:
                    raise RuntimeError(f"reward stuck flag disagrees with info['stuck_busy_agents'] on "
                                       f"{r['busy_stuck_mismatch']} steps (seed {r['seed']})")
                replay.add(r)
                new += len(r["A"])
                ep_returns.append(r["ep_return"])
                interval_decisions += r["decisions"]
            done_eps += n
            env_steps += n * cfg["steps"]
            if replay.size >= cfg["warmup"] and replay.size >= cfg["batch"]:
                grad_steps, ls, ln = learn(online, target, opt, replay, cfg, max(1, new // cfg["grad_per_new"]),
                                           grad_steps)
                loss_sum += ls
                loss_n += ln
            if done_eps % cfg["eval_every"] == 0 or done_eps == total:
                sd = {k: v.detach().clone() for k, v in online.state_dict().items()}
                evals = pool.map(run_episode, [task(s, 0.0, 0, False, sd) for s in cfg["eval_seeds"]], chunksize=1)
                rates = [e["pick_rate"] for e in evals]
                finished = done_eps == total
                interval_n += 1
                intervals.append(dict(
                    episode=done_eps, env_steps=env_steps, wall_s=wall_prior + time.time() - t0,
                    train_reward_mean=float(np.mean(ep_returns)), eval_pick_rate_mean=float(np.mean(rates)),
                    eval_pick_rates=rates, epsilon=epsilon_at(done_eps - 1, total),
                    loss_mean=(loss_sum / loss_n) if loss_n else None, decisions=interval_decisions,
                    gradient_steps=grad_steps,
                    rollout_steps_per_s=(interval_roll[0] / interval_roll[1]) if interval_roll[1] else None))
                loss_sum, loss_n, ep_returns, interval_decisions, interval_roll = 0.0, 0, [], 0, [0.0, 0.0]
                # order matters: checkpoint, log, then resume state (see the module docstring)
                lr.save_checkpoint(ckpt_path, online.state_dict(), consts, cfg)
                iv = intervals[-1]
                # abort decided before the log write, so a run that aborts at its last interval is never on disk as
                # finished: true (not even for an instant); no check during the grace period
                abort = None
                if (abort_below > 0 and done_eps >= abort_after_frac * total
                        and iv["eval_pick_rate_mean"] < abort_below * reference["mean"]):
                    abort = dict(episode=done_eps, eval_pick_rate_mean=iv["eval_pick_rate_mean"],
                                 reference=reference["mean"], abort_below=abort_below,
                                 abort_after_frac=abort_after_frac)
                write_log(finished and abort is None, abort)
                save_state(wall_prior + time.time() - t0)
                print(f"[rate {rate} seed {run_seed}] ep {done_eps}/{total} train_reward {iv['train_reward_mean']:.3f} "
                      f"eval_pick_rate {iv['eval_pick_rate_mean']:.2f} eps {iv['epsilon']:.2f} "
                      f"loss {iv['loss_mean']} grad_steps {grad_steps} wall {iv['wall_s']:.0f} s", flush=True)
                if abort is not None:
                    print(f"ABORT rate {rate} seed {run_seed} at episode {done_eps}: eval "
                          f"{abort['eval_pick_rate_mean']:.2f} < {abort_below} x reference {reference['mean']:.2f}",
                          flush=True)
                    return dict(status="aborted", episodes_done=done_eps, aborted=abort)
                if max_intervals is not None and interval_n >= max_intervals and not finished:
                    return dict(status="stopped", episodes_done=done_eps)
    return dict(status="finished", wall_s=time.time() - t0, rollout_steps=roll_steps, rollout_wall_s=roll_wall)


def parse_rates(s):
    out = []
    for tok in str(s).split(","):
        tok = tok.strip()
        try:
            v = float(tok)
        except ValueError:
            raise ValueError(f"bad rate {tok!r}") from None
        if not v > 0:
            raise ValueError(f"rate must be > 0, got {tok!r}")
        v = int(v) if v == int(v) else v
        if v not in out:
            out.append(v)
    if not out:
        raise ValueError("empty rates")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rates", default=DEFAULT_RATES)
    p.add_argument("--seeds", default=DEFAULT_SEEDS)
    p.add_argument("--workers", type=ev.workers_arg, nargs="?", default=None)  # bare/empty = unset
    p.add_argument("--episodes", type=int, default=None, help=f"episodes per run (default {DEFAULT_EPISODES})")
    p.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--results-dir", default=str(REPO / "results" / "recovery_train"))
    p.add_argument("--max-intervals", type=int, default=None)
    p.add_argument("--random-share", type=float, default=RANDOM_SHARE,
                   help="share of exploratory decisions that are uniform random, the rest follow the timeout rule "
                        f"(default {RANDOM_SHARE})")
    p.add_argument("--abort-below", type=float, default=ABORT_BELOW,
                   help=f"abort a run when an interval's eval pick-rate mean < this x the timeout reference mean "
                        f"(default {ABORT_BELOW}; 0 disables)")
    p.add_argument("--abort-after-frac", type=float, default=ABORT_AFTER_FRAC,
                   help="check the abort only at intervals with episode >= this x episodes "
                        f"(default {ABORT_AFTER_FRAC} = EPS_FRAC; 0 = from the first interval)")
    a = p.parse_args()
    if not 0.0 <= a.random_share <= 1.0:
        raise ValueError(f"--random-share must be in [0, 1], got {a.random_share}")
    if a.abort_below < 0:
        raise ValueError(f"--abort-below must be >= 0, got {a.abort_below}")
    if not 0.0 <= a.abort_after_frac <= 1.0:
        raise ValueError(f"--abort-after-frac must be in [0, 1], got {a.abort_after_frac}")
    rates = parse_rates(a.rates)
    seeds = ev.parse_seeds(a.seeds)
    if a.smoke:
        if a.episodes is not None:
            raise ValueError("--episodes cannot be combined with --smoke (smoke trains 4 episodes)")
        rates, seeds = rates[:1], seeds[:1]
        workers = a.workers if a.workers is not None else 2
        episodes = SMOKE["episodes"]
    else:
        episodes = a.episodes if a.episodes is not None else DEFAULT_EPISODES
        workers = ev.resolve_workers(a.workers, os.environ)
    if a.steps < 1 or not 1 <= episodes <= MAX_EPISODES:
        raise ValueError(f"need steps >= 1 and 1 <= episodes <= {MAX_EPISODES}")
    if workers < 1:
        raise ValueError("--workers must be >= 1")
    workers = min(workers, ITER_EPISODES if not a.smoke else SMOKE["iter_episodes"])
    results_dir = Path(a.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    print(f"{len(rates) * len(seeds)} run(s), {episodes} episodes x {a.steps} steps, {workers} workers")
    t0 = time.time()
    steps_s, aborted = [], []
    for rate in rates:
        for run_seed in seeds:
            out = train_run(rate, run_seed, a.steps, episodes, a.smoke, workers, results_dir, a.resume,
                            a.max_intervals, abort_below=a.abort_below, random_share=a.random_share,
                            abort_after_frac=a.abort_after_frac)
            if out["status"] == "aborted":
                aborted.append((rate, run_seed))
            if out["status"] == "finished" and out["rollout_wall_s"] > 0:
                sps = out["rollout_steps"] / out["rollout_wall_s"]
                steps_s.append(sps)
                print(f"[rate {rate} seed {run_seed}] env steps/s (rollout only, steady state, {workers} workers, "
                      f"learned policy in the loop): {sps:.0f}; run wall {out['wall_s']:.0f} s", flush=True)
    print(f"total {time.time() - t0:.1f} s" + (f"; mean rollout steps/s {np.mean(steps_s):.0f}" if steps_s else ""))
    if aborted:
        print(f"ABORTED runs (rate, seed): {aborted}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
