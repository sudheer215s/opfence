# Writes catalog/supabase-project (rules and fixtures). Run from the repo root:
#   python3 -I sbprojectgen.py
import json, os, re

D = "catalog/supabase-project/"
HOST = "abcdefghijklmnopqrst.supabase.co"
REF = "abcdefghijklmnopqrst"
PGRST = "https://docs.postgrest.org/en/v12/references/api/tables_views.html"
RPC = "https://docs.postgrest.org/en/v12/references/api/functions.html"
STORAGE = "https://github.com/supabase/storage/tree/master/src/http/routes"
AUTH = "https://github.com/supabase/auth/blob/master/internal/api/api.go"
FUNCS = "https://supabase.com/docs/guides/functions"
REALTIME = "https://supabase.com/docs/guides/realtime/broadcast"
SAMPLE = {"table": "orders", "function": "send-email", "bucket": "avatars", "path": "users/42/photo.png", "id": "upload-01",
          "user_id": "7c8d9e0f-1a2b-4c3d-8e4f-5a6b7c8d9e0f", "factor_id": "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d",
          "passkey_id": "pk_01", "identity_id": "1b2c3d4e-5f6a-4b7c-8d9e-0f1a2b3c4d5e", "idp_id": "6f7a8b9c-0d1e-4f2a-8b3c-4d5e6f7a8b9c",
          "client_id": "client_01", "identifier": "custom:acme", "authorization_id": "auth_01", "key": "photos/1.png"}

# (group, id, method, path, class, card, notes, sources, extra) where extra
# holds when, classify, and the fixtures: [(suffix, query, body, expect)].
R = []
def rule(group, rid, method, path, cls, card, notes=None, src=None, when=None, classify=None, fixtures=None, body=None):
    R.append(dict(group=group, id=rid, method=method, path=path, cls=cls, card=card, notes=notes, src=src, when=when or [],
                  classify=classify, fixtures=fixtures or [("", "", body, cls)]))

# ---- PostgREST: rows ----
rule("rest", "rest.insert", "POST", "/rest/v1/{table}", "write", "Insert rows into {table} in project {ref}",
     "With Prefer: resolution=merge-duplicates the insert updates the rows it conflicts with, still a write.", PGRST, body=[{"status": "new"}])
rule("rest", "rest.upsert", "PUT", "/rest/v1/{table}", "write", "Insert or replace a row of {table} in project {ref}", None, PGRST,
     fixtures=[("", "?id=eq.5", {"id": 5, "status": "new"}, "write")])
rule("rest", "rest.update", "PATCH", "/rest/v1/{table}", "write", "Update rows of {table} in project {ref}",
     "Irreversible when no filter limits the rows, since PostgREST then updates every row; filters that match every row (id=not.is.null, name=like.*) do not count, as for SQL.",
     PGRST, classify="query", fixtures=[("", "?id=eq.5", {"status": "paid"}, "write"), ("-every-row", "", {"status": "paid"}, "irreversible"),
                                         ("-tautology", "?id=not.is.null", {"status": "paid"}, "irreversible")])
rule("rest", "rest.delete", "DELETE", "/rest/v1/{table}", "delete", "Delete rows from {table} in project {ref}",
     "Irreversible when no filter limits the rows, since PostgREST then deletes every row; filters that match every row (id=not.is.null, name=like.*, an or= with such a branch) do not count, as for SQL. A limited delete is a delete: a backup or point-in-time restore can bring the rows back.",
     PGRST, classify="query", fixtures=[("", "?id=eq.5", None, "delete"), ("-every-row", "", None, "irreversible"),
                                         ("-or-tautology", "?or=(id.eq.1,id.not.is.null)", None, "irreversible"),
                                         ("-limit-only", "?order=id&limit=1", None, "irreversible")])
rule("rest", "rpc.call", "POST", "/rest/v1/rpc/{function}", "unknown", "Call database function {function} in project {ref}",
     "A function can run any SQL its owner may; Opfence cannot see its body. GET calls run in a read-only transaction, so they are reads.", RPC, body={"user_id": 42})

# ---- Storage: buckets ----
rule("storage", "bucket.create", "POST", "/storage/v1/bucket", "write", "Create storage bucket {body.name} in project {ref}",
     "A public bucket serves its files to anyone with the URL, so creating one is access.", STORAGE,
     when=[("access", '{ arg: body.public, equals: "true" }')],
     fixtures=[("", "", {"name": "avatars", "public": False}, "write"), ("-public", "", {"name": "avatars", "public": True}, "access")])
