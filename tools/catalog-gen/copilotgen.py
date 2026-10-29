# Writes catalog/github-mcp/copilot-api.yaml and its fixtures.
import json, os, re
D = "catalog/github-mcp/"
SRC = ["https://www.npmjs.com/package/@vscode/copilot-api/v/0.5.2"]
R = []
def rule(verb, method, path, cls, card=None, notes=None, body=None, res=None, sample=None, query=None):
    R.append(dict(verb=verb, method=method, path=path, cls=cls, card=card, notes=notes, body=body, res=res, sample=sample or {}, query=query))
INFER = ("Model inference on the user's Copilot plan: it changes nothing the user owns. Some models count "
         "against the plan's premium requests.")
rule("chat-completions", "POST", "/chat/completions", "read", notes=INFER,
     body={"model": "gpt-4.1", "messages": [{"role": "user", "content": "Explain this diff"}], "stream": True})
rule("responses", "POST", "/responses", "read", notes=INFER, body={"model": "gpt-5", "input": "Explain this diff"})
rule("messages", "POST", "/v1/messages", "read", notes=INFER,
     body={"model": "claude-sonnet-4", "max_tokens": 1024, "messages": [{"role": "user", "content": "Explain this diff"}]})
rule("embeddings", "POST", "/embeddings", "read", notes=INFER, body={"model": "text-embedding-3-small", "input": ["func main() {}"]})
rule("list-models", "GET", "/models", "read")
rule("read-model", "GET", "/models/{model}", "read", sample={"model": "gpt-4.1"})
rule("enable-model", "POST", "/models/{model}/policy", "write", card="Enable model {model} for the Copilot account",
     notes="Accepts a model's terms for the account, as the model picker does.",
     body={"state": "enabled"}, sample={"model": "claude-sonnet-4"})
rule("auto-model-session", "POST", "/models/session", "read", notes="Picks a model for the session (auto mode).", body={})
rule("auto-model-intent", "POST", "/models/session/intent", "read", notes="Picks a model for a prompt (auto mode).", body={"prompt": "fix the test"})
rule("list-agents", "GET", "/agents", "read", notes="The Copilot Extensions the user has installed.")
rule("agent-chat", "POST", "/agents/{agent}", "irreversible", card="Send a chat request to Copilot agent {agent}",
     notes="A Copilot Extension is another agent, run by a third party with access the user granted it; a free-form "
           "request to it is irreversible, as other tools that hand instructions to an agent are.",
     body={"messages": [{"role": "user", "content": "deploy the fix"}]}, sample={"agent": "github-code-review"}, query="chat")
rule("list-skills", "GET", "/skills", "read")
rule("search-skill", "POST", "/search/{skill}", "read", notes="A search skill (web or docs search) answers a query.",
     body={"query": "go 1.26 release notes"}, sample={"skill": "bing"})
rule("list-sessions", "GET", "/agents/sessions", "read", notes="Copilot coding agent sessions.", query="page_size=20&page_number=1")
rule("read-session", "GET", "/agents/sessions/{session}", "read", sample={"session": "1f3c9a2e"})
rule("session-logs", "GET", "/agents/sessions/{session}/logs", "read", sample={"session": "1f3c9a2e"})
rule("pull-sessions", "GET", "/agents/sessions/resource/pull/{pull}", "read", sample={"pull": "PR_kwDOAbc123"})
rule("start-coding-agent", "POST", "/agents/swe/{version}/jobs/{owner}/{repo}", "irreversible",
     card="Start the Copilot coding agent on {owner}/{repo}", res=("repo", "repo"),
     notes="Hands a free-form task to the Copilot coding agent, which pushes branches and opens a pull request in "
           "the repository: irreversible, as other tools that hand instructions to an agent are.",
     body={"problem_statement": "Fix the flaky checkout test", "event_type": "vscode"},
     sample={"version": "v1", "owner": "acme", "repo": "shop"})
rule("read-coding-agent-job", "GET", "/agents/swe/{version}/jobs/{owner}/{repo}/{job}", "read",
     sample={"version": "v1", "owner": "acme", "repo": "shop", "job": "job_8d1e"})
rule("coding-agent-job-for-session", "GET", "/agents/swe/{version}/jobs/{owner}/{repo}/session/{session}", "read",
     sample={"version": "v1", "owner": "acme", "repo": "shop", "session": "1f3c9a2e"})
rule("coding-agent-enabled", "GET", "/agents/swe/{version}/jobs/{owner}/{repo}/enabled", "read",
     sample={"version": "v1", "owner": "acme", "repo": "shop"})
rule("coding-agent-models", "GET", "/agents/swe/models", "read")
rule("list-custom-agents", "GET", "/agents/swe/custom-agents/{owner}/{repo}", "read", sample={"owner": "acme", "repo": "shop"})
rule("read-custom-agent", "GET", "/agents/swe/custom-agents/{owner}/{repo}/{agent}", "read",
     sample={"owner": "acme", "repo": "shop", "agent": "release-notes"})

for f in os.listdir(D + "fixtures"):
    if f.startswith("copilot-api-"):
        os.remove(D + "fixtures/" + f)
L = ["# Copilot API on api.githubcopilot.com, which also serves GitHub's MCP server",
     "# (mcp.paths keeps MCP to /mcp). Paths from @vscode/copilot-api 0.5.2, the",
     "# published client VS Code's Copilot Chat calls it with; Copilot tokens whose",
     "# endpoints name another API host (api.individual.githubcopilot.com and kin)",
     "# send the same requests there, which no provider claims.",
     "operations:"]
for r in R:
    L.append(f"  - id: github-mcp.copilot-api.{r['verb']}")
    L.append(f"    match: {{ rest: {{ method: {r['method']}, path: \"{r['path']}\" }} }}")
    L.append(f"    class: {r['cls']}")
    if r["res"]:
        L.append(f"    resource: {{ arg: {r['res'][0]}, kind: {r['res'][1]} }}")
    if r["card"]:
        L.append(f"    card: {json.dumps(r['card'])}")
    L += ["    status: verified", "    verified: 2026-10-22", "    sources:"] + [f"      - {s}" for s in SRC]
    if r["notes"]:
        L.append("    notes: >-")
        line = "      "
        for w in r["notes"].split():
            if len(line) + len(w) + 1 > 100 and line.strip():
                L.append(line); line = "      "
            line += ("" if line.strip() == "" else " ") + w
        L.append(line)
    path = re.sub(r"\{([^}]+)\}", lambda m: r["sample"][m.group(1)], r["path"]) + ("?" + r["query"] if r["query"] else "")
    name = f"copilot-api-{r['verb']}.http"
    desc = re.sub(r"\{([^}]+)\}", lambda m: r["sample"].get(m.group(1), m.group(0)), r["card"] or (r["method"] + " " + r["path"]))
    lines = [f"# description: {desc}", f"{r['method']} {path} HTTP/1.1", "Host: api.githubcopilot.com",
             "Authorization: Bearer opf_github-mcp_EXAMPLE", "Copilot-Integration-Id: vscode-chat"]
    if r["body"] is not None:
        lines += ["Content-Type: application/json", "", json.dumps(r["body"])]
    else:
        lines.append("")
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")
    L += ["    tests:", f"      - fixture: fixtures/{name}", f"        expect: {r['cls']}"]
    if r["res"]:
        L.append(f"        resource: \"{r['sample'][r['res'][0]]}\"")
    L.append("")
open(D + "copilot-api.yaml", "w").write("\n".join(L))
print(len(R), "rules")
