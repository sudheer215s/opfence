# Writes catalog/gitlab/mcp.yaml and its mcp-* fixtures: a rule for every tool
# GitLab's MCP server (POST /api/v4/mcp) registers, read from GitLab's source
# at the commit given. Run from the repo root:
#   python3 -I gitlabmcp.py <gitlab commit>
#
# Tools come from Mcp::Tools::Manager (app/services/mcp/tools/manager.rb and
# its EE override): CUSTOM_TOOLS, GRAPHQL_TOOLS (and EE_GRAPHQL_TOOLS), Grape
# routes marked route_setting :mcp (lib/api, ee/lib/api), aggregated tools
# built over routes, every tool's tool_aliases, and Orbit's query_graph.
# Unlisted tools are still callable by name, so they get rules too.
import json, os, sys

COMMIT = sys.argv[1]
D = "catalog/gitlab/"
DATE = "2026-10-28"
B = f"https://gitlab.com/gitlab-org/gitlab/-/blob/{COMMIT}/"
MANAGER = B + "app/services/mcp/tools/manager.rb"
TRUE = ["true", "1", "t", "y", "yes", "on"]

def svc(path):
    return B + path

# name, class, resource arg, card, note, conditions [(class, cond, label, value)], sample args, source
P = "app/services/mcp/tools/"
E = "ee/app/services/mcp/tools/"
PROJ = {"project_id": "acme/shop"}
TOOLS = [
    # Custom tools.
    ("get_artifact_file", "read", "project_id", "Read {artifact_path} from job {job_id}'s artifacts in project {project_id}",
     "Artifacts are read as GitHub's are; CI/CD masks variables in job output, not in files a job writes.", [],
     {"project_id": "acme/shop", "job_id": 2002, "artifact_path": "coverage/report.txt"}, P + "jobs/get_artifact_file_service.rb"),
    ("get_job", "read", "id", "Show job {job_id} in project {id}", "With include: log, the job's log, in which CI/CD masks variables.", [],
     {"id": "acme/shop", "job_id": 2002, "include": ["log"]}, P + "jobs/get_job_service.rb"),
    ("get_mcp_server_version", "read", None, "Show the GitLab MCP server's version", None, [], {}, P + "get_server_version_service.rb"),
    ("get_merge_request_conflicts", "read", "project_id", "Show the merge conflicts of merge request !{merge_request_iid} in project {project_id}",
     "Unlisted, but callable by name.", [], {"project_id": "acme/shop", "merge_request_iid": 12}, P + "merge_requests/get_merge_request_conflicts_service.rb"),
    ("get_pages_content", "read", "url", "Read the GitLab Pages site at {url}", "Reads private Pages sites the user can see, as reading the repository does.", [],
     {"url": "https://acme.gitlab.io/shop/"}, P + "pages/get_pages_content_service.rb"),
    ("list_releases", "read", "project_id", "List releases of project {project_id}", None, [], PROJ, P + "releases/list_releases_service.rb"),
    ("list_tags", "read", "project_id", "List tags of project {project_id}", None, [], PROJ, P + "repositories/tags/list_tags_service.rb"),
    # GraphQL-backed tools.
    ("accept_merge_request", "write", "project_id", "Merge merge request !{merge_request_iid} of project {project_id}",
     "Merging is a write, as GitHub's merge_pull_request is; removing the source branch is delete.",
     [("delete", "should_remove_source_branch", "remove-source-branch", True)],
     {"project_id": "acme/shop", "merge_request_iid": 12, "sha": "6104942438c14ec7bd21c6cd5bd995272b3faff6"}, P + "merge_requests/accept_merge_request_service.rb"),
    ("add_branch", "write", "project_id", "Create branch {branch} from {ref} in project {project_id}", None, [],
     {"project_id": "acme/shop", "branch": "feature/login", "ref": "main"}, P + "repositories/branches/add_branch_service.rb"),
    ("add_commit", "write", "project_id", "Commit to branch {branch} of project {project_id}",
     "Committing is a write, as GitHub's push_files is; a delete action removes a file, which is delete, as GitHub's delete_file is "
     "(the file stays in the history).",
     [("delete", "actions.action", "delete-file", "delete")],
     {"project_id": "acme/shop", "branch": "main", "commit_message": "Update deploy config",
      "actions": [{"action": "update", "file_path": "config/deploy.yml", "content": "replicas: 3\n"}]}, P + "repositories/add_commit_service.rb"),
    ("get_commit", "read", "project_id", "Show commit {commit_sha} of project {project_id}", None, [],
     {"project_id": "acme/shop", "commit_sha": "6104942438c14ec7bd21c6cd5bd995272b3faff6"}, P + "commits/get_commit_service.rb"),
    ("get_merge_request", "read", "project_id", "Show merge request !{merge_request_iid} of project {project_id}", None, [],
     {"project_id": "acme/shop", "merge_request_iid": 12}, P + "merge_requests/get_merge_request_service.rb"),
    ("get_merge_request_notes", "read", "project_id", "Show the comments on merge request !{merge_request_iid} of project {project_id}", "Unlisted, but callable by name.", [],
     {"project_id": "acme/shop", "merge_request_iid": 12}, P + "merge_requests/get_merge_request_notes_service.rb"),
    ("get_repository_file", "read", "project_id", "Read {file_path} at {ref} in project {project_id}", None, [],
     {"project_id": "acme/shop", "file_path": "config/deploy.yml", "ref": "main"}, P + "repositories/get_repository_file_service.rb"),
    ("get_pipeline", "read", "id", "Show pipeline {pipeline_id} of project {id}", None, [], {"id": "acme/shop", "pipeline_id": 1001}, P + "pipelines/get_pipeline_service.rb"),
    ("get_project", "read", "project_id", "Show project {project_id}", None, [], PROJ, P + "projects/get_project_service.rb"),
    ("get_saved_view_work_items", "read", "project_id", "List the work items of saved view {saved_view_id}", None, [],
     {"project_id": "acme/shop", "saved_view_id": "gid://gitlab/WorkItems::SavedViews::SavedView/3"}, P + "work_items/get_saved_view_work_items_service.rb"),
    ("get_user", "read", None, "Show GitLab user {username}", None, [], {"username": "jdoe"}, P + "users/get_user_service.rb"),
    ("get_work_item", "read", "project_id", "Show work item #{work_item_iid} of project {project_id}", None, [],
     {"project_id": "acme/shop", "work_item_iid": 12}, P + "work_items/get_work_item_service.rb"),
    ("get_workitem_notes", "read", "project_id", "Show the comments on work item #{work_item_iid} of project {project_id}", "Unlisted, but callable by name.", [],
     {"project_id": "acme/shop", "work_item_iid": 12}, P + "work_items/get_work_item_notes_service.rb"),
    ("get_work_item_types", "read", "project_id", "List work item types of project {project_id}", None, [], PROJ, P + "work_items/get_work_item_types_service.rb"),
    ("link_work_items", "write", "project_id", "Link work items to #{work_item_iid} in project {project_id}", None, [],
     {"project_id": "acme/shop", "work_item_iid": 12, "work_items_ids": ["gid://gitlab/WorkItem/9"]}, P + "work_items/link_work_items_service.rb"),
    ("list_commits", "read", "project_id", "List commits of project {project_id}", None, [], PROJ, P + "commits/list_commits_service.rb"),
    ("list_groups", "read", None, "List GitLab groups", None, [], {}, P + "groups/list_groups_service.rb"),
    ("list_merge_requests", "read", "project_id", "List merge requests of project {project_id}", None, [], PROJ, P + "merge_requests/list_merge_requests_service.rb"),
    ("list_projects", "read", None, "List GitLab projects", None, [], {}, P + "projects/list_projects_service.rb"),
    ("list_repository_tree", "read", "project_id", "List files of project {project_id}", None, [], PROJ, P + "repositories/list_repository_tree_service.rb"),
    ("list_project_members", "read", "project_id", "List members of project {project_id}", None, [], PROJ, P + "projects/list_project_members_service.rb"),
    ("list_todos", "read", None, "List your GitLab to-do items", None, [], {}, P + "todos/list_todos_service.rb"),
    ("list_wiki_pages", "read", "project_id", "List wiki pages of project {project_id}", None, [], PROJ, P + "wikis/list_wiki_pages_service.rb"),
    ("list_work_items", "read", "project_id", "List work items of project {project_id}", None, [], PROJ, P + "work_items/list_work_items_service.rb"),
    ("save_merge_request_review", "write", "project_id", "Review merge request !{merge_request_iid} of project {project_id} ({method})",
     "Comments, review threads and approvals are the reviewer's part, as GitHub's pull_request_review_write is a write.", [],
     {"project_id": "acme/shop", "merge_request_iid": 12, "method": "create_note", "body": "Looks good"}, P + "merge_requests/save_merge_request_review_service.rb"),
    ("save_note", "write", "project_id", "Comment on project {project_id}", None, [],
     {"project_id": "acme/shop", "merge_request_iid": 12, "body": "Rebased on main"}, P + "notes/save_note_service.rb"),
    ("save_pipeline", "write", "project_id", "Run, retry, cancel or rename a pipeline in project {project_id}",
     "Running a pipeline is a write, as dispatching a GitHub workflow is.", [],
     {"project_id": "acme/shop", "ref": "main"}, P + "pipelines/save_pipeline_service.rb"),
    ("save_work_item", "write", "project_id", "Create or update a work item in project {project_id}",
     "Making a confidential work item visible is access.", [("access", "confidential", "not-confidential", False)],
     {"project_id": "acme/shop", "title": "Checkout fails on Safari", "type_name": "Issue"}, P + "work_items/save_work_item_service.rb"),
    ("search_labels", "read", "full_path", "Search labels of {full_path}", None, [],
     {"full_path": "acme/shop", "is_project": True, "search": "bug"}, P + "labels/search_service.rb"),
    # EE GraphQL-backed tools.
    ("attach_scan_profile", "write", None, "Attach security scan profile {security_scan_profile_id}", "Turns scanners on for the projects and groups named.", [],
     {"security_scan_profile_id": "gid://gitlab/Security::ScanProfile/1", "project_ids": ["gid://gitlab/Project/9"]}, E + "security/attach_scan_profile_service.rb"),
    ("get_duo_session", "read", None, "Show GitLab Duo session {workflow_id}", None, [], {"workflow_id": "7"}, E + "duo_workflows/get_duo_session_service.rb"),
    ("get_vulnerability", "read", None, "Show vulnerability {vulnerability_id}", None, [], {"vulnerability_id": 99}, E + "security/get_vulnerability_service.rb"),
    ("list_duo_agents_and_flows", "read", "project_id", "List GitLab Duo agents and flows of project {project_id}", None, [], PROJ, E + "duo_workflows/list_duo_agents_and_flows_service.rb"),
    ("list_duo_sessions", "read", "project_id", "List your GitLab Duo sessions", None, [], {}, E + "duo_workflows/list_duo_sessions_service.rb"),
    ("list_vulnerabilities", "read", "project_full_path", "List vulnerabilities of project {project_full_path}", None, [],
     {"project_full_path": "acme/shop"}, E + "security/list_vulnerabilities_service.rb"),
    ("save_vulnerability", "write", None, "Change vulnerability {vulnerability_id} ({action})",
     "Dismissed vulnerabilities no longer block merge requests under security policies, so dismissing is access, as in the REST rules.",
     [("access", "action", "dismiss", "dismiss")],
     {"action": "confirm", "vulnerability_id": 99}, E + "security/save_vulnerability_service.rb"),
    # Grape routes marked as tools (route_setting :mcp).
    ("fork_repository", "write", "id", "Fork project {id}", "Forking is a write, as GitHub's fork_repository is; GitLab does not let a fork be more visible than its source.", [],
     {"id": "acme/shop", "namespace_path": "jdoe"}, "lib/api/projects.rb"),
    ("list_pipelines", "read", "id", "List pipelines of project {id}", None, [], {"id": "acme/shop"}, "lib/api/ci/pipelines.rb"),
    ("get_pipeline_jobs", "read", "id", "List the jobs of pipeline {pipeline_id} in project {id}", "Unlisted, but callable by name.", [],
     {"id": "acme/shop", "pipeline_id": 1001}, "lib/api/ci/pipelines.rb"),
    ("list_branches", "read", "id", "List branches of project {id}", None, [], {"id": "acme/shop"}, "lib/api/branches.rb"),
    ("get_issue", "read", "id", "Show issue #{issue_iid} of project {id}", "Unlisted, but callable by name.", [], {"id": "acme/shop", "issue_iid": 12}, "lib/api/issues.rb"),
    ("create_issue", "write", "id", "Open issue {title} in project {id}", "Unlisted, but callable by name.", [],
     {"id": "acme/shop", "title": "Checkout fails on Safari"}, "lib/api/issues.rb"),
    ("get_merge_request_commits", "read", "id", "List the commits of merge request !{merge_request_iid} in project {id}", "Unlisted, but callable by name.", [],
     {"id": "acme/shop", "merge_request_iid": 12}, "lib/api/merge_requests.rb"),
    ("get_merge_request_diffs", "read", "id", "Show the diffs of merge request !{merge_request_iid} in project {id}", "Unlisted, but callable by name.", [],
     {"id": "acme/shop", "merge_request_iid": 12}, "lib/api/merge_requests.rb"),
    ("get_merge_request_pipelines", "read", "id", "List the pipelines of merge request !{merge_request_iid} in project {id}", "Unlisted, but callable by name.", [],
     {"id": "acme/shop", "merge_request_iid": 12}, "lib/api/merge_requests.rb"),
    # Aggregated tools, over routes that are not tools of their own.
    ("search", "read", None, "Search GitLab for {search}", "Dispatches to the instance, group or project search route by its arguments.", [],
     {"scope": "blobs", "search": "AWS_SECRET", "project_id": "acme/shop"}, P + "search/search_service.rb"),
    ("manage_pipeline", "write", "id", "Rename or delete pipeline {pipeline_id} of project {id}",
     "Unlisted, but callable by name. Without a name it deletes the pipeline (GitLab checks name.present?, which is false for blank text), "
     "which is delete, as in the REST rules.",
     [("delete", "name", "delete", None), ("delete", "name~blank", "delete-blank-name", "  ")],
     {"id": "acme/shop", "pipeline_id": 1001, "name": "nightly"}, P + "pipelines/pipeline_service.rb"),
    ("save_merge_request", "write", "project_id", "Create or update a merge request in project {project_id}", None, [],
     {"project_id": "acme/shop", "title": "Add login", "source_branch": "feature/login", "target_branch": "main"}, P + "merge_requests/save_merge_request_service.rb"),
    ("start_duo_session", "irreversible", "project_id", "Start a GitLab Duo session in project {project_id} with goal {goal}",
     "Hands a free-form goal to an agent that acts in the project with the user's access; tools that hand a task to another agent are irreversible.", [],
     {"project_id": "acme/shop", "goal": "Fix the failing checkout test"}, E + "duo_workflows/start_duo_session_service.rb"),
    ("send_duo_session_input", "irreversible", None, "Answer GitLab Duo session {workflow_id}",
     "Approves or rejects a plan or tool call an agent is waiting on, or redirects it with a message: the agent then acts in the project.", [],
     {"workflow_id": "7", "human_approval": True}, E + "duo_workflows/send_duo_session_input_service.rb"),
    ("semantic_search", "read", "project_id", "Search the code of project {project_id} for {q}", None, [],
     {"scope": "code", "q": "where are webhooks signed", "project_id": "acme/shop"}, E + "semantic_search/semantic_search_service.rb"),
    # Orbit (opt-in toolset): commands come from the knowledge graph server;
    # query_graph is the one GitLab's source names.
    ("query_graph", "read", None, "Query the GitLab knowledge graph", "Orbit's commands are read-only queries of the knowledge graph; commands other than query_graph are named by the Orbit server at run time and stay unknown.", [],
     {"query": "MATCH (p:Project) RETURN p LIMIT 5"}, E + "orbit/command_catalog.rb"),
]
ALIASES = {
    "add_branch": ["create_branch"], "add_commit": ["create_commit"], "get_merge_request_notes": ["list_all_merge_request_notes"],
    "list_merge_requests": ["gitlab_merge_request_search"], "save_note": ["create_merge_request_note", "create_workitem_note", "create_work_item_note"],
    "search": ["gitlab_search"], "get_workitem_notes": ["get_work_item_notes"], "save_work_item": ["create_work_item", "update_work_item"],
    "save_merge_request": ["create_merge_request", "update_merge_request"], "semantic_search": ["semantic_code_search"],
    "get_duo_session": ["get_duo_workflow_status"], "get_merge_request_diffs": ["list_merge_request_diffs"],
    "save_vulnerability": ["dismiss_vulnerability", "confirm_vulnerability", "revert_to_detected_vulnerability",
                           "update_vulnerability_severity", "create_vulnerability_issue"],
}

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    if f.startswith("mcp-"):
        os.remove(D + "fixtures/" + f)


