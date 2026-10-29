# Writes catalog/gitlab/git.yaml and oauth.yaml with their fixtures (the
# rules gitlabgen.py does not generate). Run from the repo root.
import base64, json, os

D = "catalog/gitlab/"
DATE = "2026-10-28"
REPO = "/acme/platform/shop.git"
BASIC = "Basic " + base64.b64encode(b"oauth2:opf_gitlab_EXAMPLE").decode()
ZERO = "0" * 40
A1, A2 = "4f2a9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a39", "9c1e8b7d6a5f4e3d2c1b0a9f8e7d6c5b4a394f2a"
os.makedirs(D + "fixtures", exist_ok=True)


def pkt(s):
    return "%04x%s" % (len(s) + 4, s)


def http(name, desc, method, target, headers=(), body=None, auth=True):
    lines = [f"# description: {desc}", f"{method} {target} HTTP/1.1", "Host: gitlab.com"]
    if auth:
        lines.append(f"Authorization: {BASIC}")
    lines += list(headers)
    lines.append("")
    if body is not None:
        lines.append(body)
    open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")


UA = ["User-Agent: git/2.47.0"]
PUSH = UA + ["Content-Type: application/x-git-receive-pack-request", "Accept: application/x-git-receive-pack-result"]
http("git-info-refs-fetch.http", "Ref advertisement before a fetch of acme/platform/shop", "GET",
     REPO + "/info/refs?service=git-upload-pack", UA + ["Git-Protocol: version=2"])
http("git-upload-pack.http", "Protocol v2 ls-refs during a fetch of acme/platform/shop", "POST", REPO + "/git-upload-pack",
     UA + ["Content-Type: application/x-git-upload-pack-request", "Git-Protocol: version=2"],
     pkt("command=ls-refs\n") + "0001" + pkt("peel\n") + pkt("ref-prefix refs/heads/\n") + "0000")
http("git-info-refs-push.http", "Ref advertisement before a push to acme/platform/shop", "GET",
     REPO + "/info/refs?service=git-receive-pack", UA)
http("git-push-probe.http", "Authentication probe git sends before a large push to acme/platform/shop", "POST",
     REPO + "/git-receive-pack", UA + ["Content-Type: application/x-git-receive-pack-request"], "0000")
for name, desc, old, new, ref, end in [
    ("git-push-create.http", "Push new branch feature-x to acme/platform/shop", ZERO, A1, "refs/heads/feature-x", "0000PACK"),
    ("git-push-create-tag.http", "Push new tag v1.4.0 to acme/platform/shop", ZERO, A1, "refs/tags/v1.4.0", "0000PACK"),
    ("git-push-update.http", "Push branch feature-x of acme/platform/shop", A1, A2, "refs/heads/feature-x", "0000PACK"),
    ("git-push-update-main.http", "Push branch main of acme/platform/shop", A1, A2, "refs/heads/main", "0000PACK"),
    ("git-push-update-tag.http", "Move tag v1.4.0 of acme/platform/shop", A1, A2, "refs/tags/v1.4.0", "0000PACK"),
    ("git-push-delete.http", "Delete branch feature-x from acme/platform/shop", A1, ZERO, "refs/heads/feature-x", "0000"),
]:
    first = f"{old} {new} {ref}"
    http(name, desc, "POST", REPO + "/git-receive-pack", PUSH, pkt(first) + end)
LFS = UA + ["Accept: application/vnd.git-lfs+json", "Content-Type: application/vnd.git-lfs+json"]
http("git-lfs-batch-download.http", "Git LFS download from acme/platform/shop", "POST", REPO + "/info/lfs/objects/batch", LFS,
     json.dumps({"operation": "download", "transfers": ["basic"], "objects": [{"oid": "a" * 64, "size": 1024}]}))
http("git-lfs-batch-upload.http", "Git LFS upload to acme/platform/shop", "POST", REPO + "/info/lfs/objects/batch", LFS,
     json.dumps({"operation": "upload", "transfers": ["basic"], "objects": [{"oid": "a" * 64, "size": 1024}]}))
http("git-lfs-locks-list.http", "List Git LFS locks of acme/platform/shop", "GET", REPO + "/info/lfs/locks", LFS)
http("git-lfs-lock.http", "Lock assets/logo.psd in acme/platform/shop", "POST", REPO + "/info/lfs/locks", LFS,
     json.dumps({"path": "assets/logo.psd"}))