rule("storage", "bucket.update", "PUT", "/storage/v1/bucket/{bucket}", "write", "Change storage bucket {bucket} in project {ref}",
     "Changing whether the bucket is public is access.", STORAGE, when=[("access", "{ arg: body.public, present: true }")],
     fixtures=[("", "", {"file_size_limit": 1048576}, "write"), ("-public", "", {"public": True}, "access")])
rule("storage", "bucket.delete", "DELETE", "/storage/v1/bucket/{bucket}", "delete", "Delete storage bucket {bucket} in project {ref}",
     "Storage deletes only an empty bucket, so only its settings go, and they can be made again.", STORAGE)
rule("storage", "bucket.empty", "POST", "/storage/v1/bucket/{bucket}/empty", "irreversible", "Delete every file in storage bucket {bucket} of project {ref}",
     "Storage keeps no earlier versions of files.", STORAGE)
rule("storage", "bucket.lifecycle", "PUT", "/storage/v1/bucket/{bucket}/lifecycle", "irreversible", "Change the lifecycle rules of storage bucket {bucket} in project {ref}",
     "Lifecycle rules delete files once they are old enough, and Storage keeps no earlier versions.", STORAGE, body={"rules": []})

# ---- Storage: objects ----
rule("storage", "object.upload", "POST", "/storage/v1/object/{bucket}/{path*}", "write", "Upload {path} to storage bucket {bucket} of project {ref}",
     "With x-upsert: true an upload replaces the file at that path, as S3's PutObject does.", STORAGE, body={})
rule("storage", "object.replace", "PUT", "/storage/v1/object/{bucket}/{path*}", "write", "Replace {path} in storage bucket {bucket} of project {ref}", None, STORAGE, body={})
rule("storage", "object.delete", "DELETE", "/storage/v1/object/{bucket}/{path*}", "irreversible", "Delete {path} from storage bucket {bucket} of project {ref}",
     "Storage keeps no earlier versions of files.", STORAGE)
rule("storage", "object.delete-many", "DELETE", "/storage/v1/object/{bucket}", "irreversible", "Delete files {body.prefixes} from storage bucket {bucket} of project {ref}",
     "Storage keeps no earlier versions of files.", STORAGE, body={"prefixes": ["users/42/photo.png"]})
rule("storage", "object.move", "POST", "/storage/v1/object/move", "write", "Move {body.sourceKey} to {body.destinationKey} in storage bucket {body.bucketId} of project {ref}", None, STORAGE,
     body={"bucketId": "avatars", "sourceKey": "a.png", "destinationKey": "b.png"})
rule("storage", "object.copy", "POST", "/storage/v1/object/copy", "write", "Copy {body.sourceKey} to {body.destinationKey} in storage bucket {body.bucketId} of project {ref}", None, STORAGE,
     body={"bucketId": "avatars", "sourceKey": "a.png", "destinationKey": "b.png"})
rule("storage", "object.sign", "POST", "/storage/v1/object/sign/{bucket}/{path*}", "access", "Make a download link for {path} in storage bucket {bucket} of project {ref}",
     "Anyone with the link can download the file until it expires.", STORAGE, body={"expiresIn": 3600})
rule("storage", "object.sign-many", "POST", "/storage/v1/object/sign/{bucket}", "access", "Make download links for files in storage bucket {bucket} of project {ref}",
     "Anyone with a link can download the file until it expires.", STORAGE, body={"expiresIn": 3600, "paths": ["a.png"]})
rule("storage", "object.sign-upload", "POST", "/storage/v1/object/upload/sign/{bucket}/{path*}", "access", "Make an upload link for {path} in storage bucket {bucket} of project {ref}",
     "Anyone with the link can upload to that path until it expires.", STORAGE, body={})
