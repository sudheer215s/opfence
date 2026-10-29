# Generates catalog/terraform-mcp rules and fixtures from a reviewed table.
# Run from the repo root: python3 -I tfgen.py <terraform-mcp source dir>
import json, os, sys

SRC_DIR = sys.argv[1]
SRC = "https://github.com/hashicorp/terraform-mcp-server/blob/main/pkg/tools/"
ORG = "acme"
D = "catalog/terraform-mcp/"
# Anything ParseBool would not read as false: credential or auto-apply on.
NOT_FALSE = "'^(?is:[^0f].*|0.+|f[^a].*|fa|fa[^l].*|fal|fal[^s].*|fals|fals[^e].*|false.+)$'"

T = {}


def add(tool, group, verb, f, cls, args, card=None, when=None, res=None, notes=None, tests=None):
    assert tool not in T, tool
    T[tool] = dict(group=group, verb=verb, file=f, cls=cls, args=args, card=card,
                   when=when or [], res=res, notes=notes, tests=tests)


reg = lambda n: "registry/" + n + ".go"
tfe = lambda n: "tfe/" + n + ".go"

# Public Terraform Registry: reads.
for tool, args in [
    ("get_latest_module_version", {"module_publisher": "terraform-aws-modules", "module_name": "vpc", "module_provider": "aws"}),
    ("get_latest_provider_version", {"namespace": "hashicorp", "name": "aws"}),
    ("get_module_details", {"module_id": "terraform-aws-modules/vpc/aws/5.8.1"}),
    ("get_policy_details", {"terraform_policy_id": "policies/hashicorp/CIS-Policy-Set-for-AWS-Terraform/1.0.1"}),
    ("get_provider_capabilities", {"namespace": "hashicorp", "name": "aws"}),
    ("get_provider_details", {"provider_doc_id": "8894603"}),
    ("search_modules", {"module_query": "vpc"}),
    ("search_policies", {"policy_query": "cis"}),
    ("search_provider_docs", {"provider_name": "aws", "provider_namespace": "hashicorp", "service_slug": "s3_bucket", "provider_document_type": "resources"}),
]:
    add(tool, "registry", tool.replace("_", "-"), reg(tool), "read", args)

# HCP Terraform and Terraform Enterprise: reads.
files = {"list_variable_sets": "variable_sets", "list_workspace_policy_sets": "policy_sets",
         "list_workspace_variables": "workspace_variables", "read_workspace_tags": "workspace_tags"}
notes = {
    "list_workspace_variables": "Returns variable keys, and values only for variables not marked sensitive: HCP Terraform never returns a sensitive value.",
    "list_state_versions": "Returns each state version's ID, serial, status and commit, not the state or a link to it.",
    "get_plan_logs": "Plan logs print attribute values the way the terraform CLI does: values marked sensitive show as (sensitive value).",
    "get_apply_logs": "Apply logs print attribute values the way the terraform CLI does: values marked sensitive show as (sensitive value).",
}
for tool, args in [
    ("get_apply_details", {"apply_id": "apply-abc123"}),
    ("get_apply_logs", {"apply_id": "apply-abc123"}),
    ("get_plan_details", {"plan_id": "plan-abc123"}),
    ("get_plan_logs", {"plan_id": "plan-abc123"}),
    ("get_private_module_details", {"terraform_org_name": ORG, "private_module_id": "acme/vpc/aws"}),
    ("get_private_provider_details", {"terraform_org_name": ORG, "private_provider_name": "internal"}),
    ("get_project", {"project_id": "prj-abc123"}),
    ("get_run_comments", {"run_id": "run-abc123"}),
    ("get_run_details", {"run_id": "run-abc123"}),
    ("get_stack_details", {"stack_id": "st-abc123"}),
    ("get_team", {"team_id": "team-abc123"}),
    ("get_token_permissions", {}),
    ("get_workspace_details", {"terraform_org_name": ORG, "workspace_name": "prod-network"}),
    ("list_runs", {"terraform_org_name": ORG, "workspace_name": "prod-network"}),
    ("list_stacks", {"terraform_org_name": ORG}),
    ("list_state_versions", {"terraform_org_name": ORG, "workspace_name": "prod-network"}),
    ("list_teams", {"terraform_org_name": ORG}),
    ("list_terraform_orgs", {}),
    ("list_terraform_projects", {"terraform_org_name": ORG}),
    ("list_variable_sets", {"terraform_org_name": ORG}),
    ("list_workspace_policy_sets", {"terraform_org_name": ORG, "workspace_id": "ws-abc123"}),
    ("list_workspace_variables", {"terraform_org_name": ORG, "workspace_name": "prod-network"}),
    ("list_workspaces", {"terraform_org_name": ORG}),
    ("read_workspace_tags", {"terraform_org_name": ORG, "workspace_name": "prod-network"}),
    ("search_private_modules", {"terraform_org_name": ORG, "search_query": "vpc"}),
    ("search_private_providers", {"terraform_org_name": ORG, "search_query": "internal"}),
    ("whoami", {}),
]:
    if "variable" in tool:
        grp = "variable"
    elif "workspace" in tool:
        grp = "workspace"
    elif "state" in tool:
        grp = "state"
    elif any(w in tool for w in ("run", "plan", "apply")):
        grp = "run"
    elif any(w in tool for w in ("private_", "stack")):
        grp = "registry-private"
    else:
        grp = "org"
    if grp == "registry-private":
        grp = "private-registry"
    add(tool, grp, tool.replace("_", "-"), tfe(files.get(tool, tool)), "read", args, notes=notes.get(tool))

