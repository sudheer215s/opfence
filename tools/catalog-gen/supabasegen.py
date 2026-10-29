# Writes catalog/supabase (rules and fixtures) from the Supabase Management
# API's OpenAPI description. Run from the repo root:
#   python3 -I supabasegen.py <v1.json>
import json, os, re, sys

SPEC = json.load(open(sys.argv[1]))
D = "catalog/supabase/"
SRC = "https://api.supabase.com/api/v1-json"
HOST = "api.supabase.com"

# Reviewed class of every operation that is not a GET, and of the GETs that
# return secrets, by operationId, with a note where the class needs one.
# Other GETs are reads (the provider's rest_safe_methods default).
C = {
    # Branches. Kept in line with the supabase-mcp rules for the same calls.
    "v1-get-a-branch-config": ("credential", "Returns the branch database's password and JWT secret."),
    "v1-update-a-branch-config": ("write", None),
    "v1-delete-a-branch": ("delete", "Branch databases hold development data that can be rebuilt from migrations and seed files, and a deletion is scheduled and can be restored. Map a branch to production in your config if one holds data you cannot rebuild."),
    "v1-create-a-branch": ("money", "Branches are billed like small projects."),
    "v1-disable-preview-branching": ("delete", "Turns branching off and deletes every branch, as deleting each one would; see deleting a branch."),
    "v1-merge-a-branch": ("write", "Applies the branch's migrations and edge functions to the production project."),
    "v1-push-a-branch": ("write", "Applies the branch's migrations to its own database."),
    "v1-reset-a-branch": ("delete", "Discards the branch's data and untracked schema changes."),
    "v1-restore-a-branch": ("write", "Cancels a scheduled branch deletion."),
    # OAuth for apps built on the Management API.
    "v1-exchange-oauth-token": ("credential", "Returns access and refresh tokens."),
    "v1-revoke-token": ("access", "Revokes an app's access and its tokens."),
    # Organizations.
    "v1-create-an-organization": ("write", None),
    "v1-claim-project-for-organization": ("access", "Moves a project into the organization, which changes who controls it."),
    # Projects.
    "v1-create-a-project": ("money", "New projects are billed."),
    "v1-update-a-project": ("write", None),
    "v1-delete-a-project": ("irreversible", "Deletes the project with its database, storage, edge functions and backups."),
    "v1-pause-a-project": ("write", "Takes the project's database and APIs offline until restored."),
    "v1-restart-a-project": ("write", None),
    "v1-restore-a-project": ("write", "Brings a paused project back online."),
    "v1-cancel-a-project-restoration": ("write", None),
    "v1-upgrade-postgres-version": ("write", "Upgrades Postgres in place: the data stays, but the upgrade cannot be rolled back and the project is offline while it runs."),
    "v1-disable-readonly-mode-temporarily": ("write", "Supabase turns read-only mode on when the disk is nearly full; this allows writes again for 15 minutes so space can be freed."),
    "v1-setup-a-read-replica": ("money", "Read replicas are billed."),
    "v1-remove-a-read-replica": ("delete", "A replica is a copy of the primary database and can be set up again."),
    "v1-modify-database-disk": ("money", "A larger or faster disk is billed."),
    "v1-apply-project-addon": ("money", None),
    "v1-remove-project-addon": ("money", None),
    "v1-update-action-run-status": ("write", None),
    # API keys and claim tokens.
    "v1-get-project-api-keys": ("credential", "Returns the legacy anon and service_role keys in full, and secret keys with reveal."),
    "v1-get-project-api-key": ("credential", "Returns the key, in full for legacy keys and for secret keys with reveal."),
    "v1-create-project-api-key": ("credential", "Returns the new key."),
    "v1-update-project-api-key": ("credential", "Returns the key."),
    "v1-delete-project-api-key": ("access", "Apps using the key stop working."),
    "v1-update-project-legacy-api-keys": ("access", "Turns the JWT-based anon and service_role keys off or back on."),
    "v1-create-project-claim-token": ("credential", "Returns a token that lets an organization claim the project."),
    "v1-delete-project-claim-token": ("access", None),
    "v1-create-login-role": ("credential", "Creates a Postgres login role for the CLI and returns its password."),
    "v1-delete-login-roles": ("access", None),
    "v1-update-database-password": ("credential", "Sets the database password: apps connecting with the old one stop working."),
    # Auth: who can sign in and how.
    "v1-get-auth-service-config": ("credential", "Returns the SMTP password, OAuth providers' client secrets, SMS provider keys and auth hook secrets."),
    "v1-update-auth-service-config": ("access", "Auth settings decide who can sign up and sign in, and where users are sent."),
    "v1-create-project-signing-key": ("access", "Signing keys decide which JWTs the project accepts."),
    "v1-create-legacy-signing-key": ("access", "Signing keys decide which JWTs the project accepts."),
    "v1-update-project-signing-key": ("access", "Moving a key in or out of use changes which JWTs the project accepts; revoking one signs every user out."),
    "v1-remove-project-signing-key": ("access", None),
    "v1-create-a-sso-provider": ("access", None),
    "v1-update-a-sso-provider": ("access", None),
    "v1-delete-a-sso-provider": ("access", None),
    "v1-create-project-tpa-integration": ("access", "Lets users sign in with tokens from another auth provider."),
    "v1-delete-project-tpa-integration": ("access", None),
    # Database configuration.
    "v1-get-postgrest-service-config": ("credential", "Returns the project's JWT secret."),
    "v1-update-postgrest-service-config": ("access", "Decides which schemas the data API exposes."),
    "v1-update-postgres-config": ("write", None),
    "v1-update-pooler-config": ("write", None),
    "v1-get-pgsodium-config": ("credential", "Returns the pgsodium root key."),
    "v1-update-pgsodium-config": ("credential", "Sets the pgsodium root key: data encrypted with the old key, Vault secrets among it, can become unreadable."),
    "v1-update-ssl-enforcement-config": ("access", "Decides whether connections without SSL are accepted."),
    "v1-update-realtime-config": ("write", None),
    "v1-shutdown-realtime": ("write", "Drops every realtime connection."),
    "v1-update-storage-config": ("write", None),
    "v1-enable-database-webhook": ("write", None),
    # Backups and restores.
    "v1-restore-physical-backup": ("irreversible", "Replaces the database with the backup: everything written since is gone."),
    "v1-restore-pitr-backup": ("irreversible", "Replaces the database with its state at that time: everything written since is gone."),
    "v1-create-restore-point": ("write", None),
    "v1-undo": ("irreversible", "Returns the database to a restore point: everything written since is gone."),
    "v1-update-backup-schedule": ("write", None),
    # Just-in-time database access.
    "v1-authorize-jit-access": ("access", None),
    "v1-update-jit-access": ("access", None),
    "v1-delete-jit-access": ("access", None),
    "v1-invite-external-jit-access": ("access", "Invites someone outside the organization to the database."),
    "v1-accept-invite-external-jit-access": ("access", None),
    "v1-delete-invite-external-jit-access": ("access", None),
    "v1-update-jit-access-config": ("access", None),
    # Migrations and SQL.
    "v1-run-a-query": ("unknown", "The class comes from the SQL, read as Postgres: SELECT is read, INSERT and UPDATE ... WHERE are write, DELETE ... WHERE is delete, DROP, TRUNCATE and UPDATE or DELETE without WHERE are irreversible, GRANT, REVOKE and role changes are access, reading Vault's decrypted secrets is credential, and anything the classifier cannot read is unknown."),
    "v1-read-only-query": ("read", "Runs as supabase_read_only_user, so the database refuses writes; the SQL is still read, so reading Vault's decrypted secrets is credential."),
    "v1-apply-a-migration": ("unknown", "The class comes from the migration's SQL, as for running a query."),
    "v1-upsert-a-migration": ("write", "Records a migration in the history without running it."),
    "v1-patch-a-migration": ("write", "Changes a migration's entry in the history."),
    "v1-rollback-migrations": ("irreversible", "Runs the migrations' rollback SQL, which drops what they created, data included."),
    # Edge functions and their secrets.
    "v1-create-a-function": ("write", "Deploying code is a write."),
    "v1-deploy-a-function": ("write", "Deploying code is a write."),
    "v1-bulk-update-functions": ("write", None),
    "v1-update-a-function": ("write", "Deploying code is a write."),
    "v1-delete-a-function": ("delete", "A function can be deployed again from its source."),
    "v1-list-all-secrets": ("credential", "Returns the edge function secrets' values."),
    "v1-bulk-create-secrets": ("credential", "Setting a secret-store value is credential."),
    "v1-bulk-delete-secrets": ("irreversible", "A deleted secret's value cannot be read back to restore it."),
    # Network.
    "v1-list-all-network-bans": ("read", None),
    "v1-list-all-network-bans-enriched": ("read", None),
    "v1-delete-network-bans": ("access", "Lets banned IP addresses connect to the database again."),
    "v1-update-network-restrictions": ("access", "Decides which IP addresses can reach the database."),
    "v1-patch-network-restrictions": ("access", "Decides which IP addresses can reach the database."),
    # Domains.
    "v1-update-hostname-config": ("write", None),
    "v1-verify-dns-config": ("read", "Checks the custom hostname's DNS records."),
    "v1-activate-custom-hostname": ("write", None),
    "v1-Delete hostname config": ("delete", None),
    "v1-check-vanity-subdomain-availability": ("read", None),
    "v1-activate-vanity-subdomain-config": ("write", None),
    "v1-deactivate-vanity-subdomain-config": ("delete", None),
}