rule("storage", "object.upload-signed", "PUT", "/storage/v1/object/upload/sign/{bucket}/{path*}", "write", "Upload {path} to storage bucket {bucket} of project {ref} with an upload link", None, STORAGE, body={})
rule("storage", "object.list", "POST", "/storage/v1/object/list/{bucket}", "read", None, "Lists files; a POST only to carry the search options.", STORAGE, body={"prefix": ""})
rule("storage", "object.list-v2", "POST", "/storage/v1/object/list-v2/{bucket}", "read", None, "Lists files; a POST only to carry the search options.", STORAGE, body={"prefix": ""})
rule("storage", "upload.create", "POST", "/storage/v1/upload/resumable", "write", "Start a resumable upload to project {ref}'s storage", "A tus upload.", STORAGE, body={})
for m in ("POST", "PUT", "PATCH", "DELETE"):
    rule("storage", f"upload.{m.lower()}", m, "/storage/v1/upload/resumable/{id*}", "write", "Continue or cancel resumable upload {id} to project {ref}'s storage",
         "Cancelling (DELETE) drops only the part uploaded so far.", STORAGE, body={} if m != "DELETE" else None)
rule("storage", "cdn.purge-all", "DELETE", "/storage/v1/cdn", "write", "Clear project {ref}'s storage CDN cache", "Files are fetched again on the next request.", STORAGE)
rule("storage", "cdn.purge-bucket", "DELETE", "/storage/v1/cdn/{bucket}", "write", "Clear the CDN cache of storage bucket {bucket} in project {ref}", None, STORAGE)
rule("storage", "cdn.purge-object", "DELETE", "/storage/v1/cdn/{bucket}/{path*}", "write", "Clear the CDN cache of {path} in storage bucket {bucket} of project {ref}", None, STORAGE)
# Storage's S3 protocol (SigV4 with S3 access keys from the dashboard).
rule("storage", "s3.create-bucket", "PUT", "/storage/v1/s3/{bucket}", "write", "Create storage bucket {bucket} in project {ref} through the S3 protocol", None, STORAGE)
rule("storage", "s3.put-object", "PUT", "/storage/v1/s3/{bucket}/{key*}", "write", "Upload {key} to storage bucket {bucket} of project {ref} through the S3 protocol",
     "Also copies and uploads parts, as S3's PutObject, CopyObject and UploadPart do.", STORAGE)
rule("storage", "s3.delete-bucket", "DELETE", "/storage/v1/s3/{bucket}", "delete", "Delete storage bucket {bucket} in project {ref} through the S3 protocol",
     "Storage deletes only an empty bucket.", STORAGE)
rule("storage", "s3.delete-object", "DELETE", "/storage/v1/s3/{bucket}/{key*}", "irreversible", "Delete {key} from storage bucket {bucket} of project {ref} through the S3 protocol",
     "Storage keeps no earlier versions of files. Also aborts multipart uploads.", STORAGE)
rule("storage", "s3.delete-objects", "POST", "/storage/v1/s3/{bucket}", "irreversible", "Delete files from storage bucket {bucket} of project {ref} through the S3 protocol",
     "A POST on a bucket is S3's DeleteObjects (?delete), which Storage keeps no earlier versions for.", STORAGE, fixtures=[("", "?delete", None, "irreversible")])
rule("storage", "s3.multipart", "POST", "/storage/v1/s3/{bucket}/{key*}", "write", "Upload {key} in parts to storage bucket {bucket} of project {ref} through the S3 protocol",
     "Starts or completes a multipart upload.", STORAGE, fixtures=[("", "?uploads", None, "write")])

# ---- Auth (GoTrue) ----
rule("auth", "signup", "POST", "/auth/v1/signup", "write", "Sign up user {body.email} in project {ref}", "Anyone with the publishable key can sign up unless sign-ups are off.", AUTH,
     body={"email": "ada@example.com", "password": "example-password"})
rule("auth", "token", "POST", "/auth/v1/token", "credential", "Sign in to project {ref} and get a session ({query.grant_type})", "Returns access and refresh tokens.", AUTH,
     fixtures=[("", "?grant_type=password", {"email": "ada@example.com", "password": "example-password"}, "credential")])
rule("auth", "verify", "POST", "/auth/v1/verify", "credential", "Verify a sign-in code for project {ref}", "Returns a session.", AUTH, body={"type": "email", "token": "123456"})
rule("auth", "verify-link", "GET", "/auth/v1/verify", "credential", "Open a sign-in link for project {ref}", "Redirects with a session.", AUTH,
     fixtures=[("", "?token=abc&type=magiclink", None, "credential")])
