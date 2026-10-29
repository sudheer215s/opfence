# Writes catalog/atlas-app-services from the App Services Admin API v3 spec.
# Run from the repo root: python3 -I appservicesgen.py <openapi-admin-v3.yaml>
import json, os, re, sys
import yaml

SPEC = yaml.safe_load(open(sys.argv[1]))
D = "catalog/atlas-app-services/"
SRC = "https://github.com/mongodb/docs/blob/main/content/app-services/source/openapi-admin-v3.yaml"
BASE = "/api/admin/v3.0"

# Reviewed class of every operation that is not a GET, by operationId, with
# a note where the class needs one. GETs are reads (provider default) unless
# listed here too.
C = {
    # Admin sessions.
    "adminLogin": ("credential", "Exchanges an Atlas API key pair for Admin API access and refresh tokens."),
    "adminCreateSession": ("credential", "Exchanges a refresh token for a new access token."),
    "adminDeleteSession": ("write", None),
    # Apps.
    "adminCreateApplication": ("write", None),
    "adminDeleteApplication": ("irreversible", "Deletes the app with its functions, triggers, values, secrets, users and rules."),
    # Triggers and functions: code that runs with the app's system access.
    "adminCreateTrigger": ("write", "A trigger runs a function on database events or a schedule; deploying code is a write."),
    "adminUpdateTrigger": ("write", None),
    "adminDeleteTrigger": ("delete", "The trigger's configuration can be created again; events it would have handled are not replayed."),
    "adminResumeTrigger": ("write", None),
    "adminCreateFunction": ("write", "Deploying code is a write."),
    "adminUpdateFunction": ("write", "Deploying code is a write."),
    "adminDeleteFunction": ("delete", None),
    "adminExecuteFunction": ("irreversible", "Runs a function now, as a user or the system user, which can read and change any linked data."),
    "adminExecuteFunctionSource": ("irreversible", "Runs arbitrary source code in the app, which can read and change any linked data."),
    # Values, environment values and secrets.
    "adminCreateValue": ("write", None),
    "adminUpdateValue": ("write", None),
    "adminDeleteValue": ("irreversible", "Deleting any variable is irreversible: its value cannot be read back to restore it."),
    "adminCreateEnvironmentValue": ("write", None),
    "adminModifyEnvironmentValue": ("write", None),
    "adminDeleteEnvironmentValue": ("irreversible", "Deleting any variable is irreversible: its value cannot be read back to restore it."),
    "adminSetEnvironment": ("write", "Switches which environment's values the app uses."),
    "adminCreateASecret": ("credential", "Setting a secret-store value is credential."),
    "adminModifyASecret": ("credential", "Setting a secret-store value is credential."),
    "adminDeleteSecret": ("irreversible", "A deleted secret's value cannot be read back to restore it."),
    # Data sources, services and data access rules.
    "adminLinkMultiDataSources": ("access", "Linking a cluster gives the app, and through its rules the app's users, access to its data."),
    "adminCreateService": ("access", "Linking a cluster or a third-party service gives the app access to it."),
    "adminUpdateService": ("access", "Can change what the service connects to."),
    "adminDeleteService": ("delete", "Unlinks the data source or service; its data stays where it is."),
    "adminUpdateServiceConfig": ("access", "Can change the linked cluster or turn on the wire protocol, which lets app users connect with MongoDB drivers."),
    "adminValidateDocuments": ("read", "Samples documents and checks them against a schema."),
    "adminGenerateSchema": ("read", "Samples documents to propose a schema."),
    "adminRunCommand": ("unknown", "Runs a named service command; the API does not list the commands or what they do."),
    "adminCreateRule": ("access", "Data access rules decide which app users can read and write which documents."),
    "adminUpdateRule": ("access", "Data access rules decide which app users can read and write which documents."),
    "adminDeleteRule": ("access", "Removing a rule changes which app users can reach the collection."),
    "adminCreateDefaultRule": ("access", "Default rules apply to every collection without a rule of its own."),
    "adminUpdateDefaultRule": ("access", "Default rules apply to every collection without a rule of its own."),
    "adminDeleteDefaultRule": ("access", "Default rules apply to every collection without a rule of its own."),
    # Webhooks, HTTPS endpoints, Data API, GraphQL, hosting: public surfaces.
    "adminCreateWebhook": ("access", "A webhook is a public URL that runs a function: exposing to the internet is access."),
    "adminUpdateWebhook": ("access", "A webhook is a public URL that runs a function: exposing to the internet is access."),
    "adminDeleteWebhook": ("delete", None),
    "adminCreateEndpoint": ("access", "An HTTPS endpoint is a public URL that runs a function: exposing to the internet is access."),
    "adminModifyEndpoint": ("access", "An HTTPS endpoint is a public URL that runs a function: exposing to the internet is access."),
    "adminDeleteEndpoint": ("delete", None),
    "adminCreateDataApiConfig": ("access", "Turns on the Data API, which serves the linked data over HTTPS."),
    "adminModifyDataApiConfig": ("access", "Changes who can reach linked data over the Data API."),
    "adminRunGraphQLOperation": ("irreversible", "Runs a GraphQL query or mutation as the system user, past authentication and data access rules; a mutation can delete documents."),
    "adminUpdateGraphQLConfig": ("write", None),
    "adminCreateCustomResolver": ("write", None),
    "adminModifyCustomResolver": ("write", None),
    "adminDeleteCustomResolver": ("delete", None),
    "adminSetGraphQLValidationSettings": ("write", None),
    "adminSetNullTypeSchemaValidationSetting": ("write", None),
    "adminEnableDisableHosting": ("access", "Static hosting serves the app's assets on a public URL."),
    "adminMoveCopyHostedAsset": ("write", None),
    "adminUploadHostedAsset": ("write", None),
    "adminUpdateHostedAsset": ("write", None),
    # Push notifications.
    "adminCreateNotification": ("write", None),
    "adminUpdateMessage": ("write", None),
    "adminSetMessageType": ("write", None),
    "adminDeleteMessage": ("delete", None),
    "adminSendMessage": ("write", "Sends the notification to the app's users' devices."),
    # App configuration and deployment.
    "adminPushAppConfiguration": ("irreversible", "Overwrites the entire app configuration: whatever the new one leaves out, values and rules included, is gone."),
    "adminConfigureDeployment": ("write", "Can point automatic deployment at another repository and branch."),
    "adminRedeployDeployment": ("write", None),
    "adminCreateDeploymentDraft": ("write", None),
    "adminDiscardDraft": ("delete", None),
    "adminDeployDraft": ("write", "Each change in the draft was decided when it was made."),
    "adminCreateDeploymentMigration": ("write", None),
    "adminSetCustomUserDataConfig": ("write", None),
    # App users.
    "adminCreateUser": ("access", "A new email/password user who can sign in to the app."),
    "adminVerifyUserAccessToken": ("read", "Decodes a user's access token."),
    "adminDeleteUser": ("irreversible", "A deleted app user, and their identities, cannot be restored; signing up again makes a new user."),
    "adminResetUserEmail": ("access", "Changes the email a user signs in with."),
    "adminUserLogout": ("access", "Revokes the user's sessions."),
    "adminEnableUser": ("access", None),
    "adminDisableUser": ("access", None),
    "adminDeletePendingEmailPasswordUser": ("delete", None),
    "adminSendConfirmationEmail": ("write", None),
    "adminConfirmPendingUser": ("access", "Confirms a pending user, who can then sign in."),
    "adminRerunPendingUserConfirmation": ("write", None),
    # Authentication providers and API keys.
    "adminCreateAuthProvider": ("access", None),
    "adminUpdateAuthProvider": ("access", None),
    "adminDeleteAuthProvider": ("access", None),
    "adminEnableAuthProvider": ("access", None),
    "adminDisableAuthProvider": ("access", None),
    "adminCreateApiKey": ("credential", "Returns the new API key, which signs in as an app user."),
    "adminDeleteApiKey": ("access", None),
    "adminEnableApiKey": ("access", None),
    "adminDisableApiKey": ("access", None),
    # Network and session security.
    "adminSetAllowedRequestOrigins": ("access", None),
    "allowedIPAccessListCreate": ("access", None),
    "allowedIPAccessListUpdate": ("access", None),
    "allowedIPAccessListDelete": ("access", None),
    "adminCreatePrivateEndpoint": ("access", None),
    "adminUpdatePrivateEndpoint": ("access", None),
    "adminDeletePrivateEndpoint": ("access", None),
    "allowNonVpcClientRequests": ("access", "Lets clients outside the VPC reach the app."),
    "adminSetRefreshTokenExpiration": ("access", "Sets how long user sessions last."),
    # Logs.
    "createLogForwarder": ("access", "Sends the app's logs to another service."),
    "updateLogForwarder": ("access", "Can change where the app's logs go."),
    "deleteGwarder": ("delete", None),
    "enableLogForwarder": ("access", "Sends the app's logs to another service."),
    "disableLogForwarder": ("write", None),
    # Schemas.
    "adminCreateSchema": ("write", None),
    "adminUpdateSchema": ("write", None),
    "adminDeleteSchema": ("delete", None),
}