# Reads that return secrets.
add("get_state_version", "state", "get-state-version", tfe("get_state_version"), "credential", {"workspace_id": "ws-abc123"},
    tests=[("call", {"workspace_id": "ws-abc123"}, "credential"), ("by-id", {"state_version_id": "sv-abc123"}, "credential")],
    card="Read state version {state_version_id} (workspace {workspace_id}), with a link to download the whole state",
    notes="Returns hosted_state_download_url, a pre-signed link to the whole state file, which holds every resource attribute "
          "in plain text, database passwords and private keys included. Reading secrets is credential.")
add("get_plan_json_output", "run", "get-plan-json-output", tfe("get_plan_json_output"), "credential", {"plan_id": "plan-abc123"},
    card="Read the JSON plan of {plan_id}, with attribute values",
    notes="The JSON plan holds every attribute's before and after values in plain text, those Terraform marks sensitive "
          "included (it only flags them), so it can return database passwords and keys.")
add("get_sentinel_mock", "run", "get-sentinel-mock", tfe("get_sentinel_mock"), "credential", {"plan_id": "plan-abc123"},
    card="Export Sentinel mock data of {plan_id}, with attribute values",
    notes="Sentinel mocks carry the plan's configuration, state and attribute values, as the JSON plan does.")

# Projects.
add("create_project", "project", "create", tfe("create_project"), "write", {"terraform_org_name": ORG, "project_name": "payments"},
    card="Create project {project_name} in {terraform_org_name}")
add("delete_project", "project", "delete", tfe("delete_project"), "delete", {"project_id": "prj-abc123"},
    card="Delete project {project_id}", res=("project_id", "project"),
    notes="HCP Terraform deletes only a project that holds no workspaces or stacks, so nothing it managed goes with it.")

# Workspaces.
AUTO_APPLY = "Turning auto-apply on applies every later run's plan without anyone confirming it, destroys included: " \
             "turning off a safety net is as dangerous as what it protects."
add("create_workspace", "workspace", "create", tfe("create_workspace"), "write",
    {"terraform_org_name": ORG, "workspace_name": "prod-network"},
    card="Create workspace {workspace_name} in {terraform_org_name}",
    when=[("{ arg: auto_apply, equals: \"true\" }", "irreversible")], notes=AUTO_APPLY,
    tests=[("call", {"terraform_org_name": ORG, "workspace_name": "prod-network", "auto_apply": "false"}, "write"),
           ("auto-apply", {"terraform_org_name": ORG, "workspace_name": "prod-network", "auto_apply": "true"}, "irreversible"),
           ("auto-apply-bool", {"terraform_org_name": ORG, "workspace_name": "prod-network", "auto_apply": True}, "irreversible")])
