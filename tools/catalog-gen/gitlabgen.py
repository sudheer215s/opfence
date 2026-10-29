# Writes catalog/gitlab (rules and fixtures, not provider.yaml) from GitLab's
# OpenAPI 3 description (doc/api/openapi/openapi_v3.yaml, generated from the
# Grape routes). Run from the repo root:
#   python3 -I gitlabgen.py <openapi_v3.yaml> <gitlab commit>
#
# Every operation that is not a GET gets a rule whose class is reviewed here,
# by family (the spec's tag) and path; the script fails on any operation no
# entry classifies, so a new endpoint is never classed by a default. GETs are
# reads by the provider's default except those listed in CRED_GETS, whose
# responses carry secrets (found from the spec's response schemas and the
# Grape entities in lib/api/entities).
import json, os, re, sys

SPEC_PATH, COMMIT = sys.argv[1], sys.argv[2]
if SPEC_PATH.endswith(".json"):
    SPEC = json.load(open(SPEC_PATH))
else:
    import yaml
    SPEC = yaml.safe_load(open(SPEC_PATH))
D = "catalog/gitlab/"
SRC = f"https://gitlab.com/gitlab-org/gitlab/-/blob/{COMMIT}/doc/api/openapi/openapi_v3.yaml"
ENT = f"https://gitlab.com/gitlab-org/gitlab/-/blob/{COMMIT}/lib/api/entities"
HOST = "gitlab.com"
DATE = "2026-10-28"
TRUE = ["true", "1", "t", "y", "yes", "on"]
FALSE = ["false", "0", "f", "n", "no", "off"]

# ---------------------------------------------------------------------------
# Operations. Grape's optional segment "(-/)" is two routes; both get rules.
ops = []
for p, item in SPEC["paths"].items():
    assert p.startswith("/api/v4/"), p
    for m, op in item.items():
        if m not in ("get", "post", "put", "patch", "delete", "head"):
            continue
        rel = p[len("/api/v4"):]
        forms = [rel]
        if "(-/)" in rel:
            forms = [rel.replace("(-/)", ""), rel.replace("(-/)", "-/")]
        for i, f in enumerate(forms):
            ops.append((m.upper(), f, op, i == 1))

# ---------------------------------------------------------------------------
# Reviewed classes: tag -> [(method regex, path regex, class, note)], first
# match wins. Paths are relative to /api/v4.
W, Dl, Ir, R, A, C, M, U = "write", "delete", "irreversible", "read", "access", "credential", "money", "unknown"
AUTH_NOTE = "Workhorse's pre-check before an upload; nothing is stored."
TOKEN_EXCHANGE = ("Returns a short-lived token for the same user, as exchanging a credential the caller already "
                  "holds is (ARCHITECTURE §4.5).")
