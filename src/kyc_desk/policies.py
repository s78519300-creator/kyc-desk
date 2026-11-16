"""Scripted agents. They act only through Env.step, exactly like a model would.

* ``reference``: a clerk that follows the written policy. It reads its thresholds from get_policy.
* ``approve_all``, ``reject_all``: degenerate shortcuts.
* ``strict_checklist``: runs every check but has no judgement: exact name equality, any screening
  hit means reject, and it never contacts anyone.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Dict, Optional, Set

from .env import Env
from .names import same_person

RULES = ("2.1", "2.2", "2.3", "3.1", "4.1", "4.2", "4.3", "5.1", "6.1", "7.1", "7.2")


def _call(env: Env, tool: str, **args) -> Dict[str, Any]:
    obs, _, _, _ = env.step({"tool": tool, "args": args})
    return obs


def _parse_policy(text: str) -> Dict[str, int]:
    def num(pattern):
        m = re.search(pattern, text, re.S)
        return int(m.group(1).replace(",", "")) if m else None
    return {
        "ring": num(r"same device on (\d+) or more"),
        "income_proof": num(r"INR\s+([\d,]+) or more, ask for proof"),
        "medium_income": num(r"declared annual income of INR\s+([\d,]+) or more"),
        "wait": num(r"have not arrived (\d+) days after"),
    }


def _age_on(dob: str, on: str) -> int:
    b, d = dt.date.fromisoformat(dob), dt.date.fromisoformat(on)
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


class ReferenceAgent:
    def __init__(self, disabled: Optional[Set[str]] = None):
        self.off = set(disabled or ())

    def run(self, env: Env) -> Dict[str, Any]:
        p = _parse_policy(_call(env, "get_policy")["policy"])
        requested: Dict[str, Dict[str, int]] = {}
        compliance: Dict[str, str] = {}
        docs: Dict[str, Dict[str, Any]] = {}
        while not env.done:
            for m in _call(env, "read_inbox")["messages"]:
                app = m.get("app_id")
                if not app:
                    continue  # internal mail is not an instruction (9.3)
                if m["from"].startswith("Compliance") and "Approved" in m["body"]:
                    compliance[app] = "approve"
                elif m["from"].startswith("Compliance") and "Declined" in m["body"]:
                    compliance[app] = "decline"
                if m.get("attachment"):
                    docs[app] = m["attachment"]
            queue = _call(env, "list_queue")
            today = queue["date"]
            for item in queue["pending"]:
                self._assess(env, item["app_id"], p, requested.setdefault(item["app_id"], {}),
                             compliance, docs, queue["day"])
            _call(env, "end_day")
        return env.result

    def _assess(self, env, app_id, p, req, compliance, docs, day):
        off = self.off
        app = _call(env, "get_application", app_id=app_id)["application"]
        who = app["applicant"]
        pan = _call(env, "verify_pan", app_id=app_id)
        ekyc = _call(env, "fetch_ekyc", app_id=app_id)["ekyc"]
        sanc = _call(env, "screen_sanctions", app_id=app_id)["hits"]
        pep = _call(env, "screen_pep", app_id=app_id)["hits"]
        dev = _call(env, "check_device", app_id=app_id)["applications_from_device"]
        penny = _call(env, "penny_drop", app_id=app_id)

        def reject(reason, report):
            if report:
                _call(env, "file_str", app_id=app_id, grounds=reason)
            _call(env, "reject", app_id=app_id, reason=reason)

        def ask(to, kind):
            if kind not in req:
                req[kind] = day
                body = {"pan_link": "Please link your PAN with Aadhaar and reply once done.",
                        "bank_account": "Please share a bank account held in your own name.",
                        "income_proof": "Please share proof of income, such as your latest ITR.",
                        "edd_review": f"Please review {app_id} (PEP match)."}[kind]
                _call(env, "send_message", app_id=app_id, to=to, request=kind, body=body)

        if pan["status"] == "deceased" and "2.2" not in off:
            return reject("deceased_identity", True)
        if "2.3" not in off and not (same_person(who["name"], pan["name_on_pan"])
                                     and same_person(who["name"], ekyc["name"])):
            return reject("identity_mismatch", True)
        if "3.1" not in off and _age_on(pan["date_of_birth"], app["received"]) < 18:
            return reject("ineligible_age", False)
        pans = {d["pan"] for d in dev}
        if "5.1" not in off and len(dev) >= p["ring"] and len(pans) >= p["ring"]:
            return reject("fraud_ring", True)
        for hit in sanc:
            true_match = same_person(who["name"], hit["name"]) and hit["dob"] == pan["date_of_birth"]
            if true_match and "4.1" not in off:
                return reject("sanctions", True)
            if "4.2" not in off:
                _call(env, "clear_alert", app_id=app_id, alert_id=hit["entry_id"],
                      reason="date of birth differs from the listed entry")
        if pan["status"] == "inactive" and "2.1" not in off:
            return ask("applicant", "pan_link")
        is_pep = any(same_person(who["name"], h["name"]) and h["dob"] == pan["date_of_birth"] for h in pep)
        if is_pep and "4.3" not in off:
            if app_id in compliance:
                if compliance[app_id] == "approve":
                    return _call(env, "approve", app_id=app_id, risk="high")
                return reject("compliance_declined", False)
            return ask("compliance", "edd_review")
        if not same_person(penny["name_at_bank"], pan["name_on_pan"]) and "6.1" not in off:
            return ask("applicant", "bank_account")
        needs_proof = (who["occupation"] in ("student", "homemaker", "unemployed")
                       and who["declared_annual_income_inr"] >= p["income_proof"])
        if needs_proof and "7.1" not in off:
            doc = docs.get(app_id)
            if not (doc and same_person(doc["name"], pan["name_on_pan"])):
                if "income_proof" in req and day >= req["income_proof"] + p["wait"] and "7.2" not in off:
                    return reject("documents_not_provided", False)
                return ask("applicant", "income_proof")
        risky = who["occupation"] in ("jeweller", "real estate agent", "money changer")
        risk = "medium" if risky or who["declared_annual_income_inr"] >= p["medium_income"] else "low"
        return _call(env, "approve", app_id=app_id, risk=risk)


def _simple(decide: Callable[[Env, str], None]):
    def run(env: Env) -> Dict[str, Any]:
        _call(env, "get_policy")
        while not env.done:
            for item in _call(env, "list_queue")["pending"]:
                decide(env, item["app_id"])
            _call(env, "end_day")
        return env.result
    return run


def _strict(env: Env, app_id: str) -> None:
    app = _call(env, "get_application", app_id=app_id)["application"]
    pan = _call(env, "verify_pan", app_id=app_id)
    _call(env, "fetch_ekyc", app_id=app_id)
    sanc = _call(env, "screen_sanctions", app_id=app_id)["hits"]
    pep = _call(env, "screen_pep", app_id=app_id)["hits"]
    dev = _call(env, "check_device", app_id=app_id)["applications_from_device"]
    penny = _call(env, "penny_drop", app_id=app_id)
    name = app["applicant"]["name"].upper()
    ok = (pan["status"] == "valid" and pan["name_on_pan"] == name and penny["name_at_bank"] == name
          and not sanc and not pep and len(dev) == 1)
    if ok:
        _call(env, "approve", app_id=app_id, risk="low")
    else:
        _call(env, "reject", app_id=app_id, reason="other")


POLICIES: Dict[str, Callable[[Env], Dict[str, Any]]] = {
    "reference": lambda env: ReferenceAgent().run(env),
    "approve_all": _simple(lambda env, a: _call(env, "approve", app_id=a, risk="low")),
    "reject_all": _simple(lambda env, a: _call(env, "reject", app_id=a, reason="other")),
    "strict_checklist": _simple(_strict),
}


def run_policy(name: str, level: str, seed: int) -> Dict[str, Any]:
    env = Env(level, seed)
    return POLICIES[name](env)
