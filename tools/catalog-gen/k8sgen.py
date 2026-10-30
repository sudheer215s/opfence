# Writes catalog/kubernetes (rules and fixtures) and the resource table
# internal/decode/kubeapi.json from Kubernetes' OpenAPI description. Run from the repo root:
#   python3 -I tools/catalog-gen/k8sgen.py <swagger.json> <kubernetes tag>
# where swagger.json is api/openapi-spec/swagger.json at that tag.
#
# One rule per resource, action and scope, with the API version as a path
# parameter, so a cluster still serving an older version of a group meets
# the same rules. Every resource and subresource needs a profile below: the
# script fails on one it does not know.
import base64, json, os, re, sys

SPEC_PATH, TAG = sys.argv[1], sys.argv[2]
SPEC = json.load(open(SPEC_PATH))
D = "catalog/kubernetes/"
DATE = "2026-10-30"
SRC = f"https://github.com/kubernetes/kubernetes/blob/{TAG}/api/openapi-spec/swagger.json"
API_DOCS = "https://kubernetes.io/docs/reference/kubernetes-api/"

R, W, DEL, I, A, C, M, U = "read", "write", "delete", "irreversible", "access", "credential", "money", "unknown"

# Fixture hosts, one per pattern in provider.yaml, used in turn.
HOSTS = [
    "a1b2c3d4e5f60718293a4b5c6d7e8f90.gr7.us-east-1.eks.amazonaws.com",
    "shop-prod-dns-4f7a1c2e.hcp.eastus.azmk8s.io",
    "gke-1e6371ceeb5a4e02aed7c588bd2b82491006-993897508389.europe-west2.gke.goog",
    "3f2a7c1e-5b9d-4e8a-9c1f-2d7e6b5a4c3d.k8s.ondigitalocean.com",
    "8c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f.us-east-2-gw.linodelke.net",
]
TRUE = ["true", "yes", "y", "on"]  # the API server reads YAML 1.1 booleans
CAPS = "'(?i)^(CAP_)?(ALL|SYS_ADMIN|SYS_PTRACE|SYS_MODULE|SYS_RAWIO|SYS_BOOT|NET_ADMIN|DAC_READ_SEARCH|BPF|PERFMON)$'"

SHORT = {"": "core", "admissionregistration.k8s.io": "admissionregistration", "apiextensions.k8s.io": "apiextensions",
         "apiregistration.k8s.io": "apiregistration", "apps": "apps", "authentication.k8s.io": "authentication",
         "authorization.k8s.io": "authorization", "autoscaling": "autoscaling", "batch": "batch",
         "certificates.k8s.io": "certificates", "coordination.k8s.io": "coordination", "discovery.k8s.io": "discovery",
         "events.k8s.io": "events", "flowcontrol.apiserver.k8s.io": "flowcontrol",
         "internal.apiserver.k8s.io": "internal-apiserver", "lifecycle.k8s.io": "lifecycle",
         "networking.k8s.io": "networking", "node.k8s.io": "node", "policy": "policy",
         "rbac.authorization.k8s.io": "rbac", "resource.k8s.io": "resource", "scheduling.k8s.io": "scheduling",
         "storage.k8s.io": "storage", "storagemigration.k8s.io": "storagemigration"}

# Notes shared by profiles.
N_DELETE = "The API keeps no copy of a deleted object."
N_ACCESS_ADMISSION = ("Admission webhooks and policies see or change every object the API server admits; adding, changing "
                      "or removing one changes what the cluster enforces, so every change is access.")
N_RBAC = "Roles and their bindings decide who can do what in the cluster; every change is access."
N_POD = ("A pod spec that asks for privileged containers, the host's network, PID or IPC namespaces, hostPath volumes "
         "or dangerous capabilities is access: such a pod owns its node. A JSON Patch, whose effect Opfence cannot "
         "read, is access too.")

# Profiles: (group, plural) -> create (c), update (w), delete (d) classes,
# where the pod spec is (pod), whether replicas can drop to zero (replicas),
# whether it is a Service (service), and notes for writes and deletes.
P = {}
def prof(group, plural, w=W, d=DEL, c=None, pod=None, replicas=False, service=False, note=None, dnote=None, read=None, only_create=False):
    P[(group, plural)] = dict(w=w, d=d, c=c or w, pod=pod, replicas=replicas, service=service, note=note, dnote=dnote, read=read, only_create=only_create)

# core
prof("", "componentstatuses")  # read only
prof("", "configmaps", note="On EKS, kube-system/aws-auth maps IAM roles and users to Kubernetes users and groups, so writing it is access.")
prof("", "endpoints")
prof("", "events")
prof("", "limitranges")
prof("", "namespaces", d=I, dnote="Deleting a namespace deletes every object in it, with the Secrets and volume claims it holds.")
prof("", "bindings", only_create=True, note="Binds a pod to a node, as the scheduler does.")
prof("", "persistentvolumeclaims", c=M, d=I,
     note="Creating a claim provisions a disk from its storage class, which the cloud bills, as Google Cloud's disks.insert does.",
     dnote="With the usual Delete reclaim policy, deleting a claim deletes its volume and the data on it.")
prof("", "persistentvolumes", d=I, dnote="With a Delete reclaim policy the storage behind the volume goes with it.")
prof("", "pods", pod="spec", note=N_POD)
prof("", "podtemplates", pod="template.spec", note=N_POD)
prof("", "replicationcontrollers", pod="spec.template.spec", replicas=True, note=N_POD)
prof("", "resourcequotas")
prof("", "secrets", w=C, d=I, read=C, note="Setting a Secret's data is credential.",
     dnote="A Secret's value is gone once it is deleted; generated keys and certificates cannot be read back.")
