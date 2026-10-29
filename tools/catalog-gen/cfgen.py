# Writes catalog/cloudflare rules for the families stage 13b left out:
# API Shield (api_gateway), Zero Trust devices, DLP, Magic, Cloudforce One.
# Run from the repo root: python3 -I cfgen.py <openapi.json> [--print]
# Operations a rule already covers are left alone: a later run adds rules
# only for new operations, at the end of their family's file.
import json, os, re, sys

SPEC = json.load(open(sys.argv[1]))
PRINT = "--print" in sys.argv
D = "catalog/cloudflare/"
SRC = "https://github.com/cloudflare/api-schemas/blob/main/openapi.json"
NOT_FALSE = "'^(?is:[^0f].*|0.+|f[^a].*|fa|fa[^l].*|fal|fal[^s].*|fals|fals[^e].*|false.+)$'"

FILES = {"api_gateway": "api-shield", "devices": "zt-devices", "dlp": "dlp", "magic": "magic", "cloudforce-one": "cloudforce-one"}

NOTES = {
    "api-shield": "API Shield's schema validation, session identifiers and endpoint inventory decide which API requests "
                  "are checked and blocked; as with firewall rules, every change to them is access.",
    "zt-devices": "Device settings, posture rules, split tunnels and registrations decide which devices reach the "
                  "Zero Trust network and what traffic skips inspection; every change is access.",
    "dlp": "DLP profiles, entries and settings decide what data Gateway lets leave; as with firewall rules, every "
           "change to them is access.",
    "magic-protection": "Advanced DNS and TCP protection rules, allowlists and prefixes decide what traffic reaches "
                        "the network; as with firewall rules, every change is access.",
}