RES = {"appId": "app", "groupId": "project"}
SAMPLE = {"groupId": "5f4d3c2b1a09f8e7d6c5b4a3", "appId": "64b0c1d2e3f4a5b6c7d8e9f0", "triggerId": "64b0c1d2e3f4a5b6c7d8e901",
          "valueId": "64b0c1d2e3f4a5b6c7d8e902", "serviceId": "64b0c1d2e3f4a5b6c7d8e903", "datasourceId": "64b0c1d2e3f4a5b6c7d8e903",
          "commandName": "list_collections", "ruleId": "64b0c1d2e3f4a5b6c7d8e904", "incomingWebhookId": "64b0c1d2e3f4a5b6c7d8e905",
          "messageId": "64b0c1d2e3f4a5b6c7d8e906", "userId": "64b0c1d2e3f4a5b6c7d8e907", "email": "ada@example.com",
          "providerId": "64b0c1d2e3f4a5b6c7d8e908", "ipId": "64b0c1d2e3f4a5b6c7d8e909", "privateEndpointId": "64b0c1d2e3f4a5b6c7d8e90a",
          "forwarderId": "64b0c1d2e3f4a5b6c7d8e90b", "apiKeyId": "64b0c1d2e3f4a5b6c7d8e90c", "secretId": "64b0c1d2e3f4a5b6c7d8e90d",
          "functionId": "64b0c1d2e3f4a5b6c7d8e90e", "deploymentId": "64b0c1d2e3f4a5b6c7d8e90f", "draftId": "64b0c1d2e3f4a5b6c7d8e910",
          "environmentValueId": "64b0c1d2e3f4a5b6c7d8e911", "schemaId": "64b0c1d2e3f4a5b6c7d8e912", "endpointId": "64b0c1d2e3f4a5b6c7d8e913",
          "customResolverId": "64b0c1d2e3f4a5b6c7d8e914", "eventSubscriptionId": "64b0c1d2e3f4a5b6c7d8e915"}