# Conditions that make a call stricter: (class, condition) lists.
NOT_FALSE = r"^(?is:[^0f].*|0.+|f[^a].*|fa|fa[^l].*|fal|fal[^s].*|fals|fals[^e].*|false.+)$"
AUTH_SECRET = re.compile(r"(_secret|_secrets|_api_key|_api_secret|_access_key|_auth_token)$|^smtp_pass$")
auth_body = SPEC["components"]["schemas"]["UpdateAuthConfigBody"]["properties"]
AUTH_SECRETS = sorted(k for k in auth_body if AUTH_SECRET.search(k))
W = {
    "v1-update-auth-service-config": [("credential", f"{{ arg: body.{k}, present: true }}") for k in AUTH_SECRETS],
    "v1-update-realtime-config": [("access", "{ arg: body.private_only, present: true }")],
    "v1-update-a-function": [("access", "{ arg: query.verify_jwt, equals: \"false\" }")],
    "v1-create-a-function": [("access", "{ arg: query.verify_jwt, equals: \"false\" }")],
    "v1-remove-project-addon": [("irreversible", "{ arg: addon_variant, matches: \"^pitr\" }")],
}
WNOTES = {
    "v1-update-auth-service-config": " Setting one of its secrets (the SMTP password, an OAuth provider's client secret, an SMS provider's key, an auth hook's secrets) is credential.",
    "v1-update-realtime-config": " Changing private_only decides whether channels need an authorized user, so it is access.",
    "v1-update-a-function": " Turning verify_jwt off lets anyone on the internet call the function, so it is access.",
    "v1-create-a-function": " With verify_jwt off anyone on the internet can call the function, so it is access.",
    "v1-remove-project-addon": " Removing the point-in-time recovery add-on discards the recovery window, so it is irreversible.",
}
SQL = {"v1-run-a-query": "body.query", "v1-read-only-query": "body.query", "v1-apply-a-migration": "body.query"}
RES = {"ref": "project", "branch_id_or_ref": "branch", "slug": "organization"}
SAMPLE = {"ref": "abcdefghijklmnopqrst", "branch_id_or_ref": "qrstuvwxyzabcdefghij", "slug": "acme", "id": "8f4c2a10-5e6d-4b7a-9c8d-0e1f2a3b4c5d",
          "run_id": "run_01", "provider_id": "6a7b8c9d-0e1f-4a2b-8c3d-4e5f6a7b8c9d", "tpa_id": "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d",
          "function_slug": "send-email", "addon_variant": "ci_small", "invite_id": "inv_01", "user_id": "7c8d9e0f-1a2b-4c3d-8e4f-5a6b7c8d9e0f",
          "version": "20261022120000", "token": "claim_01", "name": "feature-x"}