# Explicit classes by operationId: (class, note or None).
OVR = {
    # API Shield.
    "api-shield-expression-templates-fallthrough": ("read", "Builds a WAF expression; nothing is saved."),
    "api-shield-api-patch-discovered-operations": ("write", None),
    "api-shield-api-patch-discovered-operation": ("write", None),
    "api-shield-labels-replace-operations-attached-to-managed-label": ("write", None),
    "api-shield-labels-delete-user-labels": ("delete", None),
    "api-shield-labels-create-user-labels": ("write", None),
    "api-shield-delete-user-label": ("delete", None),
    "api-shield-patch-user-label": ("write", None),
    "api-shield-put-user-label": ("write", None),
    "api-shield-labels-replace-operations-attached-to-user-label": ("write", None),
    "api-shield-endpoint-management-add-operations-to-a-zone": ("write", None),
    "api-shield-endpoint-management-add-operation-to-a-zone": ("write", None),
    "api-shield-operations-bulk-delete-labels-to-operations": ("write", None),
    "api-shield-operations-bulk-post-labels-to-operations": ("write", None),
    "api-shield-operations-bulk-put-labels-to-operations": ("write", None),
    "api-shield-operations-delete-labels-from-operation": ("write", None),
    "api-shield-operations-post-labels-to-operation": ("write", None),
    "api-shield-operations-put-labels-to-operation": ("write", None),
    # Devices.
    "create-override-code": ("credential", "An uninstall protection override code lets whoever holds it remove the WARP client."),
    "device-posture-integrations-create-device-posture-integration": ("credential", "The integration's config holds the third-party API's client secret."),
    "device-posture-integrations-update-device-posture-integration": ("credential", "The integration's config holds the third-party API's client secret."),
    "patch-device": ("write", None),
    # DLP.
    "dlp-pattern-validate": ("read", "Checks a regular expression; nothing is saved."),
    "dlp-datasets-create": ("credential", "Unless secret is false, the dataset is an Exact Data Match one and the response holds the secret the EDM encoder hashes it with."),
    "dlp-datasets-update": ("write", None),
    "dlp-datasets-create-version": ("credential", "For an Exact Data Match dataset the response holds the secret the EDM encoder hashes the new version with."),
    "dlp-email-scanner-create-account-mapping": ("credential", "The response holds the add-in identifier token the email add-in presents for the account."),
    "dlp-email-scanner-get-account-mapping": ("credential", "Returns the add-in identifier token the email add-in presents for the account."),
    "dlp-datasets-upload-version": ("write", None),
    "dlp-datasets-define-columns": ("write", None),
    "dlp-datasets-upload-dataset-column": ("write", None),
    "dlp-document-fingerprints-upload": ("write", None),
    "dlp-payload-log-put": ("access", "Payload logging stores matched content, encrypted to the public key given: whoever holds the private key reads it."),
    # Magic.
    "onramps-apply": ("irreversible", "Applies the on-ramp's plan to the connected cloud account, which can create, change and destroy resources there."),
    "onramps-plan": ("read", "Plans the on-ramp's changes; nothing is applied."),
    "onramps-export": ("read", "Exports the on-ramp as Terraform; nothing is changed."),
    "resources-catalog-policy-preview": ("read", "Runs a Rego query against the resource catalog; nothing is saved."),
    "providers-create": ("access", "A cloud integration gives Cloudflare access to a cloud account."),
    "providers-update": ("access", "Can point the integration at another cloud account or role."),
    "providers-patch": ("access", "Can point the integration at another cloud account or role."),
    "providers-delete": ("delete", None),
    "magic-ipsec-tunnels-set-pre-shared-keys-for-ipsec-tunnels": ("credential", "Sets tunnels' pre-shared keys, a secret-store value."),
    "magic-ipsec-tunnels-generate-pre-shared-key-(-psk)-for-ipsec-tunnels": ("credential", "Returns a new pre-shared key for the tunnel."),
    "magic-site-netflow-config-create-netflow-config": ("access", "NetFlow sends the site's traffic records to a collector."),
    "magic-site-netflow-config-update-netflow-config": ("access", "Can change which collector receives the site's traffic records."),
    "magic-site-netflow-config-patch-netflow-config": ("access", "Can change which collector receives the site's traffic records."),
    "magic-site-netflow-config-delete-netflow-config": ("delete", None),
    # Cloudforce One reads sent with POST.
    "post_EventList": ("read", None), "cloudforce-one-request-list": ("read", None), "cloudforce-one-priority-list": ("read", None),
    "cloudforce-one-request-asset-list": ("read", None), "cloudforce-one-request-message-list": ("read", None),
    "post_EventGraphQL": ("read", "Aggregates events; the endpoint only reads."), "post_EventGraphQLV2": ("read", "Aggregates events; the endpoint only reads."),
    "cloudforce-one-validate-email-rule": ("read", None), "cloudforce-one-validate-rule": ("read", None),
    "cloudforce-one-test-email-rule": ("read", None), "post_DomainTrial": ("read", None), "post_SearchLogoSimilarity": ("read", None),
    "post_TakedownNoticeLookup": ("read", None), "post_ItemSearch": ("read", None), "post_PirFilterGenerate": ("read", None),
    "post_PirQuota": ("read", None), "post_LetterGenerate": ("read", "Drafts a takedown letter's text; nothing is sent."),
}
for k in list(OVR):
    if k.startswith("post_PirInterest") and ("Backtest" in k or "Evaluat" in k):
        pass
# Cloudforce One: who can see datasets, and the rules that decide what is blocked.
CF1_ACCESS = re.compile(r"/(permissions|groups)(/|$)|/members(/|$)")
CF1_RULES = re.compile(r"^/cloudforce-one/rules")
# Deleting stored intelligence (events, datasets, indicators, collections and
# their items, requests and their messages) loses data; deleting
# configuration (tags, categories, queries, feeds, skills) does not.
CF1_DATA = re.compile(r"/(events|dataset|datasets|indicators|collections|items|requests|message|asset|binary)(/|$)")