add("create_no_code_workspace", "workspace", "create-no-code", tfe("create_no_code_workspace"), "write",
    {"no_code_module_id": "nocode-abc123", "workspace_name": "dev-bucket", "project_id": "prj-abc123"},
    card="Create no-code workspace {workspace_name} from module {no_code_module_id}",
    when=[("{ arg: auto_apply, matches: " + NOT_FALSE + " }", "irreversible")],
    notes="Creating the workspace queues a run of the module; with auto_apply it is applied at once and every later run too. " + AUTO_APPLY,
    tests=[("call", {"no_code_module_id": "nocode-abc123", "workspace_name": "dev-bucket", "project_id": "prj-abc123"}, "write"),
           ("auto-apply", {"no_code_module_id": "nocode-abc123", "workspace_name": "dev-bucket", "project_id": "prj-abc123", "auto_apply": True}, "irreversible"),
           ("auto-apply-string", {"no_code_module_id": "nocode-abc123", "workspace_name": "dev-bucket", "project_id": "prj-abc123", "auto_apply": "1"}, "irreversible"),
           ("no-auto-apply", {"no_code_module_id": "nocode-abc123", "workspace_name": "dev-bucket", "project_id": "prj-abc123", "auto_apply": False}, "write")])
add("update_workspace", "workspace", "update", tfe("update_workspace"), "write",
    {"terraform_org_name": ORG, "workspace_name": "prod-network", "terraform_version": "1.9.8"},
    card="Update workspace {workspace_name} in {terraform_org_name}", res=("workspace_name", "workspace"),
    when=[("{ arg: auto_apply, equals: \"true\" }", "irreversible")], notes=AUTO_APPLY,
    tests=[("call", {"terraform_org_name": ORG, "workspace_name": "prod-network", "terraform_version": "1.9.8"}, "write"),
           ("auto-apply", {"terraform_org_name": ORG, "workspace_name": "prod-network", "auto_apply": "TRUE"}, "irreversible")])
add("create_workspace_tags", "workspace", "create-tags", tfe("workspace_tags"), "write",
    {"terraform_org_name": ORG, "workspace_name": "prod-network", "tags": "env:prod"},
    card="Tag workspace {workspace_name} with {tags}")
add("force_unlock_workspace", "workspace", "force-unlock", tfe("force_unlock_workspace"), "write", {"workspace_id": "ws-abc123"},
    card="Force-unlock workspace {workspace_id}", res=("workspace_id", "workspace"),
    notes="Releases a lock another user or run holds; the state is unchanged.")
add("delete_workspace_safely", "workspace", "delete", tfe("delete_workspace_safely"), "irreversible", {"workspace_id": "ws-abc123"},
    card="Delete workspace {workspace_id}", res=("workspace_id", "workspace"),
    notes="Safe delete refuses a workspace that still manages resources, but deletes its state history, runs and variables, "
          "sensitive ones included, which cannot be put back.")

# Runs.
add("create_run", "run", "create", tfe("create_run"), "irreversible",
    {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "plan_only"},
    card="Start a run (type {run_type}) in workspace {workspace_name} of {terraform_org_name}", res=("workspace_name", "workspace"),
    when=[("{ arg: run_type, absent: true }", "write"),
          ("{ arg: run_type, matches: '^(?:plan_and_apply|refresh_state|plan_only)$' }", "write")],
    notes="Two tools share the name: without ENABLE_TF_OPERATIONS=true the server offers run types plan_and_apply, "
          "refresh_state, plan_only and allow_empty_apply, and with it also auto_approve and is_destroy. The server "
          "compares run_type exactly. plan_and_apply (the default) sets auto-apply off, so its plan waits for "
          "confirmation (action_run apply); plan_only and refresh_state change no infrastructure. Every other value "
          "leaves auto-apply to the workspace's setting, which the call does not show: auto_approve applies without "
          "confirmation, is_destroy destroys every resource, allow_empty_apply and any value the server does not list "
          "(PLAN_AND_APPLY, an empty string) plan and apply as the workspace does, so they are irreversible.",
    tests=[("call", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "plan_only"}, "write"),
           ("refresh", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "refresh_state"}, "write"),
           ("plan-and-apply", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "plan_and_apply"}, "write"),
           ("default", {"terraform_org_name": ORG, "workspace_name": "prod-network", "message": "nightly"}, "write"),
           ("auto-approve", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "auto_approve"}, "irreversible"),
           ("destroy", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "is_destroy", "message": "cleanup"}, "irreversible"),
           ("empty-apply", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "allow_empty_apply"}, "irreversible"),
           ("uppercase", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": "PLAN_AND_APPLY"}, "irreversible"),
           ("empty", {"terraform_org_name": ORG, "workspace_name": "prod-network", "run_type": ""}, "irreversible")])