# Cards, written by hand where the summary would not read well.
CARD = {
    "v1-delete-a-project": "Delete Supabase project {ref} with its database, storage and backups",
    "v1-delete-a-branch": "Delete database branch {branch_id_or_ref}",
    "v1-reset-a-branch": "Reset database branch {branch_id_or_ref}, discarding its data",
    "v1-merge-a-branch": "Merge database branch {branch_id_or_ref} into production",
    "v1-create-a-branch": "Create database branch {body.branch_name} of project {ref}",
    "v1-disable-preview-branching": "Turn off branching for project {ref}, deleting every branch",
    "v1-push-a-branch": "Push migrations to database branch {branch_id_or_ref}",
    "v1-restore-a-branch": "Cancel the deletion of database branch {branch_id_or_ref}",
    "v1-update-a-branch-config": "Change the settings of database branch {branch_id_or_ref}",
    "v1-get-a-branch-config": "Read database branch {branch_id_or_ref}'s password and JWT secret",
    "v1-run-a-query": "Run SQL on project {ref}",
    "v1-read-only-query": "Run read-only SQL on project {ref}",
    "v1-apply-a-migration": "Apply migration {body.name} to project {ref}",
    "v1-rollback-migrations": "Roll back migrations on project {ref}",
    "v1-restore-physical-backup": "Restore project {ref}'s database from a backup, losing later changes",
    "v1-restore-pitr-backup": "Restore project {ref}'s database to Unix time {body.recovery_time_target_unix}, losing later changes",
    "v1-undo": "Return project {ref}'s database to a restore point, losing later changes",
    "v1-get-project-api-keys": "Read project {ref}'s API keys",
    "v1-get-project-api-key": "Read API key {id} of project {ref}",
    "v1-create-project-api-key": "Create an API key for project {ref}",
    "v1-update-project-api-key": "Change API key {id} of project {ref}",
    "v1-delete-project-api-key": "Delete API key {id} of project {ref}",
    "v1-get-auth-service-config": "Read project {ref}'s auth settings, with their secrets",
    "v1-update-auth-service-config": "Change project {ref}'s auth settings",
    "v1-get-postgrest-service-config": "Read project {ref}'s data API settings and JWT secret",
    "v1-get-pgsodium-config": "Read project {ref}'s pgsodium root key",
    "v1-update-pgsodium-config": "Set project {ref}'s pgsodium root key",
    "v1-list-all-secrets": "Read project {ref}'s edge function secrets",
    "v1-bulk-create-secrets": "Set edge function secrets on project {ref}",
    "v1-bulk-delete-secrets": "Delete edge function secrets {body} from project {ref}",
    "v1-update-database-password": "Change project {ref}'s database password",
    "v1-create-a-project": "Create Supabase project {body.name}",
    "v1-pause-a-project": "Pause project {ref}",
    "v1-restore-a-project": "Restore paused project {ref}",
    "v1-remove-project-addon": "Remove add-on {addon_variant} from project {ref}",
    "v1-apply-project-addon": "Apply add-on {body.addon_variant} to project {ref}",
    "v1-update-a-function": "Update edge function {function_slug} of project {ref}",
    "v1-delete-a-function": "Delete edge function {function_slug} of project {ref}",
    "v1-deploy-a-function": "Deploy edge function {query.slug} to project {ref}",
    "v1-update-realtime-config": "Change project {ref}'s realtime settings",
    "v1-update-project-legacy-api-keys": "Turn project {ref}'s legacy anon and service_role keys on or off",
    "v1-create-legacy-signing-key": "Use project {ref}'s JWT secret as a signing key",
    "v1-create-project-signing-key": "Create a standby signing key for project {ref}",
    "v1-remove-project-signing-key": "Remove signing key {id} from project {ref}",
    "v1-update-project-signing-key": "Change signing key {id} of project {ref}",
    "v1-create-project-tpa-integration": "Add a third-party auth integration to project {ref}",
    "v1-delete-project-tpa-integration": "Remove third-party auth integration {tpa_id} from project {ref}",
    "v1-create-a-sso-provider": "Add an SSO provider to project {ref}",
    "v1-update-a-sso-provider": "Change SSO provider {provider_id} of project {ref}",
    "v1-delete-a-sso-provider": "Remove SSO provider {provider_id} from project {ref}",
    "v1-create-project-claim-token": "Create a claim token for project {ref}",
    "v1-delete-project-claim-token": "Revoke project {ref}'s claim token",
    "v1-create-login-role": "Create a temporary CLI login role on project {ref}",
    "v1-delete-login-roles": "Delete project {ref}'s CLI login roles",
    "v1-update-postgrest-service-config": "Change project {ref}'s data API settings",
    "v1-update-ssl-enforcement-config": "Change project {ref}'s SSL enforcement",
    "v1-update-pooler-config": "Change project {ref}'s connection pooler settings",
    "v1-update-postgres-config": "Change project {ref}'s Postgres settings",
    "v1-update-jit-access-config": "Change project {ref}'s temporary database access settings",
    "v1-upsert-a-migration": "Record migration {body.name} in project {ref}'s history without running it",
    "v1-patch-a-migration": "Change migration {version} in project {ref}'s history",
    "v1-enable-database-webhook": "Turn on database webhooks for project {ref}",
    "v1-authorize-jit-access": "Grant temporary database access on project {ref}",
    "v1-update-jit-access": "Change temporary database access on project {ref}",
    "v1-invite-external-jit-access": "Invite someone outside the organization to project {ref}'s database",
    "v1-accept-invite-external-jit-access": "Accept an invitation to project {ref}'s database",
    "v1-delete-invite-external-jit-access": "Delete database invitation {invite_id} on project {ref}",
    "v1-delete-jit-access": "Remove temporary database access of user {user_id} on project {ref}",
    "v1-create-restore-point": "Create a restore point for project {ref}'s database",
    "v1-update-backup-schedule": "Change project {ref}'s backup schedule",
    "v1-modify-database-disk": "Change project {ref}'s database disk",
    "v1-Delete hostname config": "Remove project {ref}'s custom hostname",
    "v1-update-hostname-config": "Set up a custom hostname for project {ref}",
    "v1-activate-custom-hostname": "Switch project {ref} to its custom hostname",
    "v1-deactivate-vanity-subdomain-config": "Remove project {ref}'s vanity subdomain",
    "v1-activate-vanity-subdomain-config": "Activate a vanity subdomain for project {ref}",
    "v1-create-a-function": "Create edge function {query.slug} in project {ref}",
    "v1-bulk-update-functions": "Update project {ref}'s edge functions",
    "v1-delete-network-bans": "Unban IP addresses on project {ref}",
    "v1-patch-network-restrictions": "Change which IP addresses can reach project {ref}'s database",
    "v1-update-network-restrictions": "Change which IP addresses can reach project {ref}'s database",
    "v1-exchange-oauth-token": "Exchange an OAuth code or refresh token for Supabase tokens",
    "v1-revoke-token": "Revoke an OAuth app's access and tokens",
    "v1-create-an-organization": "Create organization {body.name}",
    "v1-claim-project-for-organization": "Move a claimed project into organization {slug}",
    "v1-update-action-run-status": "Change the status of action run {run_id} on project {ref}",
    "v1-update-a-project": "Update project {ref}",
    "v1-upgrade-postgres-version": "Upgrade project {ref}'s Postgres version",
    "v1-disable-readonly-mode-temporarily": "Allow writes on read-only project {ref} for 15 minutes",
    "v1-setup-a-read-replica": "Set up a read replica of project {ref}",
    "v1-remove-a-read-replica": "Remove a read replica of project {ref}",
    "v1-cancel-a-project-restoration": "Cancel restoring project {ref}",
    "v1-restart-a-project": "Restart project {ref}",
    "v1-shutdown-realtime": "Drop every realtime connection to project {ref}",
    "v1-update-storage-config": "Change project {ref}'s storage settings",
}