# Rule file and resource name for each operation, from its first path segment
# after /groups/{groupId}/apps/{appId}.
def group_of(path):
    m = re.match(r"^/groups/\{groupId\}/apps/\{appId\}/([^/{]+)(?:/(?:\{[^}]+\}/)?([^/{]+))?", path)
    if path.startswith("/auth"):
        return "session"
    if m:
        first, second = m.group(1), m.group(2)
        g = {"service": "services", "user_registrations": "users", "custom_user_data": "users", "debug": "functions",
             "environment": "environment_values", "deploy": "deployments", "drafts": "deployments", "deployment_migration": "deployments",
             "pull": "config", "push": "push", "export": "config", "validation_settings": "graphql", "data_api": "endpoints",
             "multi_data_sources": "services", "event_subscriptions": "triggers", "dependencies": "functions",
             "measurements": "apps", "logs": "logs", "log_forwarders": "logs", "metrics": "logs", "sync": "services",
             "security": "security", "api_keys": "auth", "auth_providers": "auth"}.get(first, first)
        if first == "push" and second == "notifications" or first == "push" and path.endswith("/notifications"):
            g = "push"
        elif first == "push":
            g = "config"
        if first == "services" and second in ("rules", "default_rule"):
            g = "rules"
        if first == "services" and second == "incoming_webhooks":
            g = "webhooks"
        return g.replace("_", "-")
    return "apps"

