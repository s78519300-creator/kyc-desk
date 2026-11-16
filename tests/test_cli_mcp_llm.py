import io
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from kyc_desk.cli import main, parse_seeds
from kyc_desk.llm import run_llm
from kyc_desk.mcp_server import Server, serve


def test_parse_seeds():
    assert parse_seeds("0-3,7") == [0, 1, 2, 3, 7]


def test_cli_run_bench_export(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert main(["run", "--level", "easy", "--seed", "2", "--json", str(out)]) == 0
    assert "PASSED" in capsys.readouterr().out
    assert json.loads(out.read_text())["passed"] is True
    assert main(["bench", "--seeds", "0-1", "--level", "easy"]) == 0
    assert "strict_checklist" in capsys.readouterr().out
    tasks = tmp_path / "t.jsonl"
    assert main(["export", "--level", "all", "--seeds", "0-1", "-o", str(tasks)]) == 0
    rows = [json.loads(l) for l in tasks.read_text().splitlines()]
    assert len(rows) == 6 and rows[0]["launch"][:3] == ["python", "-m", "kyc_desk"]


def test_cli_audit(capsys):
    assert main(["audit", "--seeds", "0-1"]) == 0
    assert "AUDIT PASSED" in capsys.readouterr().out


def test_mcp_session(tmp_path):
    result = tmp_path / "result.json"
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_policy", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "nope"},
    ] + [{"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call", "params": {"name": "end_day", "arguments": {}}}
         for i in range(5)]
    out = io.StringIO()
    serve("easy", 0, str(result), io.StringIO("\n".join(json.dumps(l) for l in lines) + "\nnot json\n"), out)
    replies = [json.loads(l) for l in out.getvalue().splitlines()]
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"]["serverInfo"]["name"] == "kyc-desk"
    assert len(by_id[2]["result"]["tools"]) == 17
    assert "KYC POLICY" in json.loads(by_id[3]["result"]["content"][0]["text"])["policy"]
    assert by_id[4]["error"]["code"] == -32601
    assert by_id[None]["error"]["code"] == -32700
    assert json.loads(result.read_text())["documents"] == 8


class _Mock(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert body["tools"] and body["messages"][0]["role"] == "system"
        _Mock.calls += 1
        n = _Mock.calls
        if n == 1:
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "get_policy", "arguments": "{}"}},
                {"id": "c2", "type": "function", "function": {"name": "approve", "arguments": "{not json"}}]}
        elif n == 2:
            msg = {"role": "assistant", "content": "I think I am done."}  # no tool call: gets nudged
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"c{n}", "type": "function", "function": {"name": "end_day", "arguments": "{}"}}]}
        data = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_llm_runner_against_mock_server():
    srv = HTTPServer(("127.0.0.1", 0), _Mock)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        trace = []
        res = run_llm("mock-model", "easy", 0, f"http://127.0.0.1:{srv.server_port}/v1", "k", log=trace)
    finally:
        srv.shutdown()
    assert res["model"] == "mock-model" and res["documents"] == 8 and not res["passed"]
    assert trace[0]["tool"] == "get_policy" and trace[1]["obs"]["ok"] is False
    assert sum(1 for x in trace if x["tool"] == "end_day") == 5