VERBS = {"Deletes": "Delete", "Gets": "Get", "Updates": "Update", "Creates": "Create", "Lists": "List", "Removes": "Remove",
         "Restores": "Restore", "Pauses": "Pause", "Restarts": "Restart", "Upgrades": "Upgrade", "Activates": "Activate",
         "Checks": "Check", "Initiates": "Initiate", "Disables": "Disable", "Enables": "Enable", "Revokes": "Revoke",
         "Shutdowns": "Shut down", "Invites": "Invite", "Accepts": "Accept", "Authorizes": "Authorize", "Claims": "Claim",
         "Attempts": "Attempt", "Applies": "Apply", "Sets": "Set", "Exchanges": "Exchange", "Cancels": "Cancel", "Fetches": "Fetch",
         "Returns": "Return", "Pushes": "Push", "Merges": "Merge", "Resets": "Reset"}

def card_of(opid, summary, params):
    if opid in CARD:
        return CARD[opid]
    s = summary.strip().rstrip(".")
    first, _, rest = s.partition(" ")
    s = VERBS.get(first, first) + (" " + rest if rest else "")
    s = s.replace("the given project", "project {ref}").replace("project's", "project {ref}'s") if "ref" in params else s
    s = s[0].upper() + s[1:]
    target = [p for p in params if p not in ("ref",)]
    if target and "{" + target[-1] + "}" not in s:
        s += " {" + target[-1] + "}"
    if "ref" in params and "{ref}" not in s:
        s += " in project {ref}"
    return s

