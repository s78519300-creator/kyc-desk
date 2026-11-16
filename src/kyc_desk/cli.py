"""kyc-desk command line."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import List, Optional

from . import __version__
from .audit import audit
from .env import Env, tool_schemas
from .policies import POLICIES, run_policy
from .world import LEVELS


def parse_seeds(text: str) -> List[int]:
    out: List[int] = []
    for part in text.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def _levels(text: str) -> List[str]:
    return list(LEVELS) if text == "all" else [text]


def summary(res: dict) -> str:
    lines = [f"level {res['level']}, seed {res['seed']}: {'PASSED' if res['passed'] else 'failed'}",
             f"  documents right: {res['documents_correct']}/{res['documents']}   reward {res['reward']}",
             f"  loan value approved to fraudsters: INR {res['loan_value_approved_to_fraudsters_inr']:,}",
             f"  legitimate customers lost: {res['legitimate_customers_lost']}   tool calls: {res['tool_calls']}"]
    for d in res["details"]:
        if not d["correct"]:
            why = d["outcome"] if d["outcome"] != "ok" else "process violation"
            lines.append(f"  x {d['app_id']} ({d['situation']}): {why}; expected {d['expected']['decision']}, "
                         f"got {d['actual']['decision']}")
    for v in res["violations"][:20]:
        lines.append(f"  ! {v}")
    return "\n".join(lines) + "\n"


def cmd_play(level: str, seed: int) -> int:
    env = Env(level, seed)
    print(env.brief())
    print("\nType a tool name and JSON arguments, e.g.  verify_pan {\"app_id\": \"APP-001\"}   (tools: 'help')")
    while not env.done:
        try:
            line = input(f"[day {env.day}] > ").strip()
        except EOFError:
            break
        if not line:
            continue
        if line == "help":
            for t in tool_schemas():
                print(f"  {t['name']:<18}{t['description']}")
            continue
        tool, _, rest = line.partition(" ")
        try:
            args = json.loads(rest) if rest.strip() else {}
        except json.JSONDecodeError as exc:
            print(f"bad JSON: {exc}")
            continue
        obs, _, done, info = env.step({"tool": tool, "args": args})
        print(json.dumps(obs, indent=2))
        if done:
            print(summary(info["result"]))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="kyc-desk", description="An Indian KYC onboarding desk for training and "
                                                             "testing AI agents.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="run a scripted policy on one episode")
    r.add_argument("--level", choices=list(LEVELS), default="medium")
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--policy", choices=list(POLICIES), default="reference")
    r.add_argument("--json", help="write the full result to this file")

    b = sub.add_parser("bench", help="scripted baselines over many seeds")
    b.add_argument("--seeds", default="0-49")
    b.add_argument("--level", default="all", choices=["all", *LEVELS])

    a = sub.add_parser("audit", help="soundness checks: solvable, no shortcuts, every rule matters, sealed")
    a.add_argument("--seeds", default="0-49")
    a.add_argument("--level", default="all", choices=["all", *LEVELS])
    a.add_argument("--json", help="write the audit to this file")

    pl = sub.add_parser("play", help="do the job yourself in the terminal")
    pl.add_argument("--level", choices=list(LEVELS), default="easy")
    pl.add_argument("--seed", type=int, default=0)

    m = sub.add_parser("mcp", help="serve one episode over MCP (stdio)")
    m.add_argument("--level", choices=list(LEVELS), default="medium")
    m.add_argument("--seed", type=int, default=0)
    m.add_argument("--result", help="write the scored result here when the episode ends")

    e = sub.add_parser("export", help="write a task list (JSONL) for an agent harness")
    e.add_argument("--level", default="all", choices=["all", *LEVELS])
    e.add_argument("--seeds", default="0-99")
    e.add_argument("--out", "-o", required=True)

    lm = sub.add_parser("llm", help="run a language model through an OpenAI-compatible API")
    lm.add_argument("--model", required=True)
    lm.add_argument("--base-url", default="https://api.openai.com/v1",
                    help="any OpenAI-compatible endpoint (OpenRouter, Groq, Gemini, vLLM, Ollama ...)")
    lm.add_argument("--api-key-env", help="environment variable that holds the key (default: first one set of "
                                          "OPENAI_API_KEY, OPENROUTER_API_KEY, GROQ_API_KEY, GEMINI_API_KEY)")
    lm.add_argument("--level", choices=list(LEVELS), default="easy")
    lm.add_argument("--seeds", default="0")
    lm.add_argument("--out-dir", help="save each scored result and the full tool trace here")

    args = p.parse_args(argv)

    if args.command == "llm":
        import os
        from .llm import LLMError, api_key_from_env, run_llm
        key = api_key_from_env(args.api_key_env)
        results = []
        for s in parse_seeds(args.seeds):
            trace: list = []
            try:
                res = run_llm(args.model, args.level, s, args.base_url, key, log=trace)
            except LLMError as exc:
                print(f"seed {s}: API error: {exc}", file=sys.stderr)
                return 2
            results.append(res)
            sys.stdout.write(summary(res))
            if args.out_dir:
                os.makedirs(args.out_dir, exist_ok=True)
                with open(os.path.join(args.out_dir, f"{args.level}-{s}.json"), "w", encoding="utf-8") as fh:
                    json.dump({"result": res, "trace": trace}, fh, indent=2)
        passed = sum(r["passed"] for r in results)
        docs = sum(r["documents_correct"] for r in results) / max(1, sum(r["documents"] for r in results))
        print(f"{args.model} on {args.level}: passed {passed}/{len(results)}, documents right {docs:.0%}")
        return 0

    if args.command == "run":
        res = run_policy(args.policy, args.level, args.seed)
        sys.stdout.write(summary(res))
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=2)
        return 0

    if args.command == "bench":
        seeds = parse_seeds(args.seeds)
        print(f"{'level':<8}{'policy':<18}{'pass':>6}{'docs right':>12}{'fraud loss':>14}{'customers lost':>16}")
        for lvl in _levels(args.level):
            for name in POLICIES:
                rs = [run_policy(name, lvl, s) for s in seeds]
                docs = sum(x["documents_correct"] for x in rs) / sum(x["documents"] for x in rs)
                loss = statistics.mean(x["loan_value_approved_to_fraudsters_inr"] for x in rs)
                lost = statistics.mean(x["legitimate_customers_lost"] for x in rs)
                passed = sum(x["passed"] for x in rs) / len(rs)
                print(f"{lvl:<8}{name:<18}{passed:>6.0%}{docs:>12.0%}{'INR ' + format(round(loss), ','):>14}"
                      f"{lost:>16.1f}")
        return 0

    if args.command == "audit":
        res = audit(parse_seeds(args.seeds), _levels(args.level))
        print(f"Soundness audit over {res['seeds_per_level']} seeds x {len(res['levels'])} levels")
        print(f"  solvable: reference clerk passes {res['solvable']['passed']} of {res['solvable']['runs']}")
        print(f"  no shortcut: {res['no_shortcut']['passes']} passes in {res['no_shortcut']['runs']} runs "
              f"(approve all, reject all, strict checklist)")
        er = res["every_rule_matters"]
        print(f"  every rule matters: {er['passes']} passes in {er['runs']} runs with one rule switched off")
        print(f"  deterministic: {'yes' if res['deterministic'] else 'NO'}")
        print(f"  sealed (no answer-key words in observations): {'yes' if res['sealed']['ok'] else 'NO'}")
        print("AUDIT PASSED" if res["ok"] else "AUDIT FAILED")
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=2)
        return 0 if res["ok"] else 1

    if args.command == "play":
        return cmd_play(args.level, args.seed)

    if args.command == "mcp":
        from .mcp_server import serve
        serve(args.level, args.seed, args.result)
        return 0

    if args.command == "export":
        n = 0
        with open(args.out, "w", encoding="utf-8") as fh:
            for lvl in _levels(args.level):
                for s in parse_seeds(args.seeds):
                    env = Env(lvl, s)
                    fh.write(json.dumps({
                        "task_id": f"kyc-desk/{lvl}/{s}", "instruction": env.brief(),
                        "launch": ["python", "-m", "kyc_desk", "mcp", "--level", lvl, "--seed", str(s),
                                   "--result", f"result-{lvl}-{s}.json"],
                        "success": "result.passed == true", "documents": len(env.world.apps),
                        "days": env.world.days}) + "\n")
                    n += 1
        print(f"wrote {n} tasks to {args.out}", file=sys.stderr)
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