def verb_of(opid):
    v = re.sub(r"^admin|^allowedIP", "", opid)
    v = re.sub(r"(?<!^)([A-Z])", r"-\1", v).lower()
    return v.replace("--", "-").strip("-")

ops = []
for path, item in SPEC["paths"].items():
    for method, op in item.items():
        if method not in ("get", "post", "put", "patch", "delete"):
            continue
        ops.append((method.upper(), path, op))

missing = [op["operationId"] for m, p, op in ops if m != "GET" and op["operationId"] not in C]
assert not missing, missing
extra = set(C) - {op["operationId"] for m, p, op in ops}
assert not extra, extra

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.endswith(".yaml") and f != "provider.yaml":
        os.remove(D + f)

files = {}
ids = set()
n = 0
for method, path, op in ops:
    opid = op["operationId"]
    if method == "GET" and opid not in C:
        continue  # the provider's rest_safe_methods default
    cls, note = C[opid]
    g = group_of(path)
    rid = f"atlas-app-services.{g}.{verb_of(opid)}"
    assert rid not in ids, rid
    ids.add(rid)
    params = re.findall(r"\{([^}]+)\}", path)
    res = "appId" if "appId" in params else ("groupId" if "groupId" in params else None)
    summary = op.get("summary", opid).rstrip(".")
    target = [p for p in params if p not in ("groupId", "appId")]
    card = summary
    if target:
        card += " {" + target[-1] + "}"
    if "appId" in params:
        card += " in app {appId}"
    elif "groupId" in params:
        card += " in project {groupId}"
    L = files.setdefault(g, ["# Atlas App Services Admin API v3: " + g.replace("-", " ") + ".",
                             "# Generated from the published OpenAPI file (see provider.yaml); classes reviewed by hand.",
                             "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {method}, path: \"{BASE}{path}\" }} }}")
    L.append(f"    class: {cls}")
    if res:
        L.append(f"    resource: {{ arg: {res}, kind: {RES[res]} }}")
    if cls != "read":
        L.append(f"    card: {json.dumps(card)}")
    L += ["    status: verified", "    verified: 2026-10-22", "    sources:", f"      - {SRC}"]
    notes = note
    if op.get("deprecated"):
        notes = ((notes + " ") if notes else "") + "MongoDB has deprecated this endpoint."
    if notes:
        L.append("    notes: >-")
        line = "      "
        for w in notes.split():
            if len(line) + len(w) + 1 > 100 and line.strip():
                L.append(line); line = "      "
            line += ("" if line.strip() == "" else " ") + w
        L.append(line)
    fpath = BASE + re.sub(r"\{([^}]+)\}", lambda m: SAMPLE[m.group(1)], path)
    name = f"{g}-{verb_of(opid)}.http"
    desc = re.sub(r"\{([^}]+)\}", lambda m: SAMPLE[m.group(1)], card)
    lines = [f"# description: {desc}", f"{method} {fpath} HTTP/1.1", "Host: services.cloud.mongodb.com"]
    if opid not in ("adminLogin",):
        lines.append("Authorization: Bearer opf_atlas-app-services_EXAMPLE")
    if method in ("POST", "PUT", "PATCH"):
        body = {"username": "abcdefgh", "apiKey": "00000000-0000-0000-0000-000000000000"} if opid == "adminLogin" else {}
        lines += ["Content-Type: application/json", "", json.dumps(body)]
    else:
        lines.append("")
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")
    L += ["    tests:", f"      - fixture: fixtures/{name}", f"        expect: {cls}"]
    if res:
        L.append(f"        resource: \"{SAMPLE[res]}\"")
    L.append("")
    n += 1
for g, L in files.items():
    open(D + g + ".yaml", "w").write("\n".join(L))
print(n, "rules in", len(files), "files;", sum(1 for m, p, o in ops if m == "GET"), "GETs left to the default")