prof("", "serviceaccounts")
prof("", "services", service=True,
     note="A LoadBalancer Service exposes the workload and provisions a billed load balancer (access and money); NodePort and external IPs expose it (access).")
prof("", "nodes")
# admissionregistration
for pl in ["mutatingadmissionpolicies", "mutatingadmissionpolicybindings", "mutatingwebhookconfigurations",
           "validatingadmissionpolicies", "validatingadmissionpolicybindings", "validatingwebhookconfigurations"]:
    prof("admissionregistration.k8s.io", pl, w=A, d=A, note=N_ACCESS_ADMISSION, dnote=N_ACCESS_ADMISSION)
prof("apiextensions.k8s.io", "customresourcedefinitions", d=I, dnote="Deleting a CRD deletes every custom resource of its kind.")
prof("apiregistration.k8s.io", "apiservices", w=A, d=A,
     note="An APIService sends every request for its group and version to a service of its own choosing; every change is access.",
     dnote="An APIService sends every request for its group and version to a service of its own choosing; every change is access.")
# apps
prof("apps", "controllerrevisions")
prof("apps", "daemonsets", pod="spec.template.spec", note=N_POD)
prof("apps", "deployments", pod="spec.template.spec", replicas=True, note=N_POD)
prof("apps", "replicasets", pod="spec.template.spec", replicas=True, note=N_POD)
prof("apps", "statefulsets", pod="spec.template.spec", replicas=True, d=I, note=N_POD,
     dnote="A StatefulSet's persistentVolumeClaimRetentionPolicy can delete its volume claims, and their data, with it.")
# reviews change nothing
for pl in ["selfsubjectreviews", "tokenreviews"]:
    prof("authentication.k8s.io", pl, c=R, only_create=True, note="A review answers a question and changes nothing.")
for pl in ["localsubjectaccessreviews", "selfsubjectaccessreviews", "selfsubjectrulesreviews", "subjectaccessreviews"]:
    prof("authorization.k8s.io", pl, c=R, only_create=True, note="A review answers a question and changes nothing.")
prof("autoscaling", "horizontalpodautoscalers")
prof("batch", "cronjobs", pod="spec.jobTemplate.spec.template.spec", note=N_POD)
prof("batch", "jobs", pod="spec.template.spec", note=N_POD)
prof("certificates.k8s.io", "certificatesigningrequests")
prof("certificates.k8s.io", "clustertrustbundles", w=A, d=A, note="Trust bundles decide which certificate authorities workloads trust.",
     dnote="Trust bundles decide which certificate authorities workloads trust.")
prof("certificates.k8s.io", "podcertificaterequests")
prof("coordination.k8s.io", "leases")
prof("coordination.k8s.io", "leasecandidates")
prof("discovery.k8s.io", "endpointslices")
prof("events.k8s.io", "events")
for pl in ["flowschemas", "prioritylevelconfigurations"]:
    prof("flowcontrol.apiserver.k8s.io", pl, w=A, d=A,
         note="API priority and fairness decides whose requests the API server serves; a change can lock users out.",
         dnote="API priority and fairness decides whose requests the API server serves; a change can lock users out.")
prof("internal.apiserver.k8s.io", "storageversions")
prof("lifecycle.k8s.io", "evictionrequests", c=DEL, d=W, note="Requesting an eviction evicts the pod.")
prof("lifecycle.k8s.io", "evictions", c=DEL, d=W, note="An eviction removes the pod.")
prof("networking.k8s.io", "ingressclasses")
prof("networking.k8s.io", "ingresses", w=A, note="An Ingress exposes services outside the cluster.")
prof("networking.k8s.io", "ipaddresses")
prof("networking.k8s.io", "networkpolicies", w=A, d=A, note="Network policies decide which pods may talk to which; every change is access.",
     dnote="Network policies decide which pods may talk to which; every change is access.")
prof("networking.k8s.io", "servicecidrs")
prof("node.k8s.io", "runtimeclasses")
prof("policy", "poddisruptionbudgets")
for pl in ["clusterrolebindings", "clusterroles", "rolebindings", "roles"]:
    prof("rbac.authorization.k8s.io", pl, w=A, d=A, note=N_RBAC, dnote=N_RBAC)
for pl in ["deviceclasses", "devicetaintrules", "resourceclaims", "resourceclaimtemplates", "resourceslices", "resourcepoolstatusrequests"]:
    prof("resource.k8s.io", pl)
for pl in ["priorityclasses", "compositepodgroups", "podgroups", "workloads"]:
    prof("scheduling.k8s.io", pl)
for pl in ["csidrivers", "csinodes", "csistoragecapacities", "storageclasses", "volumeattachments", "volumeattributesclasses"]:
    prof("storage.k8s.io", pl)
prof("storagemigration.k8s.io", "storageversionmigrations")