http("git-lfs-unlock.http", "Remove Git LFS lock 7 in acme/platform/shop", "POST", REPO + "/info/lfs/locks/7/unlock", LFS,
     json.dumps({"force": False}))

GIT_SRC = ["https://git-scm.com/docs/gitprotocol-http", "https://docs.gitlab.com/topics/git/lfs/"]


def rule(L, rid, match, cls, card, tests, notes=None, sources=GIT_SRC, resource=("repository", "repository"), extra=()):
    L += [f"  - id: {rid}", f"    match: {match}", f"    class: {cls}"] + list(extra)
    if resource:
        L.append(f"    resource: {{ arg: {resource[0]}, kind: {resource[1]} }}")
    L += [f"    card: {json.dumps(card)}", "    status: verified", f"    verified: {DATE}", "    sources:"]
    L += [f"      - {s}" for s in sources]
    if notes:
        L.append("    notes: >-")
        words, line = notes.split(), "     "
        for w in words:
            if len(line) + len(w) + 1 > 100:
                L.append(line)
                line = "     "
            line += " " + w
        L.append(line)
    L.append("    tests:")
    for f, ex, *r in tests:
        L += [f"      - fixture: fixtures/{f}", f"        expect: {ex}"]
        if r and r[0]:
            L.append(f"        response: fixtures/{r[0]}")
        if resource and not (r[1:] and r[1] is None):
            L.append("        resource: acme/platform/shop")
    L.append("")


L = ["# git over HTTPS to gitlab.com: smart HTTP fetches and pushes, and Git LFS. Repositories",
     "# sit under nested groups, so the resource is the project's whole path. As for GitHub's",
     "# git rules (catalog/github/git.yaml).", "operations:"]
rule(L, "gitlab.git.fetch", "{ git: { service: upload-pack, command: fetch } }", "read", "Fetch from {repository}",
     [("git-info-refs-fetch.http", "read"), ("git-upload-pack.http", "read")],
     "Every upload-pack request, the ref advertisement included, only reads, in protocol v0, v1 and v2. A project "
     "path deeper than owner/repo is read as git only with .git, as GitLab serves it (it redirects the path without "
     "it), since the host also serves the REST API.")
rule(L, "gitlab.git.list-refs", "{ git: { service: receive-pack, command: list } }", "read", "List refs of {repository} before a push",
     [("git-info-refs-push.http", "read"), ("git-push-probe.http", "read")],
     "The ref advertisement that starts a push, and the empty push git sends to check credentials before a large "
     "upload. Neither changes a ref.")
rule(L, "gitlab.git.create-ref", "{ git: { service: receive-pack, command: create } }", "write", "Push new {ref} to {repository}",
     [("git-push-create.http", "write"), ("git-push-create-tag.http", "write")])
rule(L, "gitlab.git.update-ref", "{ git: { service: receive-pack, command: update } }", "write", "Push {ref} of {repository} to {new}",
     [("git-push-update.http", "write")],
     "A forced push sends the same command as a fast-forward, so Opfence cannot tell them apart. On feature "
     "branches that is accepted as a write; the default branch and tags have their own rules. GitLab's protected "
     "branches refuse forced pushes unless allowed.")
rule(L, "gitlab.git.update-default-branch", "{ git: { service: receive-pack, command: update, refs: [refs/heads/main, refs/heads/master] } }",
     "delete", "Push {ref} of {repository} to {new} (may be a force push)", [("git-push-update-main.http", "delete")],
     "The push may be forced, which rewrites the default branch; the old commits can be pushed back from a clone.")
rule(L, "gitlab.git.update-tag", '{ git: { service: receive-pack, command: update, refs: ["refs/tags/*"] } }',
     "delete", "Move tag {ref} of {repository} to {new}", [("git-push-update-tag.http", "delete")],
     "Moving a tag changes what a release points at; the old target can be pushed back from a clone.")
rule(L, "gitlab.git.delete-ref", "{ git: { service: receive-pack, command: delete } }", "delete", "Delete {ref} from {repository}",
     [("git-push-delete.http", "delete")],
     "The commits stay until garbage-collected and the ref can be pushed again from any clone.")
rule(L, "gitlab.git.lfs-download", "{ git: { service: lfs, command: download } }", "read", "Download Git LFS objects from {repository}",
     [("git-lfs-batch-download.http", "read")])
rule(L, "gitlab.git.lfs-upload", "{ git: { service: lfs, command: upload } }", "write", "Upload Git LFS objects to {repository}",
     [("git-lfs-batch-upload.http", "write")])