rule("auth", "callback", "GET", "/auth/v1/callback", "credential", "Finish an OAuth sign-in to project {ref}", "Exchanges the provider's code for a session.", AUTH,
     fixtures=[("", "?code=abc&state=xyz", None, "credential")])
rule("auth", "callback-post", "POST", "/auth/v1/callback", "credential", "Finish an OAuth sign-in to project {ref}", "Exchanges the provider's code for a session.", AUTH, body={})
rule("auth", "logout", "POST", "/auth/v1/logout", "write", "Sign out of project {ref}", None, AUTH, body={})
for p, what in (("recover", "Send a password reset email"), ("otp", "Send a sign-in code"), ("magiclink", "Send a sign-in link"), ("resend", "Resend a confirmation or code")):
    rule("auth", p, "POST", f"/auth/v1/{p}", "write", what + " for project {ref}", "Sends an email or a text message.", AUTH, body={"email": "ada@example.com"})
rule("auth", "user.update", "PUT", "/auth/v1/user", "access", "Change the signed-in user's email, phone, password or data in project {ref}", None, AUTH, body={"data": {"plan": "pro"}})
rule("auth", "identity.delete", "DELETE", "/auth/v1/user/identities/{identity_id}", "access", "Unlink sign-in identity {identity_id} from the signed-in user in project {ref}", None, AUTH)
rule("auth", "oauth-grant.revoke", "DELETE", "/auth/v1/user/oauth/grants", "access", "Revoke an app's access to the signed-in user in project {ref}", None, AUTH)
rule("auth", "factor.enroll", "POST", "/auth/v1/factors", "access", "Add a sign-in factor for the signed-in user in project {ref}", None, AUTH, body={"factor_type": "totp"})
rule("auth", "factor.verify", "POST", "/auth/v1/factors/{factor_id}/verify", "credential", "Verify sign-in factor {factor_id} in project {ref}", "Returns a session at the higher assurance level.", AUTH, body={"code": "123456"})
rule("auth", "factor.challenge", "POST", "/auth/v1/factors/{factor_id}/challenge", "write", "Challenge sign-in factor {factor_id} in project {ref}", None, AUTH, body={})
rule("auth", "factor.delete", "DELETE", "/auth/v1/factors/{factor_id}", "access", "Remove sign-in factor {factor_id} in project {ref}", "Removing a factor can turn multi-factor sign-in off.", AUTH)
rule("auth", "recovery-codes.create", "POST", "/auth/v1/factors/recovery-codes", "credential", "Create recovery codes for the signed-in user in project {ref}", "Returns the codes.", AUTH, body={})
rule("auth", "recovery-codes.regenerate", "POST", "/auth/v1/factors/recovery-codes/regenerate", "credential", "Regenerate the signed-in user's recovery codes in project {ref}", "Returns the codes.", AUTH, body={})
rule("auth", "recovery-codes.verify", "POST", "/auth/v1/factors/recovery-codes/verify", "credential", "Use a recovery code in project {ref}", "Returns a session.", AUTH, body={"code": "abcd-efgh"})
rule("auth", "recovery-codes.delete", "DELETE", "/auth/v1/factors/recovery-codes", "access", "Delete the signed-in user's recovery codes in project {ref}", None, AUTH)
rule("auth", "passkey.authentication-options", "POST", "/auth/v1/passkeys/authentication/options", "write", "Start a passkey sign-in to project {ref}", None, AUTH, body={})
rule("auth", "passkey.authentication-verify", "POST", "/auth/v1/passkeys/authentication/verify", "credential", "Sign in to project {ref} with a passkey", "Returns a session.", AUTH, body={})
rule("auth", "passkey.registration-options", "POST", "/auth/v1/passkeys/registration/options", "write", "Start adding a passkey in project {ref}", None, AUTH, body={})
rule("auth", "passkey.registration-verify", "POST", "/auth/v1/passkeys/registration/verify", "access", "Add a passkey for the signed-in user in project {ref}", None, AUTH, body={})
rule("auth", "passkey.update", "PATCH", "/auth/v1/passkeys/{passkey_id}", "access", "Change passkey {passkey_id} in project {ref}", None, AUTH, body={"friendly_name": "laptop"})
rule("auth", "passkey.delete", "DELETE", "/auth/v1/passkeys/{passkey_id}", "access", "Remove passkey {passkey_id} in project {ref}", None, AUTH)
rule("auth", "sso", "POST", "/auth/v1/sso", "write", "Start a single sign-on to project {ref}", None, AUTH, body={"domain": "example.com"})
rule("auth", "saml-acs", "POST", "/auth/v1/sso/saml/acs", "credential", "Finish a SAML sign-in to project {ref}", "Exchanges the assertion for a session.", AUTH, body={})
rule("auth", "oauth.client-register", "POST", "/auth/v1/oauth/clients/register", "access", "Register an OAuth client with project {ref}", "Lets the app ask the project's users for access.", AUTH, body={"client_name": "x"})
rule("auth", "oauth.token", "POST", "/auth/v1/oauth/token", "credential", "Get an OAuth token from project {ref}", None, AUTH, body={})
rule("auth", "oauth.consent", "POST", "/auth/v1/oauth/authorizations/{authorization_id}/consent", "access", "Grant an OAuth app access to the signed-in user in project {ref}", None, AUTH, body={"action": "approve"})
rule("auth", "invite", "POST", "/auth/v1/invite", "access", "Invite {body.email} to project {ref}", "Creates the user and emails a sign-in link.", AUTH, body={"email": "ada@example.com"})
# Admin (service role).
rule("auth-admin", "user.create", "POST", "/auth/v1/admin/users", "access", "Create user {body.email} in project {ref}", "Creates someone who can sign in; the service role can set their password, role and app metadata.", AUTH,
     body={"email": "ada@example.com", "email_confirm": True})