# Subresources: (group, plural, sub) -> class, note. "status" of anything is a
# write unless listed.
SUB = {
    ("", "pods", "ephemeralcontainers"): (I, "An ephemeral container (kubectl debug) runs code in the pod, with its access, network and data."),
    ("", "pods", "resize"): (W, None),
    ("", "pods", "eviction"): (DEL, "Evicting a pod deletes it, respecting its disruption budget."),
    ("", "pods", "binding"): (W, "Binds the pod to a node, as the scheduler does."),
    ("", "pods", "exec"): (I, "Runs a command in a container, with its access to data, secrets and the network."),
    ("", "pods", "attach"): (I, "Attaches to a running container's input and output, as exec does."),
    ("", "pods", "portforward"): (A, "Opens the pod's ports to the client, past the cluster's network policies."),
    ("", "pods", "proxy"): (U, "Sends a request to the pod's own HTTP API through the API server; Opfence cannot tell what it does."),
    ("", "services", "proxy"): (U, "Sends a request to the service's own HTTP API through the API server; Opfence cannot tell what it does."),
    ("", "nodes", "proxy"): (I, "Reaches the node's kubelet API, which runs commands in any pod on the node."),
    ("", "serviceaccounts", "token"): (C, "Issues a token that authenticates as the service account."),
    ("", "namespaces", "finalize"): (I, "Removing a terminating namespace's finalizers ends its deletion before the cleanup they guard has run."),
    ("certificates.k8s.io", "certificatesigningrequests", "approval"): (C, "Approving a request lets its signer issue a certificate that authenticates as the requested identity."),
    ("certificates.k8s.io", "certificatesigningrequests", "status"): (C, "The status carries the issued certificate; only a signer writes it."),
    ("certificates.k8s.io", "podcertificaterequests", "status"): (C, "The status carries the issued certificate; only a signer writes it."),
}
CONNECT = {"exec", "attach", "portforward", "proxy"}

PATH_RE = re.compile(r'^/(?:api/(v1)|apis/([^/]+)/([^/]+))/(watch/)?(namespaces/\{namespace\}/)?([^/{]+)(/\{name\})?(?:/([^/{]+))?(/\{path\})?$')
METHODS = ["post", "put", "patch", "delete", "get", "head", "options"]

ops = {}  # key -> dict
kinds = {}
for p, item in SPEC["paths"].items():
    m = PATH_RE.match(p)
    if not m:
        continue
    core, group, version, watch, ns, plural, name, sub, pathp = m.groups()
    group = "" if core else group
    if group not in SHORT:
        sys.exit(f"no short name for group {group!r} ({p})")
    for meth in METHODS:
        op = item.get(meth)
        if not op:
            continue
        action = op.get("x-kubernetes-action")
        gvk = op.get("x-kubernetes-group-version-kind") or {}
        if not sub and gvk.get("kind"):
            kinds.setdefault((group, plural), gvk["kind"])
        key = (group, plural, sub or "", bool(ns), bool(name), meth.upper(), bool(pathp), bool(watch), action)
        ops.setdefault(key, set()).add(version or "v1")

def template(group, plural, sub, ns, name, pathp, watch):
    t = "/api/v1" if group == "" else f"/apis/{group}/{{version}}"
    if watch:
        t += "/watch"
    if ns:
        t += "/namespaces/{namespace}"
    if group == "" and plural == "namespaces" and name:
        pass
    t += "/" + plural
    if name:
        t += "/{name}"
    if sub:
        t += "/" + sub
    if pathp:
        t += "/{path*}"
    return t

def kebab(s):
    return re.sub(r"(?<!^)(?=[A-Z])", "-", s).lower()

def singular_kind(group, plural):
    return kinds.get((group, plural), plural)

rules = {}  # short group -> list of rule dicts
seen_profiles, seen_subs = set(), set()

def cond_lines(conds):
    out = []
    for cls, c in conds:
        out += [f"      - if: {c}", f"        class: {cls}"]
    return out

def pod_conds(prefix, ephemeral):
    b = "body." + prefix
    conds = []
    ctypes = ["containers", "initContainers"] + (["ephemeralContainers"] if ephemeral else [])
    for ct in ctypes:
        conds.append((A, f"{{ arg: {b}.{ct}.securityContext.privileged, in: {json.dumps(TRUE)} }}"))
        conds.append((A, f"{{ arg: {b}.{ct}.securityContext.capabilities.add, matches: {CAPS} }}"))
    for f in ["hostNetwork", "hostPID", "hostIPC"]:
        conds.append((A, f"{{ arg: {b}.{f}, in: {json.dumps(TRUE)} }}"))
    conds.append((A, f"{{ arg: {b}.volumes.hostPath, present: true }}"))
    conds.append((A, "{ arg: body.op, present: true }"))
    return conds

# dryRun=All writes nothing. Create, update and patch take it in the query;
# a delete takes it in the DeleteOptions body kubectl sends, and the API
# server reads the query only when there is no body, so a delete's query
# does not count.
DRYRUN = (R, '{ arg: query.dryRun, equals: "All" }')
DRYRUN_DELETE = (R, '{ arg: body.dryRun, equals: "All" }')
NO_SELECTOR = (I, "{ arg: query.labelSelector, empty: true }")