add("action_run", "run", "action", tfe("action_run"), "write", {"run_id": "run-abc123", "run_action": "discard"},
    card="{run_action} run {run_id}", res=("run_id", "run"),
    when=[("{ arg: run_action, equals: apply }", "irreversible")],
    notes="apply carries out the run's plan, destroys included; discard and cancel stop it.",
    tests=[("call", {"run_id": "run-abc123", "run_action": "discard"}, "write"),
           ("cancel", {"run_id": "run-abc123", "run_action": "cancel"}, "write"),
           ("apply", {"run_id": "run-abc123", "run_action": "apply", "comment": "lgtm"}, "irreversible")])

# Variables.
for tool, f, args, card in [
    ("create_workspace_variable", "workspace_variables",
     {"terraform_org_name": ORG, "workspace_name": "prod-network", "key": "region", "value": "eu-west-1", "category": "terraform"},
     "Set variable {key} on workspace {workspace_name}"),
    ("update_workspace_variable", "workspace_variables",
     {"terraform_org_name": ORG, "workspace_name": "prod-network", "variable_id": "var-abc123", "value": "eu-west-2"},
     "Change variable {variable_id} on workspace {workspace_name}"),
    ("create_variable_in_variable_set", "variable_sets",
     {"variable_set_id": "varset-abc123", "key": "region", "value": "eu-west-1"},
     "Set variable {key} in variable set {variable_set_id}"),
]:
    sens = dict(args)
    sens["value"] = "hunter2"
    sens["sensitive"] = True
    if "key" in sens:
        sens["key"] = "db_password"
    sens_str = dict(sens)
    sens_str["sensitive"] = "true"
    add(tool, "variable", tool.replace("_", "-"), tfe(f), "write", args, card=card,
        when=[("{ arg: sensitive, matches: " + NOT_FALSE + " }", "credential")],
        notes="A variable marked sensitive is a secret HCP Terraform never shows again: setting it is setting a "
              "secret-store value, credential. A plain variable is a write.",
        tests=[("call", args, "write"), ("sensitive", sens, "credential"), ("sensitive-string", sens_str, "credential")])
add("delete_variable_in_variable_set", "variable", "delete-in-set", tfe("variable_sets"), "irreversible",
    {"variable_set_id": "varset-abc123", "variable_id": "var-abc123"},
    card="Delete variable {variable_id} from variable set {variable_set_id}",
    notes="Deleting any variable is irreversible: a sensitive value cannot be read back to restore it.")
add("create_variable_set", "variable", "create-set", tfe("variable_sets"), "write", {"terraform_org_name": ORG, "name": "aws-dev"},
    card="Create variable set {name} in {terraform_org_name}")
add("attach_variable_set_to_workspaces", "variable", "attach-set", tfe("variable_sets"), "write",
    {"variable_set_id": "varset-abc123", "workspace_ids": "ws-abc123,ws-def456"},
    card="Attach variable set {variable_set_id} to workspaces {workspace_ids}",
    notes="The workspaces' runs get the set's variables, credentials included, from the next run on.")
add("detach_variable_set_from_workspaces", "variable", "detach-set", tfe("variable_sets"), "write",
    {"variable_set_id": "varset-abc123", "workspace_ids": "ws-abc123"},
    card="Detach variable set {variable_set_id} from workspaces {workspace_ids}")

# Policies.
add("attach_policy_set_to_workspaces", "policy", "attach-set", tfe("policy_sets"), "write",
    {"policy_set_id": "polset-abc123", "workspace_ids": "ws-abc123"},
    card="Attach policy set {policy_set_id} to workspaces {workspace_ids}")

