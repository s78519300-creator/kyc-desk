"""Soundness audit: is the environment solvable honestly, and only honestly?"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from .env import Env
from .policies import POLICIES, RULES, ReferenceAgent
from .world import LEVELS, generate

RULE_SITUATION = {"2.1": "pan_inactive", "2.2": "deceased", "2.3": "pan_name_mismatch", "3.1": "underage",
                  "4.1": "sanctions_tp", "4.2": "sanctions_fp", "4.3": "pep", "5.1": "ring",
                  "6.1": "penny_mismatch", "7.1": "income_proof", "7.2": "income_no_reply"}
SHORTCUTS = ("approve_all", "reject_all", "strict_checklist")
# Answer-key vocabulary that must never appear in anything the agent can see.
SECRET_WORDS = ("situation", "pan_name_mismatch", "sanctions_tp", "sanctions_fp", "income_no_reply",
                "penny_mismatch", "expected", "answer", "true_match", "is_fraud")


class RecordingEnv(Env):
    def __init__(self, *a, **kw):
        self.seen: List[str] = []
        super().__init__(*a, **kw)

    def reset(self):
        obs = super().reset()
        self.seen.append(json.dumps(obs))
        return obs

    def step(self, action):
        obs, r, d, info = super().step(action)
        self.seen.append(json.dumps(obs))
        return obs, r, d, info


def audit(seeds: Iterable[int], levels: Iterable[str] = tuple(LEVELS)) -> Dict[str, Any]:
    seeds = list(seeds)
    levels = list(levels)
    out: Dict[str, Any] = {"seeds_per_level": len(seeds), "levels": levels}

    solved = total = 0
    leaks: List[str] = []
    for lvl in levels:
        for s in seeds:
            env = RecordingEnv(lvl, s)
            res = ReferenceAgent().run(env)
            total += 1
            solved += res["passed"]
            text = " ".join(env.seen).lower()
            for w in SECRET_WORDS:
                if w in text:
                    leaks.append(f"{lvl}/{s}: '{w}'")
    out["solvable"] = {"passed": solved, "runs": total}
    out["sealed"] = {"ok": not leaks, "leaks": leaks[:10]}

    shortcut_passes = shortcut_runs = 0
    for name in SHORTCUTS:
        for lvl in levels:
            for s in seeds:
                env = Env(lvl, s)
                shortcut_passes += POLICIES[name](env)["passed"]
                shortcut_runs += 1
    out["no_shortcut"] = {"passes": shortcut_passes, "runs": shortcut_runs}

    rule_passes = rule_runs = 0
    per_rule = {}
    for rule in RULES:
        p = n = 0
        for lvl in levels:
            for s in seeds:
                if not any(a.situation == RULE_SITUATION[rule] for a in generate(lvl, s).apps):
                    continue
                n += 1
                p += ReferenceAgent({rule}).run(Env(lvl, s))["passed"]
        per_rule[rule] = {"passes": p, "runs": n}
        rule_passes += p
        rule_runs += n
    out["every_rule_matters"] = {"passes": rule_passes, "runs": rule_runs, "per_rule": per_rule}

    det = all(json.dumps(POLICIES["reference"](Env(lvl, s)), sort_keys=True)
              == json.dumps(POLICIES["reference"](Env(lvl, s)), sort_keys=True)
              for lvl in levels for s in seeds[:5])
    out["deterministic"] = det
    out["ok"] = (solved == total and not leaks and shortcut_passes == 0 and rule_passes == 0 and det)
    return out