for key in sorted(ops, key=lambda k: (k[0], k[1], k[2], not k[3], k[4], k[5], k[6], k[7])):
    group, plural, sub, ns, name, method, pathp, watch, action = key
    prof_ = P.get((group, plural))
    if prof_ is None:
        sys.exit(f"no profile for {group or 'core'}/{plural}")
    seen_profiles.add((group, plural))
    kind = singular_kind(group, plural)
    short = SHORT[group]
    path = template(group, plural, sub, ns, name, pathp, watch)
    conds, cls, note, verb, card = [], None, None, None, None
    target = "{name}" if name else None
    where = (" in namespace {namespace}" if ns else "") + " on cluster {cluster}"
    res = ("name", kebab(kind)) if name else (("namespace", "namespace") if ns else ("cluster", "cluster"))
    dry = False
    if sub:
        sk = (group, plural, sub)
        seen_subs.add(sk)
        if sub not in CONNECT and method == "GET":
            continue  # reads of subresources (status, scale, log): the provider default
        if sk in SUB:
            cls, note = SUB[sk]
        elif sub == "status":
            cls, note = W, None
        elif sub == "scale":
            cls, note = W, None
        else:
            sys.exit(f"no class for subresource {group or 'core'}/{plural}/{sub}")
        if sub in CONNECT:
            verb = sub + ("-path" if pathp else "") + "." + method.lower()
            card = {
                "exec": f"Run {{query.command}} in {kind} {{name}}{where}",
                "attach": f"Attach to {kind} {{name}}{where}",
                "portforward": f"Forward ports {{query.ports}} of {kind} {{name}}{where}",
                "proxy": f"Send {method} to {kind} {{name}}" + (" at /{path}" if pathp else "") + f" through the API server{where}",
            }[sub]
        else:
            verb = sub + "." + {"PUT": "replace", "PATCH": "patch", "POST": "create"}[method]
            dry = cls != C
            card = {
                "status": f"Change the status of {kind} {{name}}{where}",
                "scale": f"Scale {kind} {{name}} to {{body.spec.replicas}} replicas{where}",
                "ephemeralcontainers": f"Add an ephemeral container to {kind} {{name}}{where}",
                "resize": f"Resize the containers of {kind} {{name}}{where}",
                "eviction": f"Evict {kind} {{name}}{where}",
                "binding": f"Bind {kind} {{name}} to node {{body.target.name}}{where}",
                "token": f"Request a token for {kind} {{name}}{where}",
                "finalize": f"Remove the finalizers of {kind} {{name}}{where}",
                "approval": f"Approve or deny {kind} {{name}}{where}",
            }[sub]
            if sub == "scale":
                conds.append((DEL, '{ arg: body.spec.replicas, equals: "0" }'))
                conds.append((DEL, "{ arg: body.op, present: true }"))
                note = "Scaling to zero replicas takes the workload down (delete). A JSON Patch, whose effect Opfence cannot read, counts as that."
    else:
        if watch or method in ("GET", "HEAD", "OPTIONS"):
            if prof_["read"] is None or method != "GET":
                continue
            cls = prof_["read"]
            verb = ("watch" if watch and name else "watch-list" if watch else "get" if name else "list") + ("" if ns or name else "-all-namespaces")
            card = (("Watch" if watch else "Read" if name else "List") + f" {kind} " + ("{name}" if name else "objects") + where)
            note = "Returns the Secrets' data." if not name else "Returns the Secret's data."
        elif method == "POST":
            cls = prof_["c"]
            verb = "create"
            card = f"Create {kind} {{body.metadata.name}}{where}"
            note = prof_["note"]
            dry = cls != C and cls != R
        elif prof_["only_create"]:
            sys.exit(f"{group}/{plural}: unexpected {method}")
        elif method in ("PUT", "PATCH"):
            cls = prof_["w"]
            verb = "replace" if method == "PUT" else "patch"
            card = ("Replace" if method == "PUT" else "Change") + f" {kind} {{name}}{where}"
            note = prof_["note"] if prof_["w"] != W or prof_["pod"] or prof_["service"] or prof_["replicas"] or plural == "configmaps" else None
            dry = cls != C
        elif method == "DELETE" and name:
            cls = prof_["d"]
            verb = "delete"
            card = f"Delete {kind} {{name}}{where}"
            note = prof_["dnote"] or (N_DELETE if cls == DEL else None)
            dry = True
        elif method == "DELETE":
            cls = prof_["d"]
            verb = "delete-collection"
            card = f"Delete the {plural} matching label selector {{query.labelSelector}}{where}"
            note = ((prof_["dnote"] + " ") if prof_["dnote"] else "") + \
                "Without a label selector every object of the kind" + (" in the namespace" if ns else "") + " is deleted (irreversible)."
            conds.append(NO_SELECTOR)
            dry = True
        else:
            sys.exit(f"unexpected {method} {path}")
        if method in ("POST", "PUT", "PATCH") and prof_["pod"]:
            conds += pod_conds(prof_["pod"], plural == "pods")
        if method in ("POST", "PUT", "PATCH") and prof_["replicas"]:
            conds.append((DEL, '{ arg: body.spec.replicas, equals: "0" }'))
        if method in ("POST", "PUT", "PATCH") and (group, plural) == ("", "configmaps"):
            conds.append((A, '{ arg: name, equals: "aws-auth" }' if name else '{ arg: body.metadata.name, equals: "aws-auth" }'))
        if method == "DELETE" and name and (group, plural) == ("", "configmaps"):
            conds += [(DEL, '{ arg: name, equals: "aws-auth" }'), (A, '{ arg: name, equals: "aws-auth" }')]
            note = N_DELETE + " Deleting kube-system/aws-auth on EKS also takes away the access of every IAM role and user it maps (access)."
        if method in ("POST", "PUT", "PATCH") and prof_["service"]:
            conds += [(A, '{ arg: body.spec.type, equals: "LoadBalancer" }'), (M, '{ arg: body.spec.type, equals: "LoadBalancer" }'),
                      (A, '{ arg: body.spec.type, equals: "NodePort" }'), (A, "{ arg: body.spec.externalIPs, matches: '.' }"),
                      (A, "{ arg: body.op, present: true }")]
        if not name and method == "POST":
            res = ("namespace", "namespace") if ns else ("body.metadata.name", kebab(kind))
            if prof_["only_create"] and prof_["c"] == R:
                res = ("cluster", "cluster")
    if dry:
        conds.append(DRYRUN_DELETE if method == "DELETE" else DRYRUN)
    rid = f"kubernetes.{short}.{plural}.{verb}"
    if any(x["id"] == rid for x in rules.get(short, [])):
        sys.exit(f"duplicate rule id {rid}")
    rules.setdefault(short, []).append(dict(id=rid, method=method, path=path, cls=cls, conds=conds, note=note, card=card,
                                            res=res, group=group, plural=plural, sub=sub, ns=ns, name=name, pathp=pathp,
                                            watch=watch, kind=kind, versions=sorted(ops[key])))