def fixture(name, tool, args, desc):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    lines = [f"# description: {desc}", "POST /api/v4/mcp HTTP/1.1", "Host: gitlab.com", "Authorization: Bearer opf_gitlab_EXAMPLE",
             "Content-Type: application/json", "Accept: application/json, text/event-stream", "", json.dumps(body)]
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")


def cond_yaml(arg, value):
    if arg.endswith("~blank"):
        return "{ arg: %s, matches: '^\\s*$' }" % arg[:-len("~blank")]
    if value is None:
        return "{ arg: %s, empty: true }" % arg
    if value is True:
        return "{ arg: %s, in: %s }" % (arg, json.dumps(TRUE))
    if value is False:
        return "{ arg: %s, in: %s }" % (arg, json.dumps(["false", "0", "f", "n", "no", "off"]))
    return "{ arg: %s, equals: %s }" % (arg, json.dumps(value))


def wrap(text, indent="      "):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > 100 and line.strip():
            out.append(line)
            line = indent
        line += ("" if line.strip() == "" else " ") + w
    out.append(line)
    return out


def describe(card, args):
    import re
    return re.sub(r"\{([^}]+)\}", lambda m: str(args.get(m.group(1), "…")), card)


L = ["# GitLab's MCP server (POST gitlab.com/api/v4/mcp, built into GitLab): a rule for every tool",
     "# Mcp::Tools::Manager registers, with their aliases. Written by gitlabmcp.py from GitLab's source.",
     "operations:"]