rule("auth-admin", "user.update", "PUT", "/auth/v1/admin/users/{user_id}", "access", "Change user {user_id} in project {ref}", "Can set the user's password, email, role, ban and app metadata.", AUTH, body={"ban_duration": "24h"})
rule("auth-admin", "user.delete", "DELETE", "/auth/v1/admin/users/{user_id}", "irreversible", "Delete user {user_id} from project {ref}",
     "Deletes the user and their identities; rows that reference them can go with them through foreign keys.", AUTH)
rule("auth-admin", "factor.update", "PUT", "/auth/v1/admin/users/{user_id}/factors/{factor_id}", "access", "Change sign-in factor {factor_id} of user {user_id} in project {ref}", None, AUTH, body={})
rule("auth-admin", "factor.delete", "DELETE", "/auth/v1/admin/users/{user_id}/factors/{factor_id}", "access", "Remove sign-in factor {factor_id} of user {user_id} in project {ref}", None, AUTH)
rule("auth-admin", "passkey.delete", "DELETE", "/auth/v1/admin/users/{user_id}/passkeys/{passkey_id}", "access", "Remove passkey {passkey_id} of user {user_id} in project {ref}", None, AUTH)
rule("auth-admin", "generate-link", "POST", "/auth/v1/admin/generate_link", "credential", "Make a {body.type} link for {body.email} in project {ref}",
     "Returns the link, and whoever opens a sign-in link is signed in as that user.", AUTH, body={"type": "magiclink", "email": "ada@example.com"})
for m, cls in (("POST", "access"), ("PUT", "access"), ("DELETE", "access")):
    p = "/auth/v1/admin/sso/providers" + ("/{idp_id}" if m != "POST" else "")
    rule("auth-admin", f"sso-provider.{m.lower()}", m, p, cls, {"POST": "Add an SSO provider to project {ref}", "PUT": "Change SSO provider {idp_id} of project {ref}", "DELETE": "Remove SSO provider {idp_id} from project {ref}"}[m], None, AUTH,
         body={} if m != "DELETE" else None)
    p = "/auth/v1/admin/oauth/clients" + ("/{client_id}" if m != "POST" else "")
    rule("auth-admin", f"oauth-client.{m.lower()}", m, p, cls, {"POST": "Register an OAuth client with project {ref}", "PUT": "Change OAuth client {client_id} of project {ref}", "DELETE": "Remove OAuth client {client_id} from project {ref}"}[m], None, AUTH,
         body={} if m != "DELETE" else None)
    p = "/auth/v1/admin/custom-providers" + ("/{identifier}" if m != "POST" else "")
    rule("auth-admin", f"custom-provider.{m.lower()}", m, p, cls, {"POST": "Add a sign-in provider to project {ref}", "PUT": "Change sign-in provider {identifier} of project {ref}", "DELETE": "Remove sign-in provider {identifier} from project {ref}"}[m], None, AUTH,
         body={} if m != "DELETE" else None)