def group_of(path):
    parts = [p for p in path.split("/") if p][1:]  # drop v1
    if parts[0] != "projects" or len(parts) < 3:
        return {"oauth": "oauth", "organizations": "organizations", "branches": "branches", "snippets": "snippets",
                "projects": "projects", "profile": "organizations"}[parts[0]]
    seg = parts[2]
    if seg == "config":
        sub = parts[3]
        return {"auth": "auth", "database": "database-config", "disk": "disk", "realtime": "realtime", "storage": "storage"}[sub]
    return {"database": "database", "api-keys": "api-keys", "claim-token": "api-keys", "cli": "api-keys", "functions": "functions",
            "secrets": "functions", "network-bans": "network", "network-restrictions": "network", "ssl-enforcement": "database-config",
            "postgrest": "database-config", "pgsodium": "database-config", "custom-hostname": "domains", "vanity-subdomain": "domains",
            "billing": "projects", "read-replicas": "projects", "readonly": "projects", "restore": "projects", "upgrade": "projects",
            "pause": "projects", "restart": "projects", "branches": "branches", "jit-access": "database", "actions": "projects",
            "advisors": "projects", "analytics": "projects", "health": "projects", "types": "projects", "storage": "storage"}[seg]

def verb_of(opid):
    v = re.sub(r"^v1-", "", opid).lower().replace(" ", "-")
    v = re.sub(r"-(a|an|the|all|given)-", "-", "-" + v + "-").strip("-")
    return v