def classify(fam, method, rel, op):
    opid = op.get("operationId", "")
    summary = op.get("summary", "")
    if opid in OVR:
        return OVR[opid]
    if fam == "cloudforce-one":
        if re.match(r"(?i)^(list|filter and list|search|lookup|get|validate|test|analy[sz]e|backtest|evaluate)\b", summary):
            return ("read", None)
        if CF1_ACCESS.search(rel):
            return ("access", "Dataset permissions and groups decide which accounts can read the intelligence.")
        if CF1_RULES.match(rel):
            return ("access", "Cloudforce One rules and exemptions decide what is detected and blocked; as with firewall rules, every change is access.")
        if method == "DELETE":
            last = rel.rstrip("/").split("/")
            if CF1_DATA.search("/".join(last[:-1]) + "/") and not re.search(r"/(tags?|categories|queries|templates|feeds|skills|interests|columns|relationships|relate|event_tag|tag-categories|event-categories|config|domains|letters|takedown-notices|priority|priority-intelligence)(/|$)", rel):
                return ("irreversible", "Deletes stored intelligence, which cannot be restored.")
            return ("delete", None)
        return ("write", None)
    if fam == "magic":
        if "/advanced_dns_protection/" in rel or "/advanced_tcp_protection/" in rel:
            return ("access", NOTES["magic-protection"])
        if re.search(r"/sites/\{[^}]+\}/(acls|app_configs)", rel):
            return ("access", "Site ACLs and app configurations decide which traffic the site lets through or sends around Cloudflare.")
        if method == "DELETE":
            return ("delete", None)
        return ("write", None)
    if fam == "devices":
        return ("access", None)
    if fam == "dlp":
        return ("access", None)
    if fam == "api_gateway":
        if method == "DELETE" and "/operations" in rel:
            return ("access", "Removing operations from endpoint management drops the per-operation protections that apply to them.")
        return ("access", None)
    raise ValueError(fam)


def kebab(s):
    s = re.sub(r"^(post|put|patch|delete|get)_", "", s)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    for pre in ("api-shield-", "magic-", "devices-", "device-", "dlp-", "cloudforce-one-", "zero-trust-accounts-"):
        if s.startswith(pre):
            s = s[len(pre):]
    return re.sub(r"-+", "-", s)


SAMPLE = {"account_id": "023e105f4ecef8ad9ca31a8372d0c353", "zone_id": "023e105f4ecef8ad9ca31a8372d0c353"}
def sample(name):
    if name in SAMPLE:
        return SAMPLE[name]
    if name == "project_type":
        return "rfi"
    if name == "version":
        return "1"
    if name == "email":
        return "ada@example.com"
    if name == "name":
        return "checkout"
    return "f174e90a-fafe-4643-bbbc-4a0ed4fc8415"


def kind_of(param):
    k = re.sub(r"_(id|uuid)$", "", param).replace("_", "-")
    return {"account": "account", "zone": "zone"}.get(k, k)


rows = []
for path, item in SPEC["paths"].items():
    m = re.match(r"^/(accounts|zones)/\{[^}]+\}/?(.*)$", path)
    if not m:
        continue
    rel = "/" + m.group(2)
    fam = m.group(2).split("/")[0]
    if fam not in FILES:
        continue
    for method, op in item.items():
        # GETs are reads by the provider default, except those listed.
        if method not in ("post", "put", "patch", "delete") and not (method == "get" and op.get("operationId") in OVR):
            continue
        cls, note = classify(fam, method.upper(), rel, op)
        rows.append((FILES[fam], method.upper(), path, rel, op, cls, note))

if PRINT:
    for f, m, p, rel, op, cls, note in sorted(rows, key=lambda r: (r[0], r[3], r[1])):
        print(f"{f:15} {cls:12} {m:6} {rel:95} {op.get('summary','')[:60]}")
    sys.exit(0)

# Existing rules that already cover an operation are left alone.
existing = set()
for fn in os.listdir(D):
    if fn.endswith(".yaml") and fn != "provider.yaml":
        for line in open(D + fn):
            mm = re.search(r'rest: \{ method: (\w+), path: "([^"]+)"', line)
            if mm:
                existing.add((mm.group(1), mm.group(2)))