rule("auth-admin", "oauth-client.regenerate-secret", "POST", "/auth/v1/admin/oauth/clients/{client_id}/regenerate_secret", "credential", "Make a new secret for OAuth client {client_id} of project {ref}", "Returns the secret.", AUTH, body={})

# ---- Edge functions ----
for m in ("GET", "POST", "PUT", "PATCH", "DELETE"):
    for sub in ("", "/{path*}"):
        b = {} if m in ("POST", "PUT", "PATCH") else None
        rule("functions", f"{m.lower()}{'-path' if sub else ''}", m, "/functions/v1/{function}" + sub, "unknown",
             "Call edge function {function} of project {ref}" + (" at {path}" if sub else ""),
             "An edge function runs code that can do anything its secrets allow; Opfence cannot see what.", FUNCS, body=b)

# ---- Realtime ----
rule("realtime", "broadcast", "POST", "/realtime/v1/api/broadcast", "write", "Send realtime messages in project {ref}", None, REALTIME, body={"messages": []})

# ---------------------------------------------------------------------------
# Rules and fixtures written by hand after this generator (stage 28c: the
# realtime socket): kept, and the rules appended to their group's file.
HERE = os.path.dirname(os.path.abspath(__file__))
HAND = {"realtime": os.path.join(HERE, "sbproject-realtime-socket.yaml")}
HAND_FIXTURES = ("realtime-socket-",)

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    if not f.startswith(HAND_FIXTURES):
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

def fill(s, extra=None):
    vals = dict(SAMPLE, ref=REF, **(extra or {}))
    return re.sub(r"\{([a-z_]+)\*?\}", lambda m: vals.get(m.group(1), m.group(1)), s)

files, ids, nfix = {}, set(), 0
for r in R:
    local = r["id"] if r["id"].startswith(r["group"] + ".") else r["group"] + "." + r["id"]
    rid = "supabase-project." + local
    assert rid not in ids, rid
    ids.add(rid)
    L = files.setdefault(r["group"], ["# Supabase project APIs (<ref>.supabase.co): " + r["group"].replace("-", " ") + ".", "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {r['method']}, path: \"{r['path']}\" }} }}")
    L.append(f"    class: {r['cls']}")
    if r["when"]:
        L.append("    when:")
        for wc, cond in r["when"]:
            L += [f"      - if: {cond}", f"        class: {wc}"]
    if r["classify"]:
        L.append(f"    classify: {{ postgrest: {r['classify']} }}")
    L.append("    resource: { arg: ref, kind: project }")
    if r["card"]:
        L.append(f"    card: {json.dumps(r['card'])}")
    L += ["    status: verified", "    verified: 2026-10-23", "    sources:", f"      - {r['src']}"]
    if r["notes"]:
        L.append("    notes: >-")
        L += wrap(r["notes"])
    L.append("    tests:")
    base = local.replace(".", "-")
    for suffix, query, body, expect in r["fixtures"]:
        name = base + suffix + ".http"
        desc = fill(r["card"] or ("Read: " + r["id"])) + {"-every-row": ", every row", "-tautology": ", with a filter that matches every row",
                                                         "-or-tautology": ", with an or= that matches every row", "-limit-only": ", with only a limit",
                                                         "-public": ", public"}.get(suffix, "")
        path = fill(r["path"])
        lines = [f"# description: {desc}", f"{r['method']} {path}{query} HTTP/1.1", f"Host: {HOST}",
                 "apikey: opf_supabase-project_EXAMPLE", "Authorization: Bearer opf_supabase-project_EXAMPLE"]
        if body is not None:
            lines += ["Content-Type: application/json", "", json.dumps(body)]
        else:
            lines.append("")
        open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")
        L += [f"      - fixture: fixtures/{name}", f"        expect: {expect}", f"        resource: \"{REF}\""]
        nfix += 1
    L.append("")
for g, L in files.items():
    text = "\n".join(L)
    if g in HAND:
        text += "\n" + open(HAND[g]).read()
    open(D + g + ".yaml", "w").write(text)
print(len(R), "rules in", len(files), "files,", nfix, "fixtures")