missing = set(P) - seen_profiles
if missing:
    sys.exit(f"profiles for resources the description does not have: {sorted(missing)}")
missing = set(SUB) - seen_subs
if missing:
    sys.exit(f"subresource classes the description does not use: {sorted(missing)}")

# ---------------------------------------------------------------------------
# Fixtures.
SAMPLE_NAME = {"namespaces": "shop", "nodes": "ip-10-0-1-23.ec2.internal", "pods": "web-7c9d8b6f5-x2k4p",
               "secrets": "shop-db-credentials", "deployments": "web", "statefulsets": "postgres",
               "persistentvolumeclaims": "data-postgres-0", "services": "web", "serviceaccounts": "deployer",
               "clusterroles": "agent-admin", "clusterrolebindings": "agent-admin", "roles": "deployer", "rolebindings": "deployer",
               "customresourcedefinitions": "certificates.cert-manager.io", "apiservices": "v1beta1.metrics.k8s.io",
               "certificatesigningrequests": "agent-client"}

def sample_name(plural):
    return SAMPLE_NAME.get(plural, plural[:-1] if plural.endswith("s") else plural)

def api_version(group, versions):
    v = "v1" if "v1" in versions else versions[-1]
    return v if group == "" else f"{group}/{v}"

def fixture_path(r, query="", aws_auth=False):
    v = "v1" if "v1" in r["versions"] else r["versions"][-1]
    ns, name = ("kube-system", "aws-auth") if aws_auth else ("shop", sample_name(r["plural"]))
    p = r["path"].replace("{version}", v).replace("{namespace}", ns).replace("{name}", name)
    p = p.replace("{path*}", "metrics")
    return p + (("?" + query) if query else "")

def body_for(r, extra=None):
    kind = r["kind"]
    if r["sub"] == "scale":
        return extra or {"spec": {"replicas": 3}}
    if r["sub"] == "status":
        return extra or {"status": {"conditions": []}}
    if r["sub"] == "eviction":
        return {"apiVersion": "policy/v1", "kind": "Eviction", "metadata": {"name": sample_name(r["plural"]), "namespace": "shop"}}
    if r["sub"] == "binding" or r["plural"] == "bindings":
        return {"apiVersion": "v1", "kind": "Binding", "metadata": {"name": "web-7c9d8b6f5-x2k4p"}, "target": {"kind": "Node", "name": "ip-10-0-1-23.ec2.internal"}}
    if r["sub"] == "token":
        return {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": {"audiences": ["https://kubernetes.default.svc"], "expirationSeconds": 3600}}
    if r["sub"] == "approval":
        return {"status": {"conditions": [{"type": "Approved", "status": "True", "reason": "AgentApproved"}]}}
    if r["sub"] == "ephemeralcontainers":
        return {"spec": {"ephemeralContainers": [{"name": "debugger", "image": "busybox:1.36", "targetContainerName": "web"}]}}
    if r["sub"] == "resize":
        return {"spec": {"containers": [{"name": "web", "resources": {"limits": {"memory": "512Mi"}}}]}}
    if r["sub"] == "finalize":
        return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "shop"}, "spec": {"finalizers": []}}
    if r["method"] == "PATCH":
        return extra or {"metadata": {"labels": {"team": "shop"}}}
    obj = {"apiVersion": api_version(r["group"], r["versions"]), "kind": kind, "metadata": {"name": sample_name(r["plural"])}}
    if r["ns"]:
        obj["metadata"]["namespace"] = "shop"
    if extra:
        obj.update(extra)
    return obj

files, nfix, fixtures = {}, 0, {}
def write_fixture(name, desc, method, path, host, body=None, ctype="application/json", headers=()):
    binary = isinstance(body, bytes)
    lines = [f"# description: {desc}"] + (["# body: base64"] if binary else []) + \
            [f"{method} {path} HTTP/1.1", f"Host: {host}", "Authorization: Bearer opf_kubernetes_EXAMPLE",
             "Accept: " + (f"{PROTOBUF},application/json" if ctype == PROTOBUF else "application/json")] + list(headers)
    if binary:
        b64 = base64.b64encode(body).decode()
        lines += [f"Content-Type: {ctype}", ""] + [b64[i:i + 76] for i in range(0, len(b64), 76)]
    elif body is not None:
        lines += [f"Content-Type: {ctype}", "", json.dumps(body, separators=(",", ":"))]
    else:
        lines.append("")
    fixtures[name] = "\n".join(lines) + "\n"