ops = []
for path, item in SPEC["paths"].items():
    for method, op in item.items():
        if method in ("get", "post", "put", "patch", "delete"):
            ops.append((method.upper(), path, op))

missing = [op["operationId"] for m, p, op in ops if m != "GET" and op["operationId"] not in C]
assert not missing, missing
extra = set(C) - {op["operationId"] for m, p, op in ops}
assert not extra, extra

def template_re(path):
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(path)) + "$")

# A GET left to the default can still match a credential GET rule whose
# template has a parameter where it has a literal (api-keys/legacy and
# api-keys/{id}); the more specific rule wins only if there is one.
cred_gets = [(p, template_re(p)) for m, p, op in ops if m == "GET" and C.get(op["operationId"], ("read",))[0] != "read"]
for m, p, op in ops:
    if m == "GET" and op["operationId"] not in C and any(r.match(p) and cp != p for cp, r in cred_gets):
        C[op["operationId"]] = ("read", "Listed so the credential rule beside it does not match this path.")

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.endswith(".yaml") and f != "provider.yaml":
        os.remove(D + f)

def wrap(text, indent="      "):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > 100 and line.strip():
            out.append(line); line = indent
        line += ("" if line.strip() == "" else " ") + w
    out.append(line)
    return out

def body_for(opid, variant=None):
    b = {
        "v1-run-a-query": {"query": "select id, email from auth.users limit 10"},
        "v1-read-only-query": {"query": "select count(*) from orders"},
        "v1-apply-a-migration": {"name": "add_orders_status", "query": "alter table orders add column status text"},
        "v1-update-auth-service-config": {"site_url": "https://app.example.com"},
        "v1-update-realtime-config": {"max_concurrent_users": 500},
        "v1-bulk-create-secrets": [{"name": "OPENAI_API_KEY", "value": "sk-example"}],
        "v1-bulk-delete-secrets": ["OPENAI_API_KEY"],
        "v1-create-a-project": {"name": "shop", "organization_slug": "acme", "region": "us-east-1", "db_pass": "example-password"},
        "v1-apply-project-addon": {"addon_type": "compute_instance", "addon_variant": "ci_small"},
        "v1-restore-pitr-backup": {"recovery_time_target_unix": 1760000000},
        "v1-update-database-password": {"password": "example-password"},
        "v1-update-pgsodium-config": {"root_key": "0" * 64},
        "v1-create-a-branch": {"branch_name": "feature-x"},
    }.get(opid, {})
    if variant:
        b = variant
    return b