rule(L, "gitlab.git.lfs-list-locks", "{ git: { service: lfs, command: list-locks } }", "read", "List Git LFS locks of {repository}",
     [("git-lfs-locks-list.http", "read")])
rule(L, "gitlab.git.lfs-lock", "{ git: { service: lfs, command: lock } }", "write", "Lock {path} in {repository} with Git LFS",
     [("git-lfs-lock.http", "write")])
rule(L, "gitlab.git.lfs-unlock", "{ git: { service: lfs, command: unlock } }", "write", "Remove Git LFS lock {id} in {repository}",
     [("git-lfs-unlock.http", "write")])
open(D + "git.yaml", "w").write("\n".join(L))

# OAuth (Doorkeeper), outside the REST API's OpenAPI description.
FORM = ["Content-Type: application/x-www-form-urlencoded"]
http("oauth-token-refresh.http", "Refresh an OAuth session (glab)", "POST", "/oauth/token", ["User-Agent: glab"] + FORM,
     "grant_type=refresh_token&refresh_token=opf_gitlab_EXAMPLErefresh&client_id=41d48f9422ebd655dd9cf2947d6979681dfaddc6d0c56f7628f6ada59559af1e",
     auth=False)
http("oauth-token-device.http", "Finish a device sign-in (glab auth login)", "POST", "/oauth/token.json", FORM,
     "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Adevice_code&device_code=EXAMPLEdevicecode&client_id=41d48f9422ebd655dd9cf2947d6979681dfaddc6d0c56f7628f6ada59559af1e",
     auth=False)
open(D + "fixtures/oauth-token-response.json", "w").write(json.dumps({
    "access_token": "EXAMPLEaccesstoken0123456789abcdef0123456789abcdef0123456789ab", "token_type": "Bearer",
    "expires_in": 7200, "refresh_token": "EXAMPLErefreshtoken0123456789abcdef0123456789abcdef0123456789a",
    "scope": "api write_repository openid", "created_at": 1761600000}, indent=2) + "\n")
http("oauth-revoke.http", "Revoke an OAuth token", "POST", "/oauth/revoke", FORM, "token=opf_gitlab_EXAMPLE&client_id=abc", auth=False)
http("oauth-device-authorize.http", "Start a device sign-in (glab auth login)", "POST", "/oauth/authorize_device", FORM,
     "client_id=41d48f9422ebd655dd9cf2947d6979681dfaddc6d0c56f7628f6ada59559af1e&scope=api+write_repository", auth=False)
OAUTH_SRC = ["https://docs.gitlab.com/api/oauth2/", "https://github.com/doorkeeper-gem/doorkeeper/blob/main/config/routes.rb"]
UNL = "    unlisted: \"Doorkeeper's OAuth routes, outside the REST API's OpenAPI description\""
L = ["# OAuth on gitlab.com (Doorkeeper): glab signs in with the device flow and refreshes",
     "# its session at /oauth/token.", "operations:"]
rule(L, "gitlab.oauth.token", '{ rest: { method: POST, path: "/oauth/token" } }', "credential",
     "Exchange an OAuth grant for GitLab tokens", [("oauth-token-refresh.http", "credential", "oauth-token-response.json", None),
                                                   ("oauth-token-device.http", "credential", "oauth-token-response.json", None)],
     "Returns an access token and a refresh token for whichever grant is sent: an authorization code, a device code, a "
     "refresh token, or a user's password. Under opfence run both reach the agent as placeholders minted for this "
     "session, and the refresh token is swapped back in when glab refreshes, so the exchange is a read there, as "
     "exchanging a credential the caller already holds is (ARCHITECTURE §4.5); anywhere else it stays credential.",
     OAUTH_SRC, None, [UNL, "    response:", "      mint: [access_token, refresh_token]", "      class: read"])
rule(L, "gitlab.oauth.revoke", '{ rest: { method: POST, path: "/oauth/revoke" } }', "access", "Revoke an OAuth token",
     [("oauth-revoke.http", "access", None, None)], "Whatever uses the token stops working.", OAUTH_SRC, None, [UNL])
rule(L, "gitlab.oauth.authorize-device", '{ rest: { method: POST, path: "/oauth/authorize_device" } }', "read",
     "Start a device sign-in", [("oauth-device-authorize.http", "read", None, None)],
     "Returns a code the user enters in a browser; no token is issued until they approve it.", OAUTH_SRC, None, [UNL])
open(D + "oauth.yaml", "w").write("\n".join(L))
print("ok")