T = {
    "Access requests": [
        ("PUT", r"/approve$", A, "Gives the user a role in the group or project."),
        ("DELETE", r"", W, "Denying a request leaves access as it was."),
        ("POST", r"", W, None),
    ],
    "Access tokens": [
        ("DELETE", r"", A, "Apps and scripts that use the token stop working."),
        ("POST", r"/rotate$", C, "Returns the new token; the old one stops working."),
        ("POST", r"", C, "Returns the new token."),
    ],
    "Active context": [
        ("DELETE", r"/dead_queue$", Dl, "Discards indexing items that failed; the index can be rebuilt."),
        (".*", r"", W, "Instance administration."),
    ],
    "Add on purchases": [(".*", r"", M, "GitLab.com subscription administration.")],
    "Advanced search rollout": [(".*", r"", W, "Instance administration.")],
    "Alert management": [
        ("POST", r"/authorize$", R, AUTH_NOTE),
        ("DELETE", r"", Dl, None),
        (".*", r"", W, None),
    ],
    "Applications": [
        ("POST", r"", C, "Returns the application's secret."),
        ("PUT", r"", A, "Redirect URIs and scopes decide what the application's users grant it."),
        ("DELETE", r"", A, "Every token issued to the application stops working."),
    ],
    "Approval rules": [(".*", r"", A, "Approval rules decide who must approve a merge request before it can merge.")],
    "Avatars": [(".*", r"", W, None)],
    "Award emoji": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Badges": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Batched background migrations": [(".*", r"", W, "Instance administration.")],
    "Batched background operations": [(".*", r"", W, "Instance administration.")],
    "Boards": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Branches": [
        ("DELETE", r"/merged_branches$", Dl, "Deletes every branch already merged into the default branch; their commits are in it."),
        ("DELETE", r"", Dl, "A branch can be pushed again from any clone, as for GitHub's branches."),
        ("PUT", r"/(un)?protect$", A, "Branch protection decides who can push and merge."),
        ("POST", r"", W, None),
    ],
    "Broadcast messages": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "CI catalog": [(".*", r"", W, None)],
    "CI jobs": [
        ("POST", r"/erase$", Ir, "Erases the job's log and artifacts."),
        ("POST", r"/play$", W, "Runs a manual job, often a deployment gate; dispatching a GitHub workflow is a write too."),
        ("POST", r"", W, None),
    ],
    "CI lint": [(".*", r"", R, "Validates CI/CD configuration; a dry run simulates creating a pipeline without creating one.")],
    "CI minutes": [(".*", r"", M, "GitLab.com subscription administration.")],
    "CI resource groups": [(".*", r"", W, None)],
    "CI runners": [
        ("POST", r"^/runners/verify$", R, "Checks a runner token the caller already holds."),
        ("POST", r"", C, "Returns a runner authentication token, which picks up jobs with their CI/CD variables."),
        ("DELETE", r"", Dl, "Unregisters with the runner's own token; it can be registered again."),
    ],
    "CI triggers": [
        ("POST", r"/trigger/pipeline$", W, "Runs a pipeline with a trigger token, as creating one does."),
        ("POST", r"", C, "Returns the trigger token, which runs pipelines with any variables."),
        ("PUT", r"", C, "Returns the trigger token."),
        ("DELETE", r"", A, "Whoever uses the trigger token can no longer run pipelines."),
    ],
    "CI variables": [
        ("DELETE", r"", Ir, "GitLab keeps no earlier value, and variables often hold secrets."),
        (".*", r"", W, "Plain variables are settings; masked and hidden ones are secrets (conditions below)."),
    ],
    "Cluster agents": [
        ("DELETE", r"/tokens/", A, "Whoever uses the agent token can no longer connect."),
        ("POST", r"/tokens$", C, "Returns the agent token."),
        ("POST", r"/url_configurations$", A, "Decides where GitLab connects to reach the agent, and with which certificate."),
        ("DELETE", r"", Dl, "The agent's configuration lives in the repository; it can be registered again."),
        ("POST", r"", W, None),
    ],
    "Clusters": [
        ("DELETE", r"", Dl, "Removes the integration; the cluster itself stays."),
        (".*", r"", A, "Gives GitLab, and the pipelines that deploy to it, a service token for the Kubernetes cluster."),
    ],
    "Code Suggestions": [
        ("POST", r"/(direct_access|connection_details)$", R, TOKEN_EXCHANGE),
        (".*", r"", R, "Asks the model for completions; nothing is changed."),
    ],
    "Code search": [("DELETE", r"", Dl, "The index can be rebuilt."), (".*", r"", W, "Instance administration.")],
    "Commit statuses": [(".*", r"", W, None)],
    "Commits": [(".*", r"", W, None)],
    "Compliance policy settings": [(".*", r"", A, "Compliance controls and security policy settings decide what merge requests and projects must satisfy.")],
    "Container registry": [
        ("DELETE", r"", Dl, "Images can be pushed again from their builds, as for Artifact Registry's Docker images."),
        ("POST", r"", W, "Notifications from the registry itself."),
    ],
    "Custom attributes": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Data management": [(".*", r"", W, "Instance administration.")],
    "Dependency management": [(".*", r"", W, "Creates an export to download later.")],
    "Dependency proxy": [(".*", r"", Dl, "Cached images are fetched again on their next use.")],
    "Deploy resources": [
        ("POST", r"/deploy_tokens$", C, "Returns the deploy token."),
        ("DELETE", r"/deploy_tokens/", A, "Whoever uses the deploy token can no longer read or push."),
        (".*", r"deploy_keys", A, "A deploy key with write access can push to the repository; GitHub's deploy keys are access too."),
        ("POST", r"/approval$", A, "Approving lets a deployment to a protected environment run."),
        ("DELETE", r"", Dl, None),
        (".*", r"", W, None),
    ],
    "Discussions": [("DELETE", r"", Dl, "As for GitHub's comments."), (".*", r"", W, None)],
    "Draft notes": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Enterprise users": [
        ("DELETE", r"", Ir, "Deletes the account."),
        (".*", r"", A, "Changing an enterprise user's email or two-factor authentication can hand over the account."),
    ],
    "Environments": [
        ("POST", r"/stop(_stale)?$", Dl, "Stopping runs the environment's on_stop job, which usually tears the deployment down; it can be deployed again."),
        ("DELETE", r"", Dl, "Deletes the environment's deployment history; GitLab environments hold no secrets (variables are scoped by name and stay)."),
        (".*", r"", W, None),
    ],
    "Epics": [
        ("DELETE", r"epics/\{epic_iid\}$", Ir, "GitLab keeps no deleted epic, with its discussion."),
        ("DELETE", r"", Dl, "Removes a link; it can be added again."),
        (".*", r"", W, None),
    ],
    "Error tracking": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Experiments": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "External status checks": [
        ("POST", r"/retry$", W, None),
        (".*", r"", A, "External status checks decide whether a merge request can merge; reporting a check as passed bypasses it."),
    ],
    "Feature flags": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Features": [(".*", r"", W, "Instance administration: GitLab's own feature flags.")],
    "Files": [("DELETE", r"", Dl, "The file stays in the repository's history, as for GitHub's contents."), (".*", r"", W, None)],
    "Freeze periods": [
        ("POST", r"", W, None),
        (".*", r"", A, "Deploy freezes decide when deployments may run; changing or removing one lets them run."),
    ],
    "GLQL": [(".*", r"", R, "Runs a GitLab Query Language query; nothing is changed.")],
    "Geo": [
        ("POST", r"/receive_pack$", U, "Carries a push for gitlab-shell, which Opfence does not read."),
        ("POST", r"/node_proxy/\{id\}/graphql$", U, "Passes a GraphQL request, which can be a mutation, to another site."),
        ("POST", r"/(info_refs_receive_pack|info_refs_upload_pack|upload_pack)$", R, "Reads refs or fetches for gitlab-shell."),
        ("DELETE", r"", Dl, "A secondary site can be added and synced again."),
        (".*", r"", W, "Instance administration."),
    ],
    "GitLab Duo": [
        ("POST", r"/direct_access$", R, TOKEN_EXCHANGE),
        (".*", r"", R, "Asks the model; nothing is changed."),
    ],
    "GitLab Duo workflows": [
        ("POST", r"/direct_access$", R, TOKEN_EXCHANGE),
        ("POST", r"/workflows/\{workflow_id\}/(execute|resume|restart)$", Ir,
         "Runs the flow, which hands a free-form goal to an agent acting in the project; tools that hand a task to "
         "another agent are irreversible."),
        ("POST", r"^/ai/duo_workflows/workflows$", W, "Creating a flow is a write; starting it is irreversible (condition below)."),
        (".*", r"", W, None),
    ],
    "GitLab Pages": [
        ("DELETE", r"/pages$", Dl, "Pages can be deployed again from the pipeline."),
        ("DELETE", r"", Dl, None),
        ("POST", r"/domains$", A, "A public domain serves the site."),
        ("PUT", r"/verify$", W, None),
        ("PUT", r"/domains/", A, "A public domain serves the site."),
        (".*", r"", W, None),
    ],
    "GitLab subscriptions": [(".*", r"", M, "GitLab.com subscription administration.")],
    "Group credentials inventory": [
        ("POST", r"/rotate$", C, "Returns the new token."),
        (".*", r"", A, "Revoking a credential stops whatever uses it."),
    ],
    "Group import and export": [("POST", r"/authorize$", R, AUTH_NOTE), (".*", r"", W, None)],
    "Groups": [
        ("DELETE", r"^/groups/\{id\}$", Dl, "Marks the group for deletion; it can be restored until then. permanently_remove deletes it at once (condition below)."),
        ("DELETE", r"/(share|shared_projects)/", A, None),
        ("DELETE", r"/uploads/", Dl, None),
        ("POST", r"/authorize$", R, AUTH_NOTE),
        ("POST", r"/projects/\{project_id\}$", A, "Moves a project into the group, whose members gain access to it."),
        ("POST", r"/(share|transfer|transfer_to_organization)$", A, None),
        ("PUT", r"/security_settings$", A, None),
        (".*", r"", W, None),
    ],
    "Hooks": [
        ("PUT", r"/(custom_headers|url_variables)/", C, "Custom header and URL variable values are write-only secrets."),
        ("DELETE", r"", Dl, "As for GitHub's webhooks."),
        ("POST", r"/(resend|test/\{trigger\})$", W, None),
        ("POST", r"^/hooks/\{hook_id\}$", W, "Sends a test event."),
        (".*", r"", A, "Webhooks send events, with their content, to the URL; GitHub's are access too."),
    ],
    "Imports": [(".*", r"", W, None)],
    "Instance": [
        ("PUT", r"/settings$", A, "Instance-wide settings: sign-up, authentication, visibility and limits."),
        (".*", r"", W, None),
    ],
    "Integrations": [
        ("POST", r"/slack/options$", R, None),
        ("POST", r"", W, "Runs a chat command (issue, deploy) or delivers a chat event."),
        ("DELETE", r"", Dl, "Turns the integration off; its settings can be entered again."),
        ("PUT", r"", A, "Integrations send the project's events and content to another service, with credentials stored in GitLab."),
    ],
    "Invitations": [(".*", r"", A, "Invitations decide who joins with which role.")],
    "Issues": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Jira Connect subscriptions": [(".*", r"", A, "Shares the namespace's development information with the Jira site.")],
    "Jira forge installation": [
        ("POST", r"/forge_token$", C, "Registers a token GitLab uses to call Jira."),
        ("DELETE", r"", Dl, None),
        (".*", r"", A, None),
    ],
    "Jira forge subscriptions": [("DELETE", r"", Dl, None), (".*", r"", A, "Shares the namespace's development information with the Jira site.")],
    "Jira forge user delegation": [(".*", r"", C, "Creates a delegation token.")],
    "Job artifacts": [
        ("DELETE", r"^/projects/\{id\}/artifacts$", Ir, "Deletes every job's artifacts in the project."),
        ("DELETE", r"", Ir, "Artifacts cannot be produced again without running the job again."),
        (".*", r"", W, None),
    ],
    "Jobs": [
        ("POST", r"^/jobs/request$", C, "A runner picking up a job receives its CI/CD variables, secrets included."),
        ("POST", r"/authorize$", R, AUTH_NOTE),
        (".*", r"", W, "Runner API: job state, logs and artifacts."),
    ],
    "Keys": [(".*", r"", A, "SSH and GPG keys decide who can push and whose commits verify; GitHub's are access too.")],
    "Knowledge graph": [(".*", r"", W, "Instance administration.")],
    "LDAP": [("POST", r"/ldap_sync$", W, None), (".*", r"", A, "LDAP group links grant group roles.")],
    "Labels": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Licenses": [
        (".*", r"managed_licenses", A, "License policies decide which dependencies merge requests may bring in."),
        ("DELETE", r"", Dl, None),
        (".*", r"", W, "Instance administration."),
    ],
    "ML Model Registry": [("PUT", r"/authorize$", R, AUTH_NOTE), (".*", r"", W, None)],
    "MLOps": [
        (".*", r"/(delete)$", Ir, "GitLab's MLflow API has no restore."),
        ("POST", r"/(search|get-latest-versions)$", R, "Searches; nothing is changed."),
        (".*", r"", W, None),
    ],
    "Markdown": [(".*", r"", R, "Renders Markdown; nothing is stored.")],
    "Member roles": [(".*", r"", A, "Custom roles decide what members can do.")],
    "Members": [(".*", r"", A, None)],
    "Merge request approvals": [
        ("POST", r"/(approve|unapprove)$", W, "Approving is the reviewer's part, as GitHub's reviews are writes."),
        ("PUT", r"/reset_approvals$", W, None),
        (".*", r"", A, "Approval rules and settings decide who must approve a merge request before it can merge."),
    ],
    "Merge requests": [
        ("DELETE", r"merge_requests/\{merge_request_iid\}$", Ir, "GitLab keeps no deleted merge request, with its discussion."),
        ("DELETE", r"", Dl, None),
        (".*", r"", W, None),
    ],
    "Merge trains": [(".*", r"", W, "The merge request merges when its pipeline passes.")],
    "Metric images": [("POST", r"/authorize$", R, AUTH_NOTE), ("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Migrations": [(".*", r"", W, "Instance administration.")],
    "Milestones": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Mobile push subscriptions": [(".*", r"", W, None)],
    "Namespaces": [(".*", r"", M, "GitLab.com plan, storage and compute administration.")],
    "Notes": [("DELETE", r"", Dl, "As for GitHub's comments."), (".*", r"", W, None)],
    "Notification settings": [(".*", r"", W, None)],
    "Offline transfers": [
        ("POST", r"^/offline_exports$", A, "Exports groups and projects to the object storage named in the request."),
        (".*", r"", W, None),
    ],
    "Orbit": [(".*", r"", R, "Queries the knowledge graph; nothing is changed.")],
    "Organizations": [("DELETE", r"", Dl, "A soft-deleted organization can be restored."), (".*", r"", W, None)],
    "Packages": [("PUT", r"/authorize$", R, AUTH_NOTE), ("DELETE", r"", Dl, "A package can be published again from its source."), (".*", r"", W, None)],
    "Pipeline schedules": [
        ("DELETE", r"", Ir, "Deletes the schedule's variables, whose values GitLab keeps nowhere else."),
        ("POST", r"/take_ownership$", W, "The schedule's pipelines run as the new owner."),
        (".*", r"", W, None),
    ],
    "Pipelines": [
        ("DELETE", r"", Dl, "Deletes the pipeline with its jobs' logs and artifacts; the commit can be run again, as for GitHub's workflow runs."),
        (".*", r"", W, None),
    ],
    "Plan limits": [(".*", r"", W, "Instance administration.")],
    "Project alias": [("DELETE", r"", Dl, None), (".*", r"", W, "Instance administration.")],
    "Project approvals": [(".*", r"", A, "Approval settings decide who must approve a merge request before it can merge.")],
    "Project import": [("POST", r"/authorize$", R, AUTH_NOTE), (".*", r"", W, None)],
    "Project mirrors": [
        ("PUT", r"", A, "Decides which repository the project's branches are pulled from, protected branches included."),
        (".*", r"", W, None),
    ],
    "Project topics": [("DELETE", r"", Dl, None), (".*", r"", W, "Instance administration.")],
    "Projects": [
        ("DELETE", r"^/projects/\{id\}$", Dl, "Marks the project for deletion; it can be restored until then. permanently_remove deletes it at once (condition below)."),
        ("DELETE", r"^/projects/\{id\}/fork$", W, "Removes the fork relationship; the code stays."),
        ("DELETE", r"/issues/\{issue_iid\}$", Ir, "GitLab keeps no deleted issue, with its discussion."),
        (".*", r"/(protection|state_protection_rules)", A, "Protection rules decide who can push or delete packages, images and Terraform state."),
        ("DELETE", r"/share/", A, None),
        ("DELETE", r"/uploads/", Dl, None),
        ("POST", r"/authorize$", R, AUTH_NOTE),
        ("POST", r"/(share|import_project_members/\{project_id\})$", A, None),
        ("PUT", r"/(transfer|security_settings)$", A, None),
        (".*", r"", W, None),
    ],
    "Projects job token scope": [(".*", r"", A, "Decides which projects' CI/CD job tokens can reach this project.")],
    "Protected branches": [(".*", r"", A, "Branch protection decides who can push and merge; GitHub's is access too.")],
    "Protected environments": [(".*", r"", A, "Environment protection decides who can deploy.")],
    "Protected tags": [(".*", r"", A, "Tag protection decides who can create and move release tags.")],
    "Provider identities": [(".*", r"", A, "SAML and SCIM identities decide who signs in as which user.")],
    "Push rules": [(".*", r"", A, "Push rules reject commits by author, message, file or secret; removing one lets them through.")],
    "Releases": [("DELETE", r"/releases/\{tag_name\}$", Dl, "Deletes the release; its tag stays."), ("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Remote mirrors": [
        ("POST", r"/sync$", W, "Pushes to a mirror already configured."),
        ("DELETE", r"", Dl, None),
        (".*", r"", A, "A push mirror pushes the repository to the URL given, on every change."),
    ],
    "Repositories": [("POST", r"/blobs/batch$", R, "Reads several files."), (".*", r"", W, None)],
    "Resource subscriptions": [(".*", r"", W, None)],
    "Rollouts": [(".*", r"", W, None)],
    "Runner controller tokens": [("DELETE", r"", A, None), (".*", r"", C, "Returns the token.")],
    "Runner controllers": [("DELETE", r"/runner_controllers/\{id\}$", Dl, None), (".*", r"", A, "Runner controllers decide which runners pick up which jobs.")],
    "Runners": [
        ("DELETE", r"^/projects/\{id\}/runners/", W, "Unassigns the runner; it stays."),
        ("DELETE", r"", Dl, "A runner can be registered again."),
        ("POST", r"reset_(registration|authentication)_token$", C, "Returns the new token."),
        (".*", r"", A, "Which runners take a project's jobs decides where its CI/CD variables, secrets included, are sent."),
    ],
    "SAML group links": [(".*", r"", A, "SAML group links grant group roles.")],
    "Secure files": [
        ("DELETE", r"", Ir, "Secure files hold signing keys and other secrets GitLab keeps nowhere else."),
        (".*", r"", C, "Secure files are a store for secrets."),
    ],
    "Security scans": [(".*", r"", R, "Scans the file sent; nothing is stored.")],
    "Service accounts": [(".*", r"", A, "Service accounts are identities with their own tokens.")],
    "Sidekiq": [(".*", r"", Ir, "Drops queued background jobs.")],
    "Snippets": [("DELETE", r"", Ir, "Deletes the snippet with its repository."), (".*", r"", W, None)],
    "Software composition analysis": [("POST", r"/authorize$", R, AUTH_NOTE), (".*", r"", W, None)],
    "Storage moves": [(".*", r"", W, "Instance administration.")],
    "Submodules": [(".*", r"", W, None)],
    "Suggestions": [(".*", r"", W, "Applies suggested changes as a commit.")],
    "Tags": [("DELETE", r"", Dl, "A tag can be pushed again from any clone."), (".*", r"", W, None)],
    "Terraform": [
        ("DELETE", r"/lock$", W, "Force-unlocking can let two applies run at once."),
        ("DELETE", r"", Ir, "Terraform state is the record of what Terraform manages; without it the resources are no longer managed."),
        (".*", r"/authorize$", R, AUTH_NOTE),
        ("POST", r"/state/\{name\}$", W, "GitLab keeps earlier versions of the state."),
        (".*", r"", W, None),
    ],
    "To-dos": [(".*", r"", W, None)],
    "Token exchange": [(".*", r"", R, TOKEN_EXCHANGE)],
    "Unleash": [(".*", r"", R, "A feature flag client registering itself or reporting which flags it evaluated; no flag changes.")],
    "Usage data": [(".*", r"", R, "Records a product analytics event about the caller (glab sends one after each command); nothing in the user's projects or settings changes.")],
    "Users": [
        ("DELETE", r"^/users/\{id\}$", Ir, "Deletes the account."),
        ("POST", r"^/user/runners$", C, "Returns the runner's authentication token."),
        ("POST", r"/support_pin$", C, "A support PIN proves to GitLab Support that someone is the user."),
        ("POST", r"/(follow|unfollow)$", W, None),
        (".*", r"^/user/(status|preferences)$", W, None),
        ("PUT", r"credit_card_validation$", W, None),
        (".*", r"", A, "Accounts, emails, identities and two-factor authentication decide who signs in as whom."),
    ],
    "VSCode": [("DELETE", r"", Dl, None), (".*", r"", W, None)],
    "Vulnerabilities": [
        ("POST", r"/(dismiss|resolve)$", A, "Dismissed and resolved vulnerabilities no longer block merge requests under security policies."),
        ("DELETE", r"", Dl, None),
        (".*", r"", W, None),
    ],
    "Wikis": [("DELETE", r"", Dl, "Wiki pages are kept in the wiki's git history."), (".*", r"", W, None)],
    # Tags whose families are reviewed above under other names.
    "Ai agent sessions": [(".*", r"", W, None)],
    "Ai agent identities": [(".*", r"", W, None)],
    "Ai agent audit events": [(".*", r"", W, None)],
}
# The Packages: * tags share the Packages entry, with reads sent as POST.
PKG = [
    ("POST", r"/(upload_urls|advisories/bulk|audits/quick)$", R, "Lists URLs or advisories; nothing is stored."),
    (".*", r"/authorize$", R, AUTH_NOTE),
    ("DELETE", r"", Dl, "A package can be published again from its source."),
    (".*", r"", W, "Publishing a package is a write."),
]

SKIP = {("POST", "/mcp")}   # GitLab's MCP server: its tool rules decide it (mcp.paths, mcp.yaml)


def classify(method, path, op):
    tag = (op.get("tags") or ["-"])[0]
    rules = PKG if tag.startswith("Packages") else T.get(tag)
    assert rules is not None, ("no family", tag, method, path)
    for mre, pre, cls, note in rules:
        if re.fullmatch(mre, method) and re.search(pre, path):
            return cls, note
    raise AssertionError(("unclassified", tag, method, path))


# ---------------------------------------------------------------------------
# GETs whose responses carry secrets.
RT = ["**.runners_token"]
RT_NOTE = ("Maintainers and owners get the legacy runner registration token (runners_token) in the project or group, "
           "which registers a runner that then receives the project's jobs and their CI/CD variables. Under opfence run "
           "the proxy redacts it; anywhere else the call stays credential.")
CRED_GETS = {
    "/admin/ci/variables": ("Returns the instance's CI/CD variables with their values.", None),
    "/admin/ci/variables/{key}": ("Returns the variable's value.", None),
    "/groups/{id}/variables": ("Returns the group's CI/CD variables with their values.", None),
    "/groups/{id}/variables/{key}": ("Returns the variable's value.", None),
    "/projects/{id}/variables": ("Returns the project's CI/CD variables with their values.", None),
    "/projects/{id}/variables/{key}": ("Returns the variable's value.", None),
    "/projects/{id}/pipelines/{pipeline_id}/variables": ("Returns the variables the pipeline ran with, values included.", None),
    "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}/variables/{key}": ("Returns the variable's value.", None),
    "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}": (
        "Returns the schedule's variables with their values; under opfence run the proxy redacts the values.",
        (["variables.value"], "read")),
    "/projects/{id}/triggers": ("Returns the trigger tokens, which run pipelines with any variables; under opfence run the proxy redacts them.", (["token"], "read")),
    "/projects/{id}/triggers/{trigger_id}": ("Returns the trigger token; under opfence run the proxy redacts it.", (["token"], "read")),
    "/projects/{id}/terraform/state/{name}": ("Terraform state holds resources' attributes in plain text, sensitive ones included.", None),
    "/projects/{id}/terraform/state/{name}/versions/{serial}": ("Terraform state holds resources' attributes in plain text, sensitive ones included.", None),
    "/projects/{id}/secure_files/{secure_file_id}/download": ("Secure files hold signing keys and other secrets.", None),
    "/application/settings": ("Returns the instance's settings, among them the Elasticsearch password and AWS secret key, the secret detection service's tokens and the Cube API key.", None),
    "/projects": (RT_NOTE, (RT, "read")),
    "/projects/{id}": (RT_NOTE, (RT, "read")),
    "/users/{user_id}/projects": (RT_NOTE, (RT, "read")),
    "/users/{user_id}/contributed_projects": (RT_NOTE, (RT, "read")),
    "/users/{user_id}/starred_projects": (RT_NOTE, (RT, "read")),
    "/projects/{id}/forks": (RT_NOTE, (RT, "read")),
    "/groups/{id}": (RT_NOTE, (RT, "read")),
    "/groups/{id}/projects": (RT_NOTE, (RT, "read")),
    "/groups/{id}/projects/shared": (RT_NOTE, (RT, "read")),
}
# Writes that return the project or group, runners_token included.
RT_WRITES = {
    ("POST", "/projects"), ("POST", "/projects/user/{user_id}"), ("PUT", "/projects/{id}"),
    ("POST", "/projects/{id}/archive"), ("POST", "/projects/{id}/unarchive"), ("POST", "/projects/{id}/star"),
    ("POST", "/projects/{id}/unstar"), ("POST", "/projects/{id}/restore"), ("POST", "/projects/{id}/fork"),
    ("POST", "/projects/{id}/fork/{forked_from_id}"), ("PUT", "/projects/{id}/transfer"),
    ("POST", "/groups"), ("PUT", "/groups/{id}"), ("POST", "/groups/{id}/archive"), ("POST", "/groups/{id}/unarchive"),
    ("POST", "/groups/{id}/restore"), ("POST", "/groups/{id}/projects/{project_id}"),
    ("POST", "/groups/{id}/transfer_to_organization"), ("POST", "/groups/{id}/share"),
}
# Writes whose responses carry the secrets of a credential GET.
RESP_WRITES = {
    ("PUT", "/projects/{id}/triggers/{trigger_id}"): (["token"], "Returns the trigger token; under opfence run the proxy redacts it."),
    ("POST", "/projects/{id}/pipeline_schedules"): (["variables.value"], "Returns the schedule with its variables' values; under opfence run the proxy redacts them."),
    ("PUT", "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}"): (["variables.value"], "Returns the schedule with its variables' values; under opfence run the proxy redacts them."),
    ("POST", "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}/take_ownership"): (["variables.value"], "Returns the schedule with its variables' values; under opfence run the proxy redacts them."),
}

# ---------------------------------------------------------------------------
# Conditions that make a call stricter. Grape merges the query string into
# the parameters of every method, so each condition reads body and query.
def c_true(arg):
    return ("in", arg, TRUE)
def c_false(arg):
    return ("in", arg, FALSE)
def c_in(arg, vals):
    return ("in", arg, vals)
def c_present(arg):
    return ("present", arg, None)

def props_of(method, path):
    op = SPEC["paths"]["/api/v4" + path][method.lower()]
    out = []
    for ct, c in (op.get("requestBody", {}).get("content") or {}).items():
        sc = c.get("schema", {})
        if "$ref" in sc:
            sc = SPEC["components"]["schemas"][sc["$ref"].split("/")[-1]]
        out += list((sc.get("properties") or {}).keys())
    return out

PUBLIC = c_in("visibility", ["public", "internal"])
access_levels = sorted(p for p in props_of("PUT", "/projects/{id}") if p.endswith("_access_level"))
PROJECT_PUT = [(A, PUBLIC, "visibility")] + [(A, c_in(a, ["enabled", "public"]), a) for a in access_levels] + [
    (A, c_true("public_builds"), "public_builds"), (A, c_true("public_jobs"), "public_jobs"),
    (A, c_false("only_allow_merge_if_pipeline_succeeds"), None), (A, c_true("allow_merge_on_skipped_pipeline"), None),
    (A, c_false("only_allow_merge_if_all_status_checks_passed"), None), (A, c_false("restrict_user_defined_variables"), None),
    (A, c_present("ci_pipeline_variables_minimum_override_role"), None), (A, c_true("ci_push_repository_for_job_token_allowed"), None),
    (A, c_true("ci_allow_fork_pipelines_to_run_in_parent_project"), None), (A, c_false("ci_separated_caches"), None),
    (A, c_false("protect_merge_request_pipelines"), None), (A, c_true("allow_pipeline_trigger_approve_deployment"), None),
    (A, c_false("ci_forward_deployment_enabled"), None), (A, c_present("approvals_before_merge"), None),
    (A, c_present("fallback_approvals_required"), None), (A, c_present("import_url"), None), (A, c_true("mirror"), None),
    (A, c_present("mirror_user_id"), None), (A, c_present("external_authorization_classification_label"), None),
    (A, c_false("security_policy_pipeline_must_succeed"), None), (A, c_false("enforce_auth_checks_on_uploads"), None),
    (Ir, c_true("mirror_overwrites_diverged_branches"), "mirror_overwrites_diverged_branches"),
    (Ir, c_present("ci_delete_pipelines_in_seconds"), "ci_delete_pipelines_in_seconds"),
    (Ir, c_true("container_expiration_policy_attributes.enabled"), None),
]
PROJECT_POST = [(A, PUBLIC, "visibility"), (A, c_in("pages_access_level", ["public"]), None),
                (A, c_true("public_builds"), None), (A, c_true("public_jobs"), None)]
GROUP_PUT = [(A, PUBLIC, "visibility")] + [(A, c, None) for c in [
    c_false("require_two_factor_authentication"), c_present("two_factor_grace_period"), c_false("share_with_group_lock"),
    c_false("membership_lock"), c_false("prevent_sharing_groups_outside_hierarchy"), c_false("prevent_forking_outside_group"),
    c_present("ip_restriction_ranges"), c_present("allowed_email_domains_list"), c_present("default_branch_protection"),
    c_present("default_branch_protection_defaults"), c_present("enabled_git_access_protocol"), c_true("request_access_enabled"),
    c_false("only_allow_merge_if_pipeline_succeeds"), c_true("allow_merge_on_skipped_pipeline"), c_false("require_sha_for_merge"),
    c_present("ldap_cn"), c_present("ldap_access"), c_present("step_up_auth_required_oauth_provider"),
    c_false("service_access_tokens_expiration_enforced"), c_false("auto_ban_user_on_excessive_projects_download"),
    c_present("unique_project_download_limit")]] + [
    (M, c_present("shared_runners_minutes_limit"), None), (M, c_present("extra_shared_runners_minutes_limit"), None)]
GROUP_POST = [(A, PUBLIC, "visibility"), (A, c_false("require_two_factor_authentication"), None)]
SNIPPET = [(A, PUBLIC, "visibility")]
VAR_POST = [(C, c_true("masked"), "masked"), (C, c_true("masked_and_hidden"), "masked_and_hidden")]
VAR_PUT = VAR_POST + [(A, c_false("protected"), "protected")]
SETTINGS_SECRET = re.compile(r"(_secret|_password|_api_key|_secret_key|_access_key|_secret_access_key|_token|private_key)$")
settings_secrets = sorted(p for p in props_of("PUT", "/application/settings")
                          if SETTINGS_SECRET.search(p) and not p.endswith(("_enabled", "_lifetime")))
COND = {
    ("PUT", "/projects/{id}"): (PROJECT_PUT,
        " Making the project or one of its features public or internal, or switching off a merge or pipeline safeguard "
        "(pipelines must pass, user-defined variables restricted, separated caches, protected merge request pipelines, "
        "approvals, pull mirroring settings) is access. Overwriting diverged branches from a mirror, automatic pipeline "
        "deletion and container cleanup policies delete data later, so they are irreversible. On a public or internal "
        "project, a feature's access level enabled makes it visible to everyone who can see the project."),
    ("POST", "/projects"): (PROJECT_POST, " A public or internal project, public Pages or public job logs are access."),
    ("POST", "/projects/user/{user_id}"): (PROJECT_POST, " A public or internal project, public Pages or public job logs are access."),
    ("PUT", "/groups/{id}"): (GROUP_PUT,
        " A public or internal group, and any change to two-factor enforcement, sharing and forking locks, IP and email "
        "domain restrictions, default branch protection, merge safeguards, LDAP links or token expiry enforcement, is "
        "access; compute minute limits are money."),
    ("POST", "/groups"): (GROUP_POST, " A public or internal group, or one that does not require two-factor authentication, is access."),
    ("POST", "/projects/{id}/snippets"): (SNIPPET, " A public or internal snippet is access, as a public gist is."),
    ("PUT", "/projects/{id}/snippets/{snippet_id}"): (SNIPPET, " A public or internal snippet is access, as a public gist is."),
    ("POST", "/snippets"): (SNIPPET, " A public or internal snippet is access, as a public gist is."),
    ("PUT", "/snippets/{id}"): (SNIPPET, " A public or internal snippet is access, as a public gist is."),
    ("PUT", "/projects/{id}/issues/{issue_iid}"): ([(A, c_false("confidential"), "confidential")], " Making a confidential issue visible is access."),
    ("PUT", "/projects/{id}/merge_requests/{merge_request_iid}/merge"): (
        [(Dl, c_true("should_remove_source_branch"), "should_remove_source_branch")], " Removing the source branch is delete."),
    ("POST", "/projects/{id}/repository/commits"): (
        [(Dl, c_true("force"), "force"), (Dl, c_in("actions.action", ["delete"]), "actions")],
        " force overwrites the branch with the new commit, as a forced push does, and a delete action removes a file; "
        "both are delete (the old commits and files stay in any clone)."),
    ("DELETE", "/projects/{id}"): ([(Ir, c_true("permanently_remove"), "permanently_remove")], ""),
    ("DELETE", "/groups/{id}"): ([(Ir, c_true("permanently_remove"), "permanently_remove")], ""),
    ("DELETE", "/projects/{id}/service_accounts/{user_id}"): ([(Ir, c_true("hard_delete"), "hard_delete")], " hard_delete also deletes the account's contributions."),
    ("DELETE", "/groups/{id}/service_accounts/{user_id}"): ([(Ir, c_true("hard_delete"), "hard_delete")], " hard_delete also deletes the account's contributions."),
    ("POST", "/projects/{id}/variables"): (VAR_POST, " A masked or hidden variable is a secret, so setting one is credential."),
    ("PUT", "/projects/{id}/variables/{key}"): (VAR_PUT, " A masked or hidden variable is a secret, so setting one is credential; making one unprotected sends it to pipelines on every branch, including ones the agent can push, which is access."),
    ("POST", "/groups/{id}/variables"): (VAR_POST, " A masked or hidden variable is a secret, so setting one is credential."),
    ("PUT", "/groups/{id}/variables/{key}"): (VAR_PUT, " A masked or hidden variable is a secret, so setting one is credential; making one unprotected sends it to pipelines on every branch, which is access."),
    ("POST", "/admin/ci/variables"): ([(C, c_true("masked"), "masked")], " A masked variable is a secret, so setting one is credential."),
    ("PUT", "/admin/ci/variables/{key}"): ([(C, c_true("masked"), "masked"), (A, c_false("protected"), "protected")], " A masked variable is a secret, so setting one is credential; making one unprotected is access."),
    ("POST", "/projects/{id}/pages/domains"): ([(C, c_present("key"), "key"), (C, c_present("user_provided_key"), None)], " Uploading a certificate's private key is credential."),
    ("PUT", "/projects/{id}/pages/domains/{domain}"): ([(C, c_present("key"), "key"), (C, c_present("user_provided_key"), None)], " Uploading a certificate's private key is credential."),
    ("POST", "/projects/{id}/export"): ([(A, c_present("upload"), "upload")], " With upload, the export is sent to the URL given, which is access."),
    ("PUT", "/projects/{id}/mirror/pull"): ([(Ir, c_true("mirror_overwrites_diverged_branches"), "mirror_overwrites_diverged_branches")], " Overwriting diverged branches discards their commits, which is irreversible."),
    ("POST", "/ai/duo_workflows/workflows"): ([(Ir, c_true("start_workflow"), "start_workflow")], " With start_workflow the flow starts at once, handing its goal to an agent, which is irreversible."),
    ("POST", "/projects/{id}/clusters/user"): ([(C, c_present("platform_kubernetes_attributes.token"), None)], " Storing the cluster's service token is credential."),
    ("POST", "/groups/{id}/clusters/user"): ([(C, c_present("platform_kubernetes_attributes.token"), None)], " Storing the cluster's service token is credential."),
    ("POST", "/admin/clusters/add"): ([(C, c_present("platform_kubernetes_attributes.token"), None)], " Storing the cluster's service token is credential."),
    ("PUT", "/application/settings"): ([(C, c_present(s), None) for s in settings_secrets], " Setting one of its secrets is credential."),
}

# ---------------------------------------------------------------------------
# Names, cards and samples.
def slug(s):
    s = re.sub(r"\([^)]*\)", " ", s)
    s = s.lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    for _ in range(2):
        s = re.sub(r"(^|-)(a|an|the|given|specified|existing|single|new|specific|current)(?=-|$)", "", s).strip("-")
    return re.sub(r"-+", "-", s)

def group_of(tag):
    return slug(tag.replace("Packages: ", "packages-"))

PROJECT = "acme%2Fshop"
SAMPLE = {"branch": "feature%2Flogin", "tag_name": "v1.2.0", "key": "DATABASE_URL", "name": "main", "slug": "home",
          "file_path": "config%2Fdeploy.yml", "sha": "6104942438c14ec7bd21c6cd5bd995272b3faff6", "email": "dev%40example.com",
          "domain": "docs.example.com", "ref": "main", "ref_name": "main", "feature_flag_name": "new-checkout",
          "module_name": "vpc", "module_system": "aws", "module_version": "1.0.0", "package_name": "shop-ui",
          "package_version": "1.0.0", "file_name": "shop-ui-1.0.0.tgz", "path": "com%2Facme%2Fshop", "codename": "stable",
          "trigger": "push_events", "provider": "ldapmain", "cn": "engineers", "uid": "jdoe", "submodule": "vendor%2Flib",
          "environment_id": "7", "recipe_revision": "0", "package_revision": "0", "conan_package_reference": "5ab84d6acfe1f23c4fae0ab88f26e3a396351ac9",
          "package_username": "acme", "package_channel": "stable", "add_on_name": "duo_pro", "model_name": "ci_builds",
          "record_identifier": "7", "secret": "a1b2c3d4", "filename": "screenshot.png", "experiment_name": "pql_three_cta",
          "settings_context_hash": "abc123", "resource_name": "settings", "queue_name": "default", "timestamp": "20261001000000",
          "saml_group_name": "engineers", "sast_endpoint": "scan", "sbom_digest": "abc123", "tag": "latest",
          "channel": "stable", "user_id": "42", "target_id": "8", "group_id": "8", "project_id": "9",
          "node_id": "3", "namespace_id": "8", "sha256": "abc123", "distribution": "stable", "letter": "s", "token_id": "5",
          "impersonation_token_id": "5", "hook_log_id": "11", "external_status_check_id": "2", "subscribable_id": "12",
          "noteable_id": "12", "eventable_id": "12", "merge_request_iid": "12", "issue_iid": "12", "epic_iid": "5",
          "pipeline_id": "1001", "job_id": "2002", "pipeline_schedule_id": "3", "serial": "4", "runner_id": "6"}

def sample(param, path):
    if param == "id":
        if path.startswith("/projects/"):
            return PROJECT
        if path.startswith("/groups/"):
            return "acme"
        if path.startswith(("/users/", "/user/")):
            return "42"
        return "7"
    if param == "user_id" and path.startswith("/users/{user_id}"):
        return "42"
    return SAMPLE.get(param, "7")

def unescape(s):
    from urllib.parse import unquote
    return unquote(s)

def resource_of(path):
    params = re.findall(r"\{([^}]+)\}", path)
    if path.startswith("/projects/{id}"):
        return ("id", "project")
    if path.startswith("/groups/{id}"):
        return ("id", "group")
    if path.startswith("/users/{id}") or path.startswith("/users/{user_id}"):
        return (params[0], "user")
    if path.startswith("/runners/{id}"):
        return ("id", "runner")
    return None

def where(path):
    if path.startswith("/projects/{id}"):
        return " in project {id}"
    if path.startswith("/groups/{id}"):
        return " in group {id}"
    if path.startswith(("/users/{id}", "/users/{user_id}")):
        return " of user {%s}" % re.findall(r"\{([^}]+)\}", path)[0]
    return ""

VERB_FIX = {"Creates": "Create", "Updates": "Update", "Deletes": "Delete", "Sets": "Set", "Removes": "Remove",
            "Fetches": "Fetch", "Searches": "Search", "Logs": "Log", "Receives": "Receive", "Triggers": "Trigger"}

# Nouns in summaries, and the parameter that names them: "Delete a tag"
# becomes "Delete tag {tag_name}".
NOUNS = [
    (r"(a |the )?merge request('s)?", "merge_request_iid", "merge request !{%s}"),
    (r"(an |the )?issue", "issue_iid", "issue #{%s}"),
    (r"(an |the )?epic", "epic_iid", "epic &{%s}"),
    (r"(a |the )?pipeline schedule", "pipeline_schedule_id", "pipeline schedule {%s}"),
    (r"(a |the )?pipeline", "pipeline_id", "pipeline {%s}"),
    (r"(a |the )?job", "job_id", "job {%s}"),
    (r"(a |the )?(repository )?branch", "branch", "branch {%s}"),
    (r"(a |the )?(repository )?tag", "tag_name", "tag {%s}"),
    (r"(a |the )?release", "tag_name", "release {%s}"),
    (r"(a |the |an instance |a project |a group )?variable", "key", "variable {%s}"),
    (r"(a |the )?(project |group )?(web)?hook", "hook_id", "webhook {%s}"),
    (r"(a |the )?deploy key", "key_id", "deploy key {%s}"),
    (r"(a |an |the )?GPG key", "key_id", "GPG key {%s}"),
    (r"(a |an |the )?SSH key", "key_id", "SSH key {%s}"),
    (r"(a |the |a project |a group )?deploy token", "token_id", "deploy token {%s}"),
    (r"(a |the |a project |a group )?access token", "token_id", "access token {%s}"),
    (r"(a |the )?snippet", "snippet_id", "snippet {%s}"),
    (r"(a |the )?milestone", "milestone_id", "milestone {%s}"),
    (r"(an |the )?environment", "environment_id", "environment {%s}"),
    (r"(a |the )?deployment", "deployment_id", "deployment {%s}"),
    (r"(a |the )?label", "name", "label {%s}"),
    (r"(a |the )?wiki page", "slug", "wiki page {%s}"),
    (r"(a |the )?file", "file_path", "file {%s}"),
    (r"(a |the )?(issue )?board", "board_id", "board {%s}"),
    (r"(a |the )?feature flag", "feature_flag_name", "feature flag {%s}"),
    (r"(a |the )?package", "package_id", "package {%s}"),
    (r"(a |the )?runner", "runner_id", "runner {%s}"),
    (r"(a |the )?member", "user_id", "member {%s}"),
    (r"(a |the )?trigger token", "trigger_id", "trigger token {%s}"),
    (r"(a |the )?Terraform state", "name", "Terraform state {%s}"),
    (r"(a |the )?note", "note_id", "comment {%s}"),
    (r"(a |the )?comment", "note_id", "comment {%s}"),
    (r"(a |the )?discussion", "discussion_id", "discussion {%s}"),
    (r"(a |the )?commit", "sha", "commit {%s}"),
    (r"(a |the )?user", "user_id", "user {%s}"),
]

def card_of(method, path, op):
    if (method, path) in CARD:
        return CARD[(method, path)]
    s = (op.get("summary") or op.get("operationId")).strip().rstrip(".")
    first, _, rest = s.partition(" ")
    s = VERB_FIX.get(first, first) + (" " + rest if rest else "")
    params = re.findall(r"\{([^}]+)\}", path)
    used = set()
    scope = None
    for prefix, kind, param in (("/projects/{id}", "project", "id"), ("/groups/{id}", "group", "id"),
                                ("/users/{id}", "user", "id"), ("/users/{user_id}", "user", "user_id")):
        if path.startswith(prefix):
            # "Archive a project" names it; "for a project service account" does not.
            s, n = re.subn(r"\b(a|an|the) %s\b(?=$|,| (to|from|with|in|for|as|by|on|into|of)\b)" % kind, "%s {%s}" % (kind, param), s, count=1)
            scope = param if n else None
            if n:
                used.add(param)
            break
    ALT = {"merge_request_iid": ("merge_request_iid", "noteable_id", "subscribable_id", "eventable_id"),
           "issue_iid": ("issue_iid", "noteable_id", "subscribable_id", "eventable_id"),
           "epic_iid": ("epic_iid", "noteable_id"), "snippet_id": ("snippet_id", "noteable_id"),
           "sha": ("sha", "noteable_id"), "name": ("name", "subscribable_id")}
    for pat, param, repl in NOUNS:
        for cand in ALT.get(param, (param,)):
            if cand in params and cand not in used:
                s2, n = re.subn(r"\b" + pat + r"\b", repl % cand, s, count=1)
                if n:
                    s, _ = s2, used.add(cand)
                break
    # Parents the summary does not name ("Update a URL variable" of which webhook).
    PARENTS = {"hook_id": "webhook {%s}", "merge_request_iid": "merge request !{%s}", "issue_iid": "issue #{%s}",
               "epic_iid": "epic &{%s}", "pipeline_id": "pipeline {%s}", "job_id": "job {%s}", "snippet_id": "snippet {%s}",
               "pipeline_schedule_id": "pipeline schedule {%s}", "agent_id": "agent {%s}", "repository_id": "container repository {%s}",
               "alert_iid": "alert {%s}", "runner_controller_id": "runner controller {%s}"}
    tail = [p for p in params if p not in used and p in PARENTS]
    for p in (tail[:-1] if tail and tail[-1] == params[-1] else tail):
        s += " of " + PARENTS[p] % p
        used.add(p)
    rest_params = [p for p in params if p not in used and not (p == "id" and path.startswith(("/projects/{id}", "/groups/{id}", "/users/{id}")))
                   and not (p == "user_id" and path.startswith("/users/{user_id}"))]
    if rest_params and "{%s}" % rest_params[-1] not in s:
        s += " {%s}" % rest_params[-1]
    return s if scope else s + where(path)

CARD = {
    ("DELETE", "/projects/{id}"): "Delete GitLab project {id}",
    ("DELETE", "/groups/{id}"): "Delete GitLab group {id} with its subgroups and projects",
    ("PUT", "/projects/{id}"): "Change the settings of project {id}",
    ("PUT", "/groups/{id}"): "Change the settings of group {id}",
    ("POST", "/projects"): "Create GitLab project {body.name}",
    ("POST", "/groups"): "Create GitLab group {body.name}",
    ("PUT", "/projects/{id}/transfer"): "Transfer project {id} to namespace {body.namespace}",
    ("POST", "/projects/{id}/variables"): "Set CI/CD variable {body.key} in project {id}",
    ("PUT", "/projects/{id}/variables/{key}"): "Change CI/CD variable {key} in project {id}",
    ("DELETE", "/projects/{id}/variables/{key}"): "Delete CI/CD variable {key} from project {id}",
    ("POST", "/groups/{id}/variables"): "Set CI/CD variable {body.key} in group {id}",
    ("PUT", "/groups/{id}/variables/{key}"): "Change CI/CD variable {key} in group {id}",
    ("DELETE", "/groups/{id}/variables/{key}"): "Delete CI/CD variable {key} from group {id}",
    ("POST", "/admin/ci/variables"): "Set instance CI/CD variable {body.key}",
    ("PUT", "/admin/ci/variables/{key}"): "Change instance CI/CD variable {key}",
    ("DELETE", "/admin/ci/variables/{key}"): "Delete instance CI/CD variable {key}",
    ("DELETE", "/projects/{id}/repository/branches/{branch}"): "Delete branch {branch} of project {id}",
    ("DELETE", "/projects/{id}/repository/merged_branches"): "Delete every merged branch of project {id}",
    ("POST", "/projects/{id}/repository/branches"): "Create branch {body.branch} in project {id}",
    ("DELETE", "/projects/{id}/repository/tags/{tag_name}"): "Delete tag {tag_name} of project {id}",
    ("POST", "/projects/{id}/repository/tags"): "Create tag {body.tag_name} in project {id}",
    ("POST", "/projects/{id}/repository/commits"): "Commit to branch {body.branch} of project {id}",
    ("POST", "/projects/{id}/repository/files/{file_path}"): "Create file {file_path} on branch {body.branch} of project {id}",
    ("PUT", "/projects/{id}/repository/files/{file_path}"): "Change file {file_path} on branch {body.branch} of project {id}",
    ("DELETE", "/projects/{id}/repository/files/{file_path}"): "Delete file {file_path} on branch {body.branch} of project {id}",
    ("PUT", "/projects/{id}/merge_requests/{merge_request_iid}/merge"): "Merge merge request !{merge_request_iid} of project {id}",
    ("POST", "/projects/{id}/merge_requests"): "Open a merge request from {body.source_branch} to {body.target_branch} in project {id}",
    ("PUT", "/projects/{id}/merge_requests/{merge_request_iid}"): "Update merge request !{merge_request_iid} of project {id}",
    ("DELETE", "/projects/{id}/merge_requests/{merge_request_iid}"): "Delete merge request !{merge_request_iid} of project {id} with its discussion",
    ("POST", "/projects/{id}/issues"): "Open issue {body.title} in project {id}",
    ("PUT", "/projects/{id}/issues/{issue_iid}"): "Update issue #{issue_iid} of project {id}",
    ("DELETE", "/projects/{id}/issues/{issue_iid}"): "Delete issue #{issue_iid} of project {id} with its discussion",
    ("POST", "/projects/{id}/pipeline"): "Run a pipeline on {body.ref} in project {id}",
    ("DELETE", "/projects/{id}/pipelines/{pipeline_id}"): "Delete pipeline {pipeline_id} of project {id} with its logs and artifacts",
    ("POST", "/projects/{id}/jobs/{job_id}/play"): "Run manual job {job_id} in project {id}",
    ("POST", "/projects/{id}/jobs/{job_id}/erase"): "Erase job {job_id}'s log and artifacts in project {id}",
    ("DELETE", "/projects/{id}/artifacts"): "Delete every job artifact in project {id}",
    ("POST", "/projects/{id}/deploy_keys"): "Add deploy key {body.title} to project {id}",
    ("POST", "/projects/{id}/deploy_tokens"): "Create deploy token {body.name} in project {id}",
    ("POST", "/projects/{id}/access_tokens"): "Create access token {body.name} for project {id}",
    ("POST", "/groups/{id}/access_tokens"): "Create access token {body.name} for group {id}",
    ("POST", "/user/personal_access_tokens"): "Create personal access token {body.name}",
    ("POST", "/projects/{id}/members"): "Add a member to project {id}",
    ("POST", "/groups/{id}/members"): "Add a member to group {id}",
    ("POST", "/projects/{id}/hooks"): "Add a webhook to {body.url} in project {id}",
    ("POST", "/groups/{id}/hooks"): "Add a webhook to {body.url} in group {id}",
    ("POST", "/projects/{id}/protected_branches"): "Protect branch {body.name} of project {id}",
    ("DELETE", "/projects/{id}/protected_branches/{name}"): "Unprotect branch {name} of project {id}",
    ("POST", "/projects/{id}/triggers"): "Create a pipeline trigger token in project {id}",
    ("DELETE", "/projects/{id}/terraform/state/{name}"): "Delete Terraform state {name} of project {id} with every version",
    ("DELETE", "/projects/{id}/registry/repositories/{repository_id}"): "Delete container repository {repository_id} of project {id} with its images",
    ("POST", "/projects/{id}/export"): "Export project {id}",
    ("DELETE", "/users/{id}"): "Delete GitLab user {id}",
    ("POST", "/projects/{id}/secure_files"): "Upload secure file {body.name} to project {id}",
    ("DELETE", "/projects/{id}/secure_files/{secure_file_id}"): "Delete secure file {secure_file_id} of project {id}",
    ("POST", "/projects/{id}/fork"): "Fork project {id}",
    ("POST", "/ai/duo_workflows/workflows"): "Create a GitLab Duo flow with goal {body.goal}",
    ("POST", "/groups/{id}/share"): "Share group {id} with group {body.group_id}",
    ("DELETE", "/groups/{id}/share/{group_id}"): "Stop sharing group {id} with group {group_id}",
    ("POST", "/projects/{id}/share"): "Share project {id} with group {body.group_id}",
    ("DELETE", "/projects/{id}/share/{group_id}"): "Stop sharing project {id} with group {group_id}",
    ("POST", "/groups/{id}/projects/{project_id}"): "Move project {project_id} into group {id}",
    ("POST", "/projects/{id}/restore"): "Restore project {id}, which is marked for deletion",
    ("POST", "/groups/{id}/restore"): "Restore group {id}, which is marked for deletion",
    ("PUT", "/projects/{id}/mirror/pull"): "Change where project {id} pulls its branches from",
    ("POST", "/projects/{id}/remote_mirrors"): "Push project {id}'s repository to mirror {body.url}",
    ("POST", "/projects/{id}/runners"): "Assign runner {body.runner_id} to project {id}",
    ("PUT", "/runners/{id}"): "Change runner {id}",
}
GET_CARD = {
    "/admin/ci/variables": "Read the instance's CI/CD variables with their values",
    "/admin/ci/variables/{key}": "Read instance CI/CD variable {key}",
    "/groups/{id}/variables": "Read group {id}'s CI/CD variables with their values",
    "/groups/{id}/variables/{key}": "Read CI/CD variable {key} of group {id}",
    "/projects/{id}/variables": "Read project {id}'s CI/CD variables with their values",
    "/projects/{id}/variables/{key}": "Read CI/CD variable {key} of project {id}",
    "/projects/{id}/pipelines/{pipeline_id}/variables": "Read the variables of pipeline {pipeline_id} in project {id}",
    "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}/variables/{key}": "Read variable {key} of pipeline schedule {pipeline_schedule_id} in project {id}",
    "/projects/{id}/pipeline_schedules/{pipeline_schedule_id}": "Read pipeline schedule {pipeline_schedule_id} of project {id} with its variables",
    "/projects/{id}/triggers": "Read project {id}'s pipeline trigger tokens",
    "/projects/{id}/triggers/{trigger_id}": "Read pipeline trigger token {trigger_id} of project {id}",
    "/projects/{id}/terraform/state/{name}": "Read Terraform state {name} of project {id}",
    "/projects/{id}/terraform/state/{name}/versions/{serial}": "Read version {serial} of Terraform state {name} in project {id}",
    "/projects/{id}/secure_files/{secure_file_id}/download": "Download secure file {secure_file_id} of project {id}",
    "/application/settings": "Read the instance's settings with their secrets",
    "/projects": "List GitLab projects",
    "/projects/{id}": "Read project {id}",
    "/users/{user_id}/projects": "List projects of user {user_id}",
    "/users/{user_id}/contributed_projects": "List projects user {user_id} contributed to",
    "/users/{user_id}/starred_projects": "List projects user {user_id} starred",
    "/projects/{id}/forks": "List forks of project {id}",
    "/groups/{id}": "Read group {id}",
    "/groups/{id}/projects": "List projects of group {id}",
    "/groups/{id}/projects/shared": "List projects shared with group {id}",
}

def body_for(method, path):
    if method not in ("POST", "PUT", "PATCH"):
        return None
    b = {
        ("POST", "/projects"): {"name": "shop", "namespace_id": 8, "visibility": "private"},
        ("PUT", "/projects/{id}"): {"description": "Online shop"},
        ("POST", "/groups"): {"name": "Acme", "path": "acme", "visibility": "private"},
        ("PUT", "/groups/{id}"): {"description": "Acme Inc."},
        ("PUT", "/projects/{id}/transfer"): {"namespace": "acme-archive"},
        ("POST", "/projects/{id}/variables"): {"key": "LOG_LEVEL", "value": "debug"},
        ("PUT", "/projects/{id}/variables/{key}"): {"value": "debug"},
        ("POST", "/groups/{id}/variables"): {"key": "LOG_LEVEL", "value": "debug"},
        ("PUT", "/groups/{id}/variables/{key}"): {"value": "debug"},
        ("POST", "/admin/ci/variables"): {"key": "LOG_LEVEL", "value": "debug"},
        ("PUT", "/admin/ci/variables/{key}"): {"value": "debug"},
        ("POST", "/projects/{id}/repository/branches"): {"branch": "feature/login", "ref": "main"},
        ("POST", "/projects/{id}/repository/tags"): {"tag_name": "v1.2.0", "ref": "main"},
        ("POST", "/projects/{id}/repository/commits"): {"branch": "main", "commit_message": "Update deploy config",
                                                         "actions": [{"action": "update", "file_path": "config/deploy.yml", "content": "replicas: 3\n"}]},
        ("POST", "/projects/{id}/repository/files/{file_path}"): {"branch": "main", "content": "replicas: 3\n", "commit_message": "Add deploy config"},
        ("PUT", "/projects/{id}/repository/files/{file_path}"): {"branch": "main", "content": "replicas: 3\n", "commit_message": "Update deploy config"},
        ("PUT", "/projects/{id}/merge_requests/{merge_request_iid}/merge"): {"squash": True},
        ("POST", "/projects/{id}/merge_requests"): {"source_branch": "feature/login", "target_branch": "main", "title": "Add login"},
        ("PUT", "/projects/{id}/merge_requests/{merge_request_iid}"): {"title": "Add login form"},
        ("POST", "/projects/{id}/issues"): {"title": "Checkout fails on Safari"},
        ("PUT", "/projects/{id}/issues/{issue_iid}"): {"state_event": "close"},
        ("POST", "/projects/{id}/pipeline"): {"ref": "main"},
        ("POST", "/projects/{id}/deploy_keys"): {"title": "ci", "key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample ci", "can_push": False},
        ("POST", "/projects/{id}/deploy_tokens"): {"name": "registry-pull", "scopes": ["read_registry"]},
        ("POST", "/projects/{id}/access_tokens"): {"name": "release-bot", "scopes": ["api"], "access_level": 30, "expires_at": "2027-01-01"},
        ("POST", "/groups/{id}/access_tokens"): {"name": "release-bot", "scopes": ["api"], "access_level": 30, "expires_at": "2027-01-01"},
        ("POST", "/user/personal_access_tokens"): {"name": "cli", "scopes": ["read_api"], "expires_at": "2027-01-01"},
        ("POST", "/projects/{id}/members"): {"user_id": 42, "access_level": 30},
        ("POST", "/groups/{id}/members"): {"user_id": 42, "access_level": 30},
        ("POST", "/projects/{id}/hooks"): {"url": "https://hooks.example.com/gitlab", "push_events": True},
        ("POST", "/groups/{id}/hooks"): {"url": "https://hooks.example.com/gitlab", "push_events": True},
        ("POST", "/projects/{id}/protected_branches"): {"name": "release/*", "push_access_level": 40},
        ("POST", "/projects/{id}/export"): {"description": "backup"},
        ("PUT", "/projects/{id}/mirror/pull"): {"enabled": True, "url": "https://github.com/acme/shop.git"},
        ("POST", "/ai/duo_workflows/workflows"): {"project_id": "9", "goal": "Fix the failing checkout test"},
        ("POST", "/projects/{id}/snippets"): {"title": "notes", "files": [{"file_path": "notes.md", "content": "x"}]},
        ("POST", "/snippets"): {"title": "notes", "files": [{"file_path": "notes.md", "content": "x"}]},
        ("PUT", "/projects/{id}/pages/domains/{domain}"): {"auto_ssl_enabled": True},
        ("POST", "/projects/{id}/pages/domains"): {"domain": "docs.example.com", "auto_ssl_enabled": True},
    }.get((method, path), {})
    return b

# ---------------------------------------------------------------------------
# Writing.
os.makedirs(D + "fixtures", exist_ok=True)
# provider.yaml, git.yaml, oauth.yaml and mcp.yaml (and their git-*, oauth-*
# and mcp-* fixtures) are written by hand or by gitlabstatic.py and
# gitlabmcp.py.
HAND = {"provider.yaml", "git.yaml", "oauth.yaml", "mcp.yaml"}
for f in os.listdir(D + "fixtures"):
    if not f.startswith(("git-", "oauth-", "mcp-")):
        os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.endswith(".yaml") and f not in HAND:
        os.remove(D + f)

def wrap(text, indent="      "):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > 100 and line.strip():
            out.append(line)
            line = indent
        line += ("" if line.strip() == "" else " ") + w
    out.append(line)
    return out

def fill(path):
    return re.sub(r"\{([^}]+)\}", lambda m: sample(m.group(1), path), path)

def fixture(name, method, fpath, desc, body=None, query="", extra_headers=()):
    lines = [f"# description: {desc}", f"{method} /api/v4{fpath}{query} HTTP/1.1", f"Host: {HOST}",
             "PRIVATE-TOKEN: opf_gitlab_EXAMPLE"] + list(extra_headers)
    if body is not None:
        lines += ["Content-Type: application/json", "", json.dumps(body)]
    else:
        lines.append("")
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")

def describe(card, path):
    return re.sub(r"\{([^}]+)\}", lambda m: unescape(sample(m.group(1), path)) if not m.group(1).startswith("body.") else "…", card)

def cond_yaml(kind, arg, vals):
    if kind == "present":
        return f"{{ arg: {arg}, present: true }}"
    return f"{{ arg: {arg}, in: {json.dumps(vals)} }}"

def cond_value(kind, vals):
    if kind == "present":
        return "example"
    return vals[0]

def set_arg(body, arg, value):
    cur = body
    parts = arg.split(".")
    for p in parts[:-1]:
        nxt = cur.get(p)
        if isinstance(nxt, list):
            nxt[0][parts[-1]] = value
            return
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value

LIST_GETS = {"/projects", "/users/{user_id}/projects", "/users/{user_id}/contributed_projects", "/users/{user_id}/starred_projects",
             "/projects/{id}/forks", "/groups/{id}/projects", "/groups/{id}/projects/shared", "/projects/{id}/triggers"}

def write_response(name, method, path, resp):
    """A recorded-style response holding every path the rule transforms."""
    if resp == RT:
        proj = {"id": 9, "path_with_namespace": "acme/shop", "visibility": "private", "runners_token": "GR1348941EXAMPLEtoken"}
        if path.startswith("/groups") and path in ("/groups", "/groups/{id}") or re.search(r"^/groups/\{id\}/(archive|unarchive|restore|projects/\{project_id\}|transfer_to_organization|share)$", path):
            v = {"id": 8, "full_path": "acme", "runners_token": "GR1348941EXAMPLEgroup", "projects": [proj], "shared_projects": []}
        else:
            v = proj
    elif resp == ["variables.value"]:
        v = {"id": 3, "description": "nightly", "ref": "main",
             "variables": [{"key": "DEPLOY_TOKEN", "value": "example-secret", "variable_type": "env_var"}]}
    elif resp == ["token"]:
        v = {"id": 10, "description": "deploy", "token": "glptt-EXAMPLEtriggertoken", "owner": {"username": "jdoe"}}
    else:
        raise AssertionError(resp)
    if method == "GET" and path in LIST_GETS:
        v = [v]
    open(D + "fixtures/" + name, "w").write(json.dumps(v, indent=2) + "\n")

# Literal last segments, where a .json suffix would otherwise miss the rule.
SUFFIX_TESTS = {("DELETE", "/projects/{id}/repository/merged_branches"), ("POST", "/projects/{id}/jobs/{job_id}/erase"),
                ("DELETE", "/projects/{id}/artifacts"), ("POST", "/projects/{id}/pipeline"),
                ("POST", "/projects/{id}/repository/commits"), ("DELETE", "/projects/{id}/terraform/state/{name}/lock")}

entries = []   # (group, method, path, op, dash, cls, note, is_get)
for method, path, op, dash in ops:
    if (method, path) in SKIP:
        continue
    if method in ("GET", "HEAD"):
        if path in CRED_GETS and method == "GET":
            entries.append((group_of((op.get("tags") or ["-"])[0]), method, path, op, dash, C, CRED_GETS[path][0], True))
        continue
    cls, note = classify(method, path, op)
    entries.append((group_of((op.get("tags") or ["-"])[0]), method, path, op, dash, cls, note, False))
assert all((m, p) in [(e[1], e[2]) for e in entries] for m, p in RT_WRITES), [x for x in RT_WRITES if x not in [(e[1], e[2]) for e in entries]]
assert all(k in [(e[1], e[2]) for e in entries] for k in COND), [k for k in COND if k not in [(e[1], e[2]) for e in entries]]
assert len(CRED_GETS) == sum(1 for e in entries if e[7]), "a credential GET is missing from the spec"

# Verbs: the summary, made unique within the group with the path's scope
# and then its distinguishing segments.
def scope_of(path):
    first = path.split("/")[1]
    return {"projects": "project", "groups": "group", "users": "user", "user": "user", "admin": "admin"}.get(first, "")

verb = {}
by = {}
for i, e in enumerate(entries):
    g, method, path, op = e[0], e[1], e[2], e[3]
    v = slug(op.get("summary") or op.get("operationId"))
    m = re.fullmatch(r"/(projects|groups)/\{id\}/(integrations|services)/([a-z0-9_-]+)(/trigger)?", path)
    if g == "integrations" and m:
        v = m.group(3).replace("_", "-") + ("-trigger" if m.group(4) else "-update")
        v = ("project-" if m.group(1) == "projects" else "group-") + v + ("-services" if m.group(2) == "services" else "")
    elif g == "integrations" and re.fullmatch(r"/(projects|groups)/\{id\}/(integrations|services)/\{slug\}", path):
        v = ("project-" if path.startswith("/projects") else "group-") + "disable" + ("-services" if "/services/" in path else "")
    verb[i] = v
    by.setdefault((g, v), []).append(i)
for (g, v), idx in list(by.items()):
    if len(idx) > 1:
        for i in idx:
            sc = scope_of(entries[i][2])
            verb[i] = (sc + "-" + v) if sc and not v.startswith(sc) else v
by = {}
for i in verb:
    by.setdefault((entries[i][0], verb[i]), []).append(i)
for (g, v), idx in list(by.items()):
    if len(idx) > 1:
        for i in idx:
            e = entries[i]
            tail = [s for s in e[2].split("/") if s and not s.startswith("{")][-2:]
            extra = slug("-".join(tail))
            if e[4]:
                extra += "-dash"
            verb[i] = v + "-" + extra if extra else v
by = {}
for i in verb:
    by.setdefault((entries[i][0], verb[i]), []).append(i)
for (g, v), idx in by.items():
    if len(idx) > 1:
        for n, i in enumerate(idx):
            if n:
                verb[i] = v + "-" + str(n + 1)
ids = {}
for i, v in verb.items():
    rid = f"gitlab.{entries[i][0]}.{v}"
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)+", rid), rid
    assert rid not in ids.values(), rid
    ids[i] = rid

files = {}
n_fixtures = 0
for i, e in enumerate(entries):
    g, method, path, op, dash, cls, note, is_get = e
    rid = ids[i]
    res = resource_of(path)
    card = GET_CARD[path] if is_get else card_of(method, path, op)
    resp = None
    rclass = None
    if is_get and CRED_GETS[path][1]:
        resp, rclass = CRED_GETS[path][1]
    if not is_get and (method, path) in RT_WRITES:
        resp, rclass = RT, cls
        note = ((note + " ") if note else "") + RT_NOTE.replace("the call stays credential", "the call stays credential, for its response")
        cls = C
    if not is_get and (method, path) in RESP_WRITES:
        resp, rnote = RESP_WRITES[(method, path)]
        rclass = cls
        note = ((note + " ") if note else "") + rnote
        cls = C
    conds, cnote = COND.get((method, path), ([], ""))
    L = files.setdefault(g, ["# GitLab REST API (gitlab.com/api/v4): " + (op.get("tags") or ["-"])[0] + ".",
                             "# Generated from GitLab's OpenAPI description (see provider.yaml); classes reviewed by hand.",
                             "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {method}, path: \"/api/v4{path}\" }} }}")
    L.append(f"    class: {cls}")
    if conds:
        L.append("    when:")
        for wc, (kind, arg, vals), _ in conds:
            for loc in ("body", "query"):
                L.append(f"      - if: {cond_yaml(kind, loc + '.' + arg, vals)}")
                L.append(f"        class: {wc}")
    if resp:
        L.append("    response:")
        L.append(f"      redact: {json.dumps(resp)}")
        L.append(f"      class: {rclass}")
    if res:
        L.append(f"    resource: {{ arg: {res[0]}, kind: {res[1]} }}")
    L.append(f"    card: {json.dumps(card)}")
    L += ["    status: verified", f"    verified: {DATE}", "    sources:", f"      - {SRC}"]
    if resp and (is_get or (method, path) in RT_WRITES):
        L.append(f"      - {ENT}")
    full = (note or "") + cnote
    if dash:
        full = (full + " " if full else "") + "Grape serves this route with and without /-/; this is the /-/ form."
    if op.get("deprecated"):
        full = (full + " " if full else "") + "GitLab has deprecated this endpoint."
    if full.strip():
        L.append("    notes: >-")
        L += wrap(full.strip())
    fpath = fill(path)
    base = rid.split(".", 1)[1].replace(".", "-")
    desc = describe(card, path)
    body = body_for(method, path)
    fixture(base + ".http", method, fpath, desc, body)
    n_fixtures += 1
    tests = [(base + ".http", cls, None)]
    if resp:
        rname = base + "-response.json"
        tests[0] = (base + ".http", cls, rname)
        write_response(rname, method, path, resp)
    for wc, (kind, arg, vals), label in conds:
        if not label:
            continue
        b = json.loads(json.dumps(body)) if body is not None else {}
        set_arg(b, arg, cond_value(kind, vals))
        name = f"{base}-{slug(label)}.http"
        if method in ("POST", "PUT", "PATCH"):
            fixture(name, method, fpath, desc + f" ({label})", b)
        else:
            q = "?" + arg + "=" + str(cond_value(kind, vals)).lower()
            fixture(name, method, fpath, desc + f" ({label})", None, q)
        n_fixtures += 1
        tests.append((name, wc, None))
    # A file named like a git endpoint is a REST call, not a fetch.
    if (method, path) == ("POST", "/projects/{id}/repository/files/{file_path}"):
        name = f"{base}-named-git-upload-pack.http"
        fixture(name, method, fpath.replace("config%2Fdeploy.yml", "git-upload-pack"), "Create file git-upload-pack on branch main of project acme/shop", body)
        n_fixtures += 1
        tests.append((name, cls, None))
    # Every family member: the format suffix reads the same rule.
    if (method, path) in SUFFIX_TESTS:
        name = f"{base}-format-suffix.http"
        fixture(name, method, fpath + ".json", desc + " (with a .json suffix)", body)
        n_fixtures += 1
        tests.append((name, cls, None))
    L.append("    tests:")
    for f, ex, rf in tests:
        L.append(f"      - fixture: fixtures/{f}")
        L.append(f"        expect: {ex}")
        if rf:
            L.append(f"        response: fixtures/{rf}")
        if res:
            L.append(f"        resource: {json.dumps(unescape(sample(res[0], path)))}")
    L.append("")

for g, L in files.items():
    open(D + g + ".yaml", "w").write("\n".join(L))
print(len(entries), "rules in", len(files), "files;", n_fixtures, "fixtures;",
      sum(1 for e in entries if e[7]), "credential GETs;", len(settings_secrets), "settings secrets;",
      len(access_levels), "access levels")