def fixture(name, method, fpath, desc, body=None, query=""):
    lines = [f"# description: {desc}", f"{method} {fpath}{query} HTTP/1.1", f"Host: {HOST}"]
    if not name.startswith("oauth-exchange"):
        lines.append("Authorization: Bearer opf_supabase_EXAMPLE")
    if method in ("POST", "PUT", "PATCH"):
        lines += ["Content-Type: application/json", "", json.dumps(body if body is not None else {})]
    elif method == "DELETE" and body is not None:
        lines += ["Content-Type: application/json", "", json.dumps(body)]
    else:
        lines.append("")
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")

files, ids, n = {}, set(), 0
for method, path, op in ops:
    opid = op["operationId"]
    if method == "GET" and opid not in C:
        continue
    cls, note = C[opid]
    g = group_of(path)
    rid = f"supabase.{g}.{verb_of(opid)}"
    assert rid not in ids, rid
    ids.add(rid)
    params = re.findall(r"\{([^}]+)\}", path)
    res = next((p for p in ("branch_id_or_ref", "ref", "slug") if p in params), None)
    card = card_of(opid, op.get("summary", opid), params)
    L = files.setdefault(g, ["# Supabase Management API (api.supabase.com): " + g.replace("-", " ") + ".",
                             "# Generated from the published OpenAPI description (see provider.yaml); classes reviewed by hand.",
                             "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {method}, path: \"{path}\" }} }}")
    L.append(f"    class: {cls}")
    if W.get(opid):
        L.append("    when:")
        for wc, cond in W[opid]:
            L.append(f"      - if: {cond}")
            L.append(f"        class: {wc}")
    if opid in SQL:
        L.append(f"    classify: {{ sql: {SQL[opid]} }}")
    if res:
        L.append(f"    resource: {{ arg: {res}, kind: {RES[res]} }}")
    if cls != "read" or opid in SQL:
        L.append(f"    card: {json.dumps(card)}")
    L += ["    status: verified", "    verified: 2026-10-23", "    sources:", f"      - {SRC}"]
    notes = (note or "") + WNOTES.get(opid, "")
    if op.get("deprecated"):
        notes = (notes + " " if notes else "") + "Supabase has deprecated this endpoint."
    if notes.strip():
        L.append("    notes: >-")
        L += wrap(notes.strip())
    fpath = re.sub(r"\{([^}]+)\}", lambda m: SAMPLE[m.group(1)], path)
    base = f"{g}-{verb_of(opid)}"
    desc = re.sub(r"\{([^}]+)\}", lambda m: SAMPLE.get(m.group(1), m.group(1)), card)
    query = "?slug=send-email" if opid == "v1-deploy-a-function" else ""
    fixture(base + ".http", method, fpath, desc, body_for(opid), query)
    tests = [(base + ".http", cls)]
    # Fixtures for each condition, and for SQL.
    if opid == "v1-update-auth-service-config":
        fixture(base + "-smtp-pass.http", method, fpath, desc + ", setting the SMTP password", {"smtp_pass": "example-password"})
        fixture(base + "-github-secret.http", method, fpath, desc + ", setting GitHub's client secret", {"external_github_enabled": True, "external_github_secret": "example"})
        tests += [(base + "-smtp-pass.http", "credential"), (base + "-github-secret.http", "credential")]
    if opid == "v1-update-realtime-config":
        fixture(base + "-private-only.http", method, fpath, desc + ", making channels public", {"private_only": False})
        tests.append((base + "-private-only.http", "access"))
    if opid in ("v1-update-a-function", "v1-create-a-function"):
        fixture(base + "-no-jwt.http", method, fpath, desc + " without JWT verification", {}, "?verify_jwt=false")
        tests.append((base + "-no-jwt.http", "access"))
    if opid == "v1-remove-project-addon":
        pitr = fpath.replace("ci_small", "pitr_7")
        fixture(base + "-pitr.http", method, pitr, desc.replace("ci_small", "pitr_7"))
        tests.append((base + "-pitr.http", "irreversible"))
    if opid == "v1-run-a-query":
        tests[0] = (base + ".http", "read")
        fixture(base + "-delete-all.http", method, fpath, desc + ": delete every order", {"query": "/* tidy up */ delete from orders"})
        fixture(base + "-vault.http", method, fpath, desc + ": read Vault's secrets", {"query": "select name, decrypted_secret from vault.decrypted_secrets"})
        fixture(base + "-grant.http", method, fpath, desc + ": grant access", {"query": "grant all on orders to anon"})
        tests += [(base + "-delete-all.http", "irreversible"), (base + "-vault.http", "credential"), (base + "-grant.http", "access")]
    if opid == "v1-read-only-query":
        fixture(base + "-vault.http", method, fpath, desc + ": read Vault's secrets", {"query": "select decrypted_secret from vault.decrypted_secrets"})
        tests.append((base + "-vault.http", "credential"))
    if opid == "v1-apply-a-migration":
        tests[0] = (base + ".http", "write")
        fixture(base + "-drop.http", method, fpath, desc + ", dropping a table", {"name": "drop_orders", "query": "drop table orders"})
        tests.append((base + "-drop.http", "irreversible"))
    L.append("    tests:")
    for f, e in tests:
        L.append(f"      - fixture: fixtures/{f}")
        L.append(f"        expect: {e}")
        if res:
            L.append(f"        resource: \"{SAMPLE[res]}\"")
    L.append("")
    n += 1

for g, L in files.items():
    open(D + g + ".yaml", "w").write("\n".join(L))
print(n, "rules in", len(files), "files;", sum(1 for m, p, o in ops if m == "GET" and o["operationId"] not in C), "GETs left to the default;",
      len(AUTH_SECRETS), "auth secret fields")