out = {}
ids = set()
for f, method, path, rel, op, cls, note in sorted(rows, key=lambda r: (r[0], r[3], r[1])):
    full = "/client/v4" + path
    if (method, full) in existing:
        continue
    verb = kebab(op.get("operationId") or (method + rel))
    if f"cloudflare.{f}.{verb}" in ids:
        verb = f"{verb}-{method.lower()}"  # Cloudforce One accepts PATCH and POST for the same update
    rid = f"cloudflare.{f}.{verb}"
    assert rid not in ids, rid
    ids.add(rid)
    params = re.findall(r"\{([^}]+)\}", path)
    res = params[-1]
    summary = op.get("summary", "").rstrip(".").replace(" [DEPRECATED]", "")
    target = [p for p in params if p not in ("account_id", "zone_id")]
    card = summary + (" {" + target[-1] + "}" if target else "")
    if note is None and cls == "access":
        note = NOTES.get(f)
    if op.get("deprecated"):
        note = ((note + " ") if note else "") + "Cloudflare has deprecated this endpoint."
    L = out.setdefault(f, [f"# Cloudflare REST API (api.cloudflare.com/client/v4): {f}", "operations:"])
    L.append(f"  - id: {rid}")
    L.append(f"    match: {{ rest: {{ method: {method}, path: \"{full}\" }} }}")
    L.append(f"    class: {cls}")
    tests = [("", {}, cls)]
    if op.get("operationId") == "dlp-datasets-create":
        L += ["    when:", "      - if: { arg: body.secret, equals: \"false\" }", "        class: write"]
        tests = [("", {"body": '{"name":"customers"}'}, "credential"), ("-secret", {"body": '{"name":"customers","secret":true}'}, "credential"),
                 ("-plaintext", {"body": '{"name":"words","secret":false}'}, "write")]
    if op.get("operationId") in ("magic-ipsec-tunnels-create-ipsec-tunnels", "magic-ipsec-tunnels-update-ipsec-tunnel",
                                 "magic-ipsec-tunnels-update-multiple-ipsec-tunnels"):
        L += ["    when:", "      - if: { arg: body.psk, present: true }", "        class: credential",
              "      - if: { arg: body.ipsec_tunnels.psk, present: true }", "        class: credential"]
        note = "A tunnel's pre-shared key is a secret-store value: setting it is credential."
        if op.get("operationId") == "magic-ipsec-tunnels-update-multiple-ipsec-tunnels":
            tests.append(("-psk", {"body": '{"ipsec_tunnels":[{"id":"t1","psk":"hunter2"}]}'}, "credential"))
        else:
            tests.append(("-psk", {"body": '{"name":"office","psk":"hunter2"}'}, "credential"))
    if op.get("operationId") == "onramps-delete":
        L += ["    when:", f"      - if: {{ arg: query.destroy, matches: {NOT_FALSE} }}", "        class: irreversible"]
        note = "Deletes the on-ramp; with destroy it also destroys the resources it created in the cloud account."
        tests.append(("-destroy", {"query": "destroy=true"}, "irreversible"))
    L.append(f"    resource: {{ arg: {res}, kind: {kind_of(res)} }}")
    if cls != "read":
        if method == "GET":
            card = "Read " + card[0].lower() + card[1:]
        L.append(f"    card: {json.dumps(card)}")
    L += ["    status: verified", "    verified: 2026-10-22", "    sources:", f"      - {SRC}"]
    if note:
        L.append("    notes: >-")
        line = "      "
        for w in note.split():
            if len(line) + len(w) + 1 > 100 and line.strip():
                L.append(line); line = "      "
            line += ("" if line.strip() == "" else " ") + w
        L.append(line)
    L.append("    tests:")
    for suffix, extra, expect in tests:
        fpath = "/client/v4" + re.sub(r"\{([^}]+)\}", lambda mm: sample(mm.group(1)), path)
        if extra.get("query"):
            fpath += "?" + extra["query"]
        name = f"{f}-{verb}{suffix}.http"
        desc = re.sub(r"\{([^}]+)\}", lambda mm: sample(mm.group(1)), card)
        lines = [f"# description: {desc}", f"{method} {fpath} HTTP/1.1", "Host: api.cloudflare.com",
                 "Authorization: Bearer opf_cloudflare_EXAMPLE"]
        if method in ("POST", "PUT", "PATCH"):
            lines += ["Content-Type: application/json", "", extra.get("body", "{}")]
        else:
            lines.append("")
        open(D + "fixtures/" + name, "w").write("\n".join(lines) + "\n")
        L += [f"      - fixture: fixtures/{name}", f"        expect: {expect}", f"        resource: \"{sample(res)}\""]
    L.append("")
for f, L in out.items():
    # A family's file that exists keeps its rules; new ones go at its end.
    if os.path.exists(D + f + ".yaml"):
        open(D + f + ".yaml", "a").write("\n" + "\n".join(L[2:]))
    else:
        open(D + f + ".yaml", "w").write("\n".join(L))
print({f: sum(1 for l in L if l.startswith("  - id:")) for f, L in out.items()})