n = 0
for name, cls, res, card, note, conds, args, src in TOOLS:
    for alias in [name] + ALIASES.get(name, []):
        slug = alias.replace("_", "-")
        rid = f"gitlab.mcp.{slug}"
        L += [f"  - id: {rid}", f"    match: {{ mcp: {{ tool: {alias} }} }}", f"    class: {cls}"]
        if conds:
            L.append("    when:")
            for c, arg, label, value in conds:
                L += [f"      - if: {cond_yaml(arg, value)}", f"        class: {c}"]
        if res:
            L.append(f"    resource: {{ arg: {res}, kind: {'url' if res == 'url' else 'project'} }}")
        L += [f"    card: {json.dumps(card)}", "    status: verified", f"    verified: {DATE}", "    sources:", f"      - {MANAGER}", f"      - {svc(src)}"]
        full = note or ""
        if alias != name:
            full = f"An alias of {name}, which GitLab resolves to it. " + full
        if full.strip():
            L.append("    notes: >-")
            L += wrap(full.strip())
        L.append("    tests:")
        base = f"mcp-{slug}"
        fixture(base + ".http", alias, args, describe(card, args))
        n += 1
        L += [f"      - fixture: fixtures/{base}.http", f"        expect: {cls}"]
        if res and res in args:
            L.append(f"        resource: {json.dumps(str(args[res]))}")
        for c, arg, label, value in conds:
            a = json.loads(json.dumps(args))
            key = arg[:-len("~blank")] if arg.endswith("~blank") else arg
            if label == "delete" and value is None:
                a.pop(key, None)
            elif key == "actions.action":
                a["actions"].append({"action": "delete", "file_path": "old.yml"})
            else:
                a[key] = value
            fixture(f"{base}-{label}.http", alias, a, describe(card, a) + f" ({label})")
            n += 1
            L += [f"      - fixture: fixtures/{base}-{label}.http", f"        expect: {c}"]
            if res and res in a:
                L.append(f"        resource: {json.dumps(str(a[res]))}")
        L.append("")
open(D + "mcp.yaml", "w").write("\n".join(L))
print(sum(1 + len(ALIASES.get(t[0], [])) for t in TOOLS), "rules,", n, "fixtures")