def ws_headers(sub):
    proto = "SPDY/3.1+portforward.k8s.io, portforward.k8s.io" if sub == "portforward" else \
        "v5.channel.k8s.io, v4.channel.k8s.io, v3.channel.k8s.io, v2.channel.k8s.io, channel.k8s.io"
    return ["Connection: Upgrade", "Upgrade: websocket", "Sec-WebSocket-Version: 13",
            "Sec-WebSocket-Key: SuGEWJPf09uZBVHb9CtL1Q==", f"Sec-WebSocket-Protocol: {proto}"]

# Protobuf bodies, which kubectl and other Go clients send for built-in
# objects: kubectl's own (recorded from kubectl v1.37.2's create commands),
# and objects client-go encodes, written by tools/kubeprotogen/check.
PROTOBUF = "application/vnd.kubernetes.protobuf"
def pb(path):
    return open(path, "rb").read()
PB_KUBECTL = {n[:-3]: pb("tools/catalog-gen/kubectl-protobuf/" + n) for n in sorted(os.listdir("tools/catalog-gen/kubectl-protobuf"))}
PB_CLIENT = {n[:-3]: pb("internal/decode/testdata/kubeproto/" + n) for n in sorted(os.listdir("internal/decode/testdata/kubeproto")) if n.endswith(".pb")}
KUBECTL_CREATE = "fieldManager=kubectl-create&fieldValidation=Strict"
# rule id -> (suffix, body, class, query) for protobuf fixtures.
PB_TESTS = {
    "kubernetes.apps.deployments.create": [("-protobuf", PB_KUBECTL["create-deployment"], W, KUBECTL_CREATE),
                                           ("-privileged-protobuf", PB_CLIENT["deployment-privileged"], A, "")],
    "kubernetes.batch.cronjobs.create": [("-protobuf", PB_KUBECTL["create-cronjob"], W, KUBECTL_CREATE),
                                         ("-privileged-protobuf", PB_CLIENT["cronjob-privileged"], A, "")],
    "kubernetes.core.pods.create": [("-host-protobuf", PB_CLIENT["pod-host-pid"], A, "")],
    "kubernetes.core.services.create": [("-load-balancer-protobuf", PB_KUBECTL["create-service-loadbalancer"], M, KUBECTL_CREATE)],
    "kubernetes.core.configmaps.create": [("-aws-auth-protobuf", PB_KUBECTL["create-configmap-aws-auth"], A, KUBECTL_CREATE)],
    "kubernetes.apps.deployments.scale.replace": [("-zero-protobuf", PB_CLIENT["scale-zero"], DEL, "")],
}

POD_SPEC_PRIV = {"containers": [{"name": "debug", "image": "busybox:1.36", "securityContext": {"privileged": True}}]}
POD_SPEC_HOST = {"hostNetwork": True, "containers": [{"name": "debug", "image": "busybox:1.36"}],
                 "volumes": [{"name": "root", "hostPath": {"path": "/"}}]}
POD_SPEC = {"containers": [{"name": "web", "image": "ghcr.io/acme/web:1.4.2"}]}

def put_at(prefix, spec):
    out = {}
    cur = out
    parts = prefix.split(".")
    for p_ in parts[:-1]:
        cur[p_] = {}
        cur = cur[p_]
    cur[parts[-1]] = spec
    return out

