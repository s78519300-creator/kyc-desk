import pytest

from kyc_desk import Env, ReferenceAgent, run_policy
from kyc_desk.audit import RULE_SITUATION, audit
from kyc_desk.world import LEVELS, generate


@pytest.mark.parametrize("level", list(LEVELS))
def test_reference_passes(level):
    for seed in range(8):
        res = run_policy("reference", level, seed)
        assert res["passed"], [d for d in res["details"] if not d["correct"]]
        assert res["reward"] == 1.0


@pytest.mark.parametrize("name", ["approve_all", "reject_all", "strict_checklist"])
def test_shortcuts_fail(name):
    for level in LEVELS:
        for seed in range(4):
            assert not run_policy(name, level, seed)["passed"]


def test_approve_all_loses_money_and_reject_all_loses_customers():
    a = run_policy("approve_all", "hard", 0)
    r = run_policy("reject_all", "hard", 0)
    assert a["loan_value_approved_to_fraudsters_inr"] > 0
    assert r["legitimate_customers_lost"] > 0 and r["loan_value_approved_to_fraudsters_inr"] == 0


@pytest.mark.parametrize("rule", sorted(RULE_SITUATION))
def test_every_rule_matters(rule):
    seeds = [s for s in range(10) if any(a.situation == RULE_SITUATION[rule] for a in generate("hard", s).apps)]
    assert seeds
    for s in seeds[:3]:
        assert not ReferenceAgent({rule}).run(Env("hard", s))["passed"]


def test_audit_small():
    res = audit(range(3))
    assert res["ok"], res
