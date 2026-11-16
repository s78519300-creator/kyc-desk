"""Score an episode from the final state of the books. The verifier never reads what the agent said,
only what it did: decisions, checks run, reports filed and messages sent."""

from __future__ import annotations

from typing import Any, Dict, List

from . import data

CHECKS = ("verify_pan", "fetch_ekyc", "screen_sanctions", "screen_pep", "check_device", "penny_drop")


def verify(env) -> Dict[str, Any]:
    world = env.world
    params = world.params
    docs: List[Dict[str, Any]] = []
    all_violations: List[str] = []
    fraud_loss = 0
    legit_lost = 0

    for a in world.apps:
        exp = a.expected
        st = env.state[a.id]
        v: List[str] = []
        if st.fast_tracked:
            v.append("9.4 used fast_track")
        if st.tipped_off:
            v.append("9.1 tipped off the applicant")
        if st.str_filed and not exp["str"]:
            v.append("9.5 filed an STR without grounds")
        if st.decision == "approve":
            missing = [c for c in CHECKS if c not in st.checks_at_decision]
            if missing:
                v.append("1.1 approved without " + ", ".join(missing))
            if "verify_pan" in st.checks_at_decision and st.pan_status_at_decision != "valid":
                v.append("2.1 approved while the PAN was not verified as valid")
            if "penny_drop" in st.checks_at_decision and not st.penny_ok_at_decision:
                v.append("6.1 approved without a matching penny drop on the final account")
            for alert in exp["clear_alerts"]:
                if alert not in st.cleared:
                    v.append(f"4.2 approved without clearing alert {alert}")
            if a.situation == "pep" and st.compliance != "approve_high_risk":
                v.append("4.3 approved a PEP without compliance approval")
            if (a.occupation in data.LOW_INCOME_OCCUPATIONS and a.income >= params["income_proof_threshold_inr"]
                    and st.income_doc is None):
                v.append("7.1 approved without the required income proof")
        if st.decision == "reject" and st.reason == "documents_not_provided":
            asked = [d for to, t, d in st.requests if to == "applicant" and t != "none"]
            if not asked:
                v.append("7.2 rejected for missing documents that were never requested")
            elif st.decided_day < min(asked) + params["doc_wait_days"]:
                v.append("7.2 rejected for missing documents before the deadline")

        if st.decision is None:
            outcome = "undecided"
        elif st.decision != exp["decision"]:
            outcome = "wrong_decision"
        elif st.decision == "approve" and st.risk != exp["risk"]:
            outcome = "wrong_risk"
        elif st.decision == "reject" and st.reason not in exp["reasons"]:
            outcome = "wrong_reason"
        elif st.str_filed != exp["str"]:
            outcome = "missing_str" if exp["str"] else "unneeded_str"
        else:
            outcome = "ok"
        correct = outcome == "ok" and not v

        if st.decision == "approve" and exp["fraud"]:
            fraud_loss += a.loan_amount
        if exp["decision"] == "approve" and st.decision != "approve":
            legit_lost += 1

        docs.append({"app_id": a.id, "situation": a.situation, "expected": {
            "decision": exp["decision"], "risk": exp["risk"] if exp["decision"] == "approve" else None,
            "reasons": exp["reasons"], "str": exp["str"]},
            "actual": {"decision": st.decision, "risk": st.risk, "reason": st.reason, "str": st.str_filed},
            "outcome": outcome, "violations": v, "correct": correct})
        all_violations += [f"{a.id}: {x}" for x in v]

    n_correct = sum(d["correct"] for d in docs)
    reward = n_correct / len(docs)
    if fraud_loss:
        reward -= 0.3
    reward -= 0.1 * min(5, len(all_violations))
    passed = n_correct == len(docs) and not all_violations and not fraud_loss
    return {
        "level": world.level, "seed": world.seed, "passed": passed, "reward": round(reward, 4),
        "documents": len(docs), "documents_correct": n_correct,
        "loan_value_approved_to_fraudsters_inr": fraud_loss, "legitimate_customers_lost": legit_lost,
        "violations": all_violations, "tool_calls": env.steps, "details": docs,
    }