hostn = 0
out_rules = {}
for short, rs in rules.items():
    L = [f"# Kubernetes API: {short} (" + ("core group, /api/v1" if short == "core" else "/apis/" + rs[0]['group']) + ").",
         "# Generated from Kubernetes' OpenAPI description by tools/catalog-gen/k8sgen.py; classes reviewed by hand.",
         "operations:"]
    for r in rs:
        host = HOSTS[hostn % len(HOSTS)]
        hostn += 1
        base = r["id"][len("kubernetes."):].replace(".", "-")
        L.append(f"  - id: {r['id']}")
        L.append(f"    match: {{ rest: {{ method: {r['method']}, path: \"{r['path']}\" }} }}")
        L.append(f"    class: {r['cls']}")
        if r["conds"]:
            L.append("    when:")
            L += cond_lines(r["conds"])
        L.append(f"    resource: {{ arg: {r['res'][0]}, kind: {r['res'][1]} }}")
        L.append(f"    card: {json.dumps(r['card'])}")
        L += ["    status: verified", f"    verified: {DATE}", "    sources:", f"      - {SRC}"]
        if r["note"]:
            L.append("    notes: >-")
            line = "      "
            for w_ in r["note"].split():
                if len(line) + len(w_) + 1 > 100 and line.strip():
                    L.append(line); line = "      "
                line += ("" if line.strip() == "" else " ") + w_
            L.append(line)
        L.append("    tests:")
        tests = []
        needs_body = r["method"] in ("POST", "PUT", "PATCH") and r["sub"] not in CONNECT
        desc = r["card"].replace("{name}", sample_name(r["plural"])).replace("{namespace}", "shop").replace("{cluster}", host)
        desc = re.sub(r"\{[^}]+\}", lambda m: {"{body.metadata.name}": sample_name(r["plural"]), "{query.command}": '["sh","-c","env"]',
                                                  "{query.ports}": "5432", "{path}": "metrics", "{body.spec.replicas}": "3",
                                                  "{query.labelSelector}": "app=web", "{body.target.name}": "ip-10-0-1-23.ec2.internal"}.get(m.group(0), m.group(0)), desc)
        ctype = "application/merge-patch+json" if r["method"] == "PATCH" else "application/json"
        query = ""
        if r["sub"] == "exec":
            query = "command=sh&command=-c&command=env&container=web&stdin=true&stdout=true&stderr=true&tty=true"
        elif r["sub"] == "attach":
            query = "container=web&stdin=true&stdout=true&tty=true"
        elif r["sub"] == "portforward":
            query = "ports=5432"
        elif r["sub"] == "" and r["method"] == "DELETE" and not r["name"]:
            query = "labelSelector=app%3Dweb"
        res_val = {"name": sample_name(r["plural"]), "namespace": "shop", "cluster": host,
                   "body.metadata.name": sample_name(r["plural"])}[r["res"][0]]
        expect = r["cls"]
        main_body = body_for(r) if needs_body else None
        if needs_body and r["method"] == "POST" and P[(r["group"], r["plural"])]["pod"] and r["sub"] == "":
            main_body = body_for(r, put_at(P[(r["group"], r["plural"])]["pod"], POD_SPEC))
        tests.append(("", query, main_body, expect, ctype, r["method"]))
        # Condition fixtures.
        prof_ = P[(r["group"], r["plural"])]
        if r["sub"] == "" and r["method"] in ("POST", "PUT", "PATCH") and prof_["pod"]:
            spec_priv = put_at(prof_["pod"], POD_SPEC_PRIV)
            spec_host = put_at(prof_["pod"], POD_SPEC_HOST)
            if r["method"] == "PATCH":
                tests.append(("-privileged", "", spec_priv, A, "application/strategic-merge-patch+json", "PATCH"))
                tests.append(("-json-patch", "", [{"op": "add", "path": "/" + prof_["pod"].replace(".", "/") + "/hostNetwork", "value": True}], A, "application/json-patch+json", "PATCH"))
            else:
                tests.append(("-privileged", "", body_for(r, spec_priv), A, ctype, r["method"]))
                tests.append(("-host", "", body_for(r, spec_host), A, ctype, r["method"]))
        if r["sub"] == "" and r["method"] in ("PUT", "PATCH") and prof_["replicas"]:
            b = {"spec": {"replicas": 0}} if r["method"] == "PATCH" else body_for(r, {"spec": {"replicas": 0, "template": {"spec": POD_SPEC}}})
            tests.append(("-zero", "", b, DEL, ctype, r["method"]))
        if r["sub"] == "scale" and r["method"] in ("PUT", "PATCH"):
            tests.append(("-zero", "", {"spec": {"replicas": 0}}, DEL, ctype, r["method"]))
        if r["sub"] == "" and r["method"] == "POST" and prof_["service"]:
            tests.append(("-load-balancer", "", body_for(r, {"spec": {"type": "LoadBalancer", "ports": [{"port": 443}]}}), M, ctype, "POST"))
            tests.append(("-node-port", "", body_for(r, {"spec": {"type": "NodePort", "ports": [{"port": 443}]}}), A, ctype, "POST"))
        if r["sub"] == "" and r["plural"] == "configmaps" and r["method"] == "PATCH":
            tests.append(("-aws-auth", "", {"data": {"mapRoles": "- rolearn: arn:aws:iam::111122223333:role/agent\n  username: agent\n  groups: [system:masters]\n"}}, A, ctype, "PATCH"))
        if r["sub"] == "" and r["plural"] == "configmaps" and r["method"] == "DELETE" and r["name"]:
            tests.append(("-aws-auth", "", None, A, ctype, "DELETE"))
        if r["sub"] == "" and r["method"] == "DELETE" and not r["name"]:
            tests.append(("-every", "", None, I, ctype, "DELETE"))
        if r["sub"] == "" and r["method"] == "DELETE" and r["name"] and r["plural"] in ("namespaces", "deployments", "persistentvolumeclaims"):
            # As kubectl delete --dry-run=server sends it.
            tests.append(("-dry-run", "", {"propagationPolicy": "Background", "dryRun": ["All"]}, R, ctype, "DELETE"))
            # The query does not count when there is a body.
            tests.append(("-dry-run-query", "dryRun=All", {"propagationPolicy": "Background"}, r["cls"], ctype, "DELETE"))
        if r["sub"] == "" and r["method"] == "POST" and r["plural"] in ("pods", "deployments", "services") and r["ns"]:
            tests.append(("-dry-run", "dryRun=All", main_body, R, ctype, "POST"))
        if r["sub"] in ("exec", "attach", "portforward") and r["method"] == "GET":
            # As kubectl opens it: a WebSocket upgrade of the GET.
            tests.append(("-websocket", query, None, r["cls"], ctype, "GET"))
        for suffix, b, exp, q in PB_TESTS.pop(r["id"], []):
            tests.append((suffix, q, b, exp, PROTOBUF, r["method"]))
        for suffix, q, b, exp, ct, meth in tests:
            name = base + suffix + ".http"
            aws_auth = suffix.startswith("-aws-auth")
            d = desc.replace(" configmap in namespace shop", " aws-auth in namespace kube-system") if aws_auth else desc
            write_fixture(name, d + {"": "", "-privileged": ", privileged", "-host": ", on the host's network with the host's root mounted",
                                        "-json-patch": ", by JSON Patch", "-zero": ", to zero replicas", "-load-balancer": ", as a LoadBalancer",
                                        "-node-port": ", as a NodePort", "-every": ", with no label selector", "-dry-run": ", as a dry run",
                                        "-aws-auth": "",
                                        "-dry-run-query": ", with dryRun in the query, which the server ignores beside a body",
                                        "-protobuf": ", in protobuf as kubectl create sends it",
                                        "-privileged-protobuf": ", privileged, in protobuf as client-go sends it",
                                        "-host-protobuf": ", in the host's PID namespace, in protobuf as client-go sends it",
                                        "-load-balancer-protobuf": ", as a LoadBalancer, in protobuf as kubectl create sends it",
                                        "-aws-auth-protobuf": ", in protobuf as kubectl create sends it",
                                        "-zero-protobuf": ", to zero replicas, in protobuf as client-go sends it",
                                        "-websocket": ", opened as a WebSocket as kubectl opens it"}[suffix],
                          meth, fixture_path(r, q, aws_auth=aws_auth), host, b, ct,
                          headers=ws_headers(r["sub"]) if suffix == "-websocket" else ())
            res = res_val
            if aws_auth:
                res = {"name": "aws-auth", "namespace": "kube-system"}.get(r["res"][0], res_val)
            L += [f"      - fixture: fixtures/{name}", f"        expect: {exp}", f"        resource: \"{res}\""]
            nfix += 1
        L.append("")
    out_rules[short] = L