# Teams: who can reach what.
add("create_team", "team", "create", tfe("create_team"), "access", {"terraform_org_name": ORG, "team_name": "platform"},
    card="Create team {team_name} in {terraform_org_name}",
    notes="A team can be given organization permissions when it is created.")
add("delete_team", "team", "delete", tfe("delete_team"), "access", {"team_id": "team-abc123"},
    card="Delete team {team_id}", res=("team_id", "team"),
    notes="Removes every access the team's members had through it.")
add("add_team_member", "team", "add-member", tfe("add_team_member"), "access", {"team_id": "team-abc123", "username": "mallory"},
    card="Add {username} to team {team_id}")
add("grant_team_access", "team", "grant-access", tfe("grant_team_access"), "access",
    {"team_id": "team-abc123", "access_level": "admin", "workspace_id": "ws-abc123"},
    card="Grant team {team_id} {access_level} access")

assert len(T) == 61, len(T)

BAD = set()
# Every tool and argument must appear in the server's source.
base = os.path.join(SRC_DIR, "pkg/tools/")
for tool, v in T.items():
    s = open(base + v["file"]).read()
    assert '"' + tool + '"' in s, (tool, v["file"])
    for _, args, _ in (v["tests"] or [("call", v["args"], None)]):
        for a in args:
            if ("(\"" + a + "\"") not in s: print("MISSING", tool, a, v["file"]); BAD.add(v["file"])

assert not BAD, BAD
os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.endswith(".yaml") and f != "provider.yaml":
        os.remove(D + f)

TITLES = {"registry": "public Terraform Registry", "private-registry": "private registry and stacks", "org": "organizations, teams and tokens",
          "workspace": "workspaces", "run": "runs, plans and applies", "state": "state versions", "variable": "variables and variable sets",
          "project": "projects", "policy": "policy sets", "team": "teams"}


def wrap(text, indent):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > 100 and line.strip():
            out.append(line)
            line = indent
        line += ("" if line == indent else " ") + w
    out.append(line)
    return out


groups = {}
for tool, v in sorted(T.items()):
    groups.setdefault(v["group"], []).append(tool)
for g, tools in sorted(groups.items()):
    lines = ["# Terraform MCP server (hashicorp/terraform-mcp-server): " + TITLES[g] + ".", "operations:"]
    for tool in tools:
        v = T[tool]
        lines.append(f"  - id: terraform-mcp.{g}.{v['verb']}")
        lines.append(f"    match: {{ mcp: {{ tool: {tool} }} }}")
        lines.append(f"    class: {v['cls']}")
        if v["when"]:
            lines.append("    when:")
            for cond, cls in v["when"]:
                lines.append(f"      - if: {cond}")
                lines.append(f"        class: {cls}")
        if v["res"]:
            lines.append(f"    resource: {{ arg: {v['res'][0]}, kind: {v['res'][1]} }}")
        if v["card"]:
            lines.append(f"    card: {json.dumps(v['card'])}")
        lines.append("    status: verified")
        lines.append("    verified: 2026-10-22")
        lines.append("    sources:")
        lines.append(f"      - {SRC}{v['file']}")
        if v["notes"]:
            lines.append("    notes: >-")
            lines += wrap(v["notes"], "      ")
        lines.append("    tests:")
        for suffix, args, expect in (v["tests"] or [("call", v["args"], v["cls"])]):
            fname = f"{g}-{v['verb']}" + ("" if suffix == "call" else "-" + suffix) + ".json"
            desc = tool.replace("_", " ") + ("" if suffix == "call" else " (" + suffix.replace("-", " ") + ")")
            with open(D + "fixtures/" + fname, "w") as fh:
                json.dump({"description": desc, "tool": tool, "arguments": args}, fh, indent=2)
                fh.write("\n")
            lines.append(f"      - fixture: fixtures/{fname}")
            lines.append(f"        expect: {expect}")
            if v["res"] and v["res"][0] in args:
                lines.append(f"        resource: \"{args[v['res'][0]]}\"")
        lines.append("")
    with open(D + g + ".yaml", "w") as fh:
        fh.write("\n".join(lines))
print(len(T), "tools,", sum(len(v["tests"] or [1]) for v in T.values()), "tests in", sorted(groups))
