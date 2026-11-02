"""Run trap and golden cases through the MCP server (a real stdio subprocess).

python3 mcp/eval_via_mcp.py [--provider claude|local|mock] [--golden mcp/sample_golden.json ...] [--compare-direct]
Uses eval.run_eval.check unchanged, so a case passes here exactly when it would pass in the engine's own eval.
Exit 1 on any failing case (cases marked needs_model are reported but not counted under the mock provider), or,
with --compare-direct, on any difference from an in-process engine call.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "source"))

from eval.run_eval import check  # noqa: E402


class Client:
    def __init__(self, env):
        self.p = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, env=env, text=True)
        self.n = 0
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                "clientInfo": {"name": "eval_via_mcp", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")

    def rpc(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        reply = json.loads(self.p.stdout.readline())
        if "error" in reply:
            raise RuntimeError(reply["error"])
        return reply["result"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=os.environ.get("MODEL_PROVIDER", "claude"))
    ap.add_argument("--golden", nargs="*", default=[os.path.join(HERE, "sample_golden.json")])
    ap.add_argument("--compare-direct", action="store_true",
                    help="also call the engine in-process and require an identical status, answer and citations")
    args = ap.parse_args()
    env = dict(os.environ, MODEL_PROVIDER=args.provider,
               MODEL_CALL_LOG=os.environ.get("MODEL_CALL_LOG", os.path.join(tempfile.mkdtemp(), "model_calls.jsonl")))
    os.environ["MODEL_PROVIDER"] = args.provider
    from rfp import provider
    provider.CALL_LOG = env["MODEL_CALL_LOG"]  # read at import; keep this run's calls out of flightlog/
    direct = None
    if args.compare_direct:
        sys.path.insert(0, HERE)
        import server as direct  # same loading code; answer.answer called in this process, no MCP in between
    c = Client(env)
    mismatches = []
    assert {t["name"] for t in c.rpc("tools/list", {})["tools"]} == {"answer_question", "list_questions"}
    failed, total, passed = [], 0, 0
    for g in args.golden:
        for case in json.load(open(g)):
            res = c.rpc("tools/call", {"name": "answer_question", "arguments": {"question": case["q"]}})
            fails = ["tool error: " + res["content"][0]["text"]] if res["isError"] else check(case, res["structuredContent"])
            if direct and not res["isError"]:
                d = direct.answer_question(case["q"])
                if [d[k] for k in ("status", "answer", "citations")] != [res["structuredContent"][k] for k in ("status", "answer", "citations")]:
                    mismatches.append(case["id"])
            skip = case.get("needs_model") and args.provider == "mock"
            if not skip:
                total, passed = total + 1, passed + (not fails)
                if fails:
                    failed.append(case["id"])
            print("%-4s %s %s" % (case["id"], "SKIP (needs a real model)" if skip else "PASS" if not fails else "FAIL",
                                  "" if skip else "; ".join(fails)))
    print("\n%d/%d passed through MCP (%s); failed: %s" % (passed, total, args.provider, failed or "none"))
    if direct:
        print("wrapper vs direct engine call: %s" % ("identical on every case run" if not mismatches else "DIFFER on %s" % mismatches))
    return 1 if failed or mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