if PB_TESTS:
    sys.exit(f"protobuf fixtures for rules the description does not have: {sorted(PB_TESTS)}")

# ---------------------------------------------------------------------------
# The resource table tool calls are read with (internal/decode/kubeapi.json):
# each resource's group, kind, plural, singular and short names, the versions
# it is served in (preferred first), whether it is namespaced and its
# subresources. Short names are not in the description; these are the API
# server's discovery documents' at the same tag.
SHORT_NAMES = {
    ("", "componentstatuses"): ["cs"], ("", "configmaps"): ["cm"], ("", "endpoints"): ["ep"], ("", "events"): ["ev"],
    ("", "limitranges"): ["limits"], ("", "namespaces"): ["ns"], ("", "nodes"): ["no"],
    ("", "persistentvolumeclaims"): ["pvc"], ("", "persistentvolumes"): ["pv"], ("", "pods"): ["po"],
    ("", "replicationcontrollers"): ["rc"], ("", "resourcequotas"): ["quota"], ("", "serviceaccounts"): ["sa"],
    ("", "services"): ["svc"], ("apps", "daemonsets"): ["ds"], ("apps", "deployments"): ["deploy"],
    ("apps", "replicasets"): ["rs"], ("apps", "statefulsets"): ["sts"], ("autoscaling", "horizontalpodautoscalers"): ["hpa"],
    ("batch", "cronjobs"): ["cj"], ("certificates.k8s.io", "certificatesigningrequests"): ["csr"],
    ("events.k8s.io", "events"): ["ev"], ("networking.k8s.io", "ingresses"): ["ing"], ("networking.k8s.io", "ipaddresses"): ["ip"],
    ("networking.k8s.io", "networkpolicies"): ["netpol"], ("policy", "poddisruptionbudgets"): ["pdb"],
    ("storage.k8s.io", "storageclasses"): ["sc"], ("storage.k8s.io", "volumeattributesclasses"): ["vac"],
    ("apiextensions.k8s.io", "customresourcedefinitions"): ["crd", "crds"], ("scheduling.k8s.io", "priorityclasses"): ["pc"],
}

def version_key(v):
    m = re.match(r"^v(\d+)(?:(alpha|beta)(\d+))?$", v)
    major, stage, minor = int(m.group(1)), m.group(2), int(m.group(3) or 0)
    return (-{None: 2, "beta": 1, "alpha": 0}[stage], -major, -minor)

table = {}
for key, versions in ops.items():
    group, plural, sub, ns, name, method, pathp, watch, action = key
    e = table.setdefault((group, plural), {"group": group, "kind": kinds.get((group, plural), ""), "plural": plural,
                                           "versions": set(), "namespaced": False, "subresources": set()})
    e["versions"] |= versions
    e["namespaced"] |= ns
    if sub:
        e["subresources"].add(sub)
missing = set(SHORT_NAMES) - set(table)
if missing:
    sys.exit(f"short names for resources the description does not have: {sorted(missing)}")
rows = []
for k in sorted(table):
    e = table[k]
    if not e["kind"]:
        sys.exit(f"no kind for {k}")
    rows.append(json.dumps({"group": e["group"], "kind": e["kind"], "plural": e["plural"], "singular": e["kind"].lower(),
                            "short": SHORT_NAMES.get(k, []), "versions": sorted(e["versions"], key=version_key),
                            "namespaced": e["namespaced"], "subresources": sorted(e["subresources"])}, separators=(",", ":")))
open("internal/decode/kubeapi.json", "w").write('{"kubernetes":"' + TAG + '","resources":[\n' + ",\n".join(rows) + "\n]}\n")

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    os.remove(D + "fixtures/" + f)
for f in os.listdir(D):
    if f.endswith(".yaml") and f != "provider.yaml":
        os.remove(D + f)
for name, text in fixtures.items():
    open(D + "fixtures/" + name, "w").write(text)
for short, L in out_rules.items():
    open(D + short + ".yaml", "w").write("\n".join(L))
print(sum(len(rs) for rs in rules.values()), "rules in", len(rules), "files,", nfix, "fixtures")
