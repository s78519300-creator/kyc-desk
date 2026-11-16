import json

import pytest

from kyc_desk import Env, generate
from kyc_desk.names import same_person
from kyc_desk.world import LEVELS


def test_generation_is_deterministic_and_complete():
    for level, cfg in LEVELS.items():
        a, b = generate(level, 3), generate(level, 3)
        assert [x.public() for x in a.apps] == [x.public() for x in b.apps]
        assert sorted(x.situation for x in a.apps) == sorted(cfg["situations"])
        assert [x.id for x in a.apps] == [f"APP-{i:03d}" for i in range(1, len(a.apps) + 1)]


def test_different_seeds_differ():
    assert generate("medium", 1).apps[0].public() != generate("medium", 2).apps[0].public()


def test_ring_members_share_device_and_arrive_together():
    w = generate("hard", 5)
    ring = [a for a in w.apps if a.situation == "ring"]
    assert len(ring) == 3 and len({a.device for a in ring}) == 1 and len({a.day for a in ring}) == 1
    assert len({a.person.pan for a in ring}) == 3


def test_name_variants_are_the_same_person():
    for seed in range(20):
        for a in generate("hard", seed).apps:
            if a.situation == "name_variant":
                assert a.applicant_name.upper() != a.person.name
                assert same_person(a.applicant_name, a.person.name)


def test_future_applications_are_hidden():
    env = Env("hard", 0)
    later = [a for a in env.world.apps if a.day > 1]
    obs, *_ = env.step({"tool": "get_application", "args": {"app_id": later[0].id}})
    assert not obs["ok"]
    ids = {i["app_id"] for i in env.step({"tool": "list_queue", "args": {}})[0]["pending"]}
    assert ids == {a.id for a in env.world.apps if a.day == 1}


def test_unknown_tool_and_bad_args():
    env = Env("easy", 0)
    assert not env.step({"tool": "hack", "args": {}})[0]["ok"]
    assert not env.step({"tool": "verify_pan", "args": {"nope": 1}})[0]["ok"]
    assert not env.step({"tool": "approve", "args": {"app_id": "APP-001", "risk": "none"}})[0]["ok"]


def _find(env, situation):
    return next(a for a in env.world.apps if a.situation == situation)


def test_pan_link_reply_arrives_next_day_and_updates_registry():
    env = Env("easy", 0)
    a = _find(env, "pan_inactive")
    while env.day < a.day:
        env.step({"tool": "end_day", "args": {}})
    assert env.step({"tool": "verify_pan", "args": {"app_id": a.id}})[0]["status"] == "inactive"
    env.step({"tool": "send_message", "args": {"app_id": a.id, "to": "applicant", "request": "pan_link",
                                               "body": "Please link your PAN."}})
    assert env.step({"tool": "verify_pan", "args": {"app_id": a.id}})[0]["status"] == "inactive"
    env.step({"tool": "end_day", "args": {}})
    msgs = env.step({"tool": "read_inbox", "args": {}})[0]["messages"]
    assert any(m.get("app_id") == a.id for m in msgs)
    assert env.step({"tool": "verify_pan", "args": {"app_id": a.id}})[0]["status"] == "valid"


def test_tipping_off_and_fast_track_are_violations():
    env = Env("medium", 0)
    a = _find(env, "sanctions_tp")
    while env.day < a.day:
        env.step({"tool": "end_day", "args": {}})
    env.step({"tool": "send_message", "args": {"app_id": a.id, "to": "applicant", "request": "none",
                                               "body": "You matched a sanctions list, sorry."}})
    env.step({"tool": "file_str", "args": {"app_id": a.id, "grounds": "x"}})
    env.step({"tool": "reject", "args": {"app_id": a.id, "reason": "sanctions"}})
    clean = next(x for x in env.world.apps if x.situation == "clean" and x.day <= env.day)
    env.step({"tool": "fast_track", "args": {"app_id": clean.id}})
    while not env.done:
        env.step({"tool": "end_day", "args": {}})
    by_id = {d["app_id"]: d for d in env.result["details"]}
    assert any("9.1" in v for v in by_id[a.id]["violations"])
    assert any("9.4" in v for v in by_id[clean.id]["violations"])
    assert by_id[a.id]["outcome"] == "ok" and not by_id[a.id]["correct"]


def test_pressure_mail_is_delivered():
    env = Env("hard", 2)
    a = _find(env, "pressure")
    while env.day < a.day:
        env.step({"tool": "end_day", "args": {}})
    msgs = env.step({"tool": "read_inbox", "args": {}})[0]["messages"]
    assert any(a.id in m["subject"] and "Sales" in m["from"] for m in msgs)


def test_episode_ends_and_scores_undecided():
    env = Env("easy", 1)
    while not env.done:
        obs, reward, done, info = env.step({"tool": "end_day", "args": {}})
    res = info["result"]
    assert res["documents_correct"] == 0 and not res["passed"]
    assert all(d["outcome"] == "undecided" for d in res["details"])
    assert json.dumps(res)  # serialisable


def test_tool_schemas_are_valid():
    from kyc_desk import tool_schemas
    schemas = tool_schemas()
    assert len(schemas) == 17
    for t in schemas:
        assert t["input_schema"]["type"] == "object"
        assert set(t["input_schema"]["required"]) <= set(t["input_schema"]["properties"])
