"""Write internal/decode/kubeproto.json.gz from Kubernetes' .proto files.

kubectl and other Go clients send built-in objects to the API server as
protobuf (Content-Type application/vnd.kubernetes.protobuf), and the API
server takes them alongside JSON. To read such a body as the JSON object it
stands for, Opfence needs each message's fields: their numbers, JSON names
and types. This script reads every generated.proto of a Kubernetes checkout
and the OpenAPI description of the same tag, and writes:

  kinds:    "apiVersion Kind" -> message, for every kind the description
            lists and every object (a message with ObjectMeta) of the
            groups' older versions, so a client of an older cluster is read
  messages: message -> [[number, JSON name, type, flags], ...], where type
            is a scalar (string, bool, int32, int64, double, bytes), a
            message, or map:<key>:<value>, and flags has r (repeated) and i
            (inline: the message's fields sit in the parent's JSON object,
            as a Volume's VolumeSource does)
  lists:    messages that stand for a JSON array of their items field
            (ExtraValue, Verbs)

Run from the repository root with a checkout of kubernetes/kubernetes at the
tag (the staging/src/k8s.io/api, apimachinery, apiextensions-apiserver and
kube-aggregator folders and api/openapi-spec/swagger.json are enough):

    python3 -I tools/kubeprotogen/gen.py <kubernetes checkout> v1.37.2 internal/decode/kubeproto.json.gz

The JSON names come from the description: a field takes the name of the
property it matches, ignoring case and punctuation, since go-to-protobuf
names a few fields after the Go field (Webhooks, aPIGroup). The script fails
on a property no field carries or a field no property names. Messages of
versions the description no longer has take the names of the same message
in another version; the fields left with only their .proto name (a few in
old versions, all plain lowerCamel) are listed with KUBEPROTO_LIST_UNCHECKED=1.
tools/kubeprotogen/check tests the result against Kubernetes' own encoder.
"""
import gzip
import json
import os
import re
import sys

ROOT, TAG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
STAGING = os.path.join(ROOT, "staging", "src", "k8s.io")
SPEC = json.load(open(os.path.join(ROOT, "api", "openapi-spec", "swagger.json")))

# Folders whose messages are not API objects a client sends: tests,
# webhook payloads and discovery documents.
SKIP = ("apimachinery/pkg/apis/testapigroup", "api/imagepolicy", "api/admission/", "api/apidiscovery")

SCALARS = {"string", "bool", "int32", "int64", "double", "bytes"}
FIELD = re.compile(r"^(optional|repeated|required)\s+(\S+)\s+(\w+)\s*=\s*(\d+)\s*;")
MAPF = re.compile(r"^map<\s*(\S+?)\s*,\s*(\S+?)\s*>\s+(\w+)\s*=\s*(\d+)\s*;")

messages = {}   # full name -> list of (num, name, type, repeated)
lists = set()   # list wrappers
packages = {}   # package -> folder


def parse(path, rel):
    pkg, cur, comments = None, None, []
    for raw in open(path):
        line = raw.strip()
        if line.startswith("//"):
            comments.append(line)
            continue
        if not line:
            comments = []
            continue
        m = re.match(r"^package\s+([\w.]+)\s*;", line)
        if m:
            pkg = m.group(1)
            packages[pkg] = rel
            continue
        m = re.match(r"^message\s+(\w+)\s*\{\s*(\})?", line)
        if m:
            cur = pkg + "." + m.group(1)
            if cur in messages:
                sys.exit(f"duplicate message {cur}")
            messages[cur] = []
            if any("+protobuf.nullable=true" in c for c in comments):
                lists.add(cur)
            if m.group(2):
                cur = None
            comments = []
            continue
        if line == "}":
            cur, comments = None, []
            continue
        if cur is None:
            comments = []
            continue
        m = MAPF.match(line)
        if m:
            k, v, name, num = m.groups()
            messages[cur].append((int(num), name, ("map", k, resolve_later(pkg, v)), False))
            comments = []
            continue
        m = FIELD.match(line)
        if not m:
            sys.exit(f"{path}: cannot read {line!r}")
        label, typ, name, num = m.groups()
        messages[cur].append((int(num), name, resolve_later(pkg, typ), label == "repeated"))
        comments = []


def resolve_later(pkg, typ):
    if typ in SCALARS:
        return typ
    if typ.startswith("."):
        return typ[1:]
    return pkg + "." + typ


for dirpath, _, files in os.walk(STAGING):
    if "generated.proto" not in files:
        continue
    rel = os.path.relpath(dirpath, STAGING).replace(os.sep, "/")
    if any(rel.startswith(s) or (rel + "/").startswith(s) for s in SKIP):
        continue
    parse(os.path.join(dirpath, "generated.proto"), rel)

for name, fields in messages.items():
    for _, fname, typ, _ in fields:
        t = typ[2] if isinstance(typ, tuple) else typ
        if t not in SCALARS and t not in messages:
            sys.exit(f"{name}.{fname}: no message {t}")
for name in lists:
    f = messages[name]
    if len(f) != 1 or f[0][1] != "items" or not f[0][3]:
        sys.exit(f"{name}: a nullable message other than a list of items")


def defname(msg):
    # io.k8s.api.core.v1.Pod <-> k8s.io.api.core.v1.Pod
    return "io.k8s." + msg[len("k8s.io."):].replace("apiextensions_apiserver", "apiextensions-apiserver").replace("kube_aggregator", "kube-aggregator")


def msgname(defn):
    return "k8s.io." + defn[len("io.k8s."):].replace("apiextensions-apiserver", "apiextensions_apiserver").replace("kube-aggregator", "kube_aggregator")


DEFS = SPEC["definitions"]
# Messages whose JSON form is not an object of their fields; the decoder
# writes them as the API's JSON does.
SPECIAL = {
    "k8s.io.apimachinery.pkg.api.resource.Quantity", "k8s.io.apimachinery.pkg.util.intstr.IntOrString",
    "k8s.io.apimachinery.pkg.apis.meta.v1.Time", "k8s.io.apimachinery.pkg.apis.meta.v1.MicroTime",
    "k8s.io.apimachinery.pkg.apis.meta.v1.Duration", "k8s.io.apimachinery.pkg.runtime.RawExtension",
    "k8s.io.apimachinery.pkg.apis.meta.v1.FieldsV1",
    "k8s.io.apiextensions_apiserver.pkg.apis.apiextensions.v1.JSON",
    "k8s.io.apiextensions_apiserver.pkg.apis.apiextensions.v1beta1.JSON",
}
for v in ("v1", "v1beta1"):
    for s in ("JSONSchemaPropsOrArray", "JSONSchemaPropsOrBool", "JSONSchemaPropsOrStringArray"):
        SPECIAL.add(f"k8s.io.apiextensions_apiserver.pkg.apis.apiextensions.{v}.{s}")
for s in SPECIAL:
    if s not in messages:
        sys.exit(f"no message {s}")


# JSON names and inline fields, from the description: a field is named as
# the property it matches, ignoring case and punctuation (go-to-protobuf
# names a few fields after the Go field, such as Webhooks, aPIGroup and
# JSONSchemaProps' xKubernetesListType for x-kubernetes-list-type); a field no property
# names is inline when its message's fields, themselves expanded, all are.
# Checked both ways for every message with a definition.
inline = set()   # (msg, field name)
rename = {}      # (msg, proto name) -> JSON name
problems = []


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def expand(msg, props, ren, inl, seen):
    """The properties a message's fields cover when inline, or None; the
    names and inline fields it takes go in ren and inl, the messages it
    reads in seen."""
    seen.add(msg)
    lower = {norm(q): q for q in props}
    out = set()
    for _, name, typ, rep in messages[msg]:
        p = lower.get(norm(name))
        if p is not None:
            out.add(p)
            if p != name:
                ren[(msg, name)] = p
            continue
        if isinstance(typ, str) and typ in messages and not rep:
            sub = expand(typ, props, ren, inl, seen)
            if sub:
                inl.add((msg, name))
                out |= sub
                continue
        return None
    return out


checked = set()
for msg, fields in messages.items():
    d = DEFS.get(defname(msg))
    if d is None or msg in SPECIAL or msg in lists or d.get("type") not in (None, "object") or "properties" not in d:
        continue
    checked.add(msg)
    props = set(d["properties"])
    ren, inl, seen = {}, set(), set()
    covered = expand(msg, props, ren, inl, seen)
    if covered is None:
        # Name the fields that matched nothing.
        lower = {norm(p): p for p in props}
        for _, name, typ, rep in fields:
            if norm(name) not in lower and not (isinstance(typ, str) and typ in messages and not rep and expand(typ, props, {}, set(), set())):
                problems.append(f"{msg}.{name}: not a property of {defname(msg)}")
        continue
    for k, v in ren.items():
        if rename.setdefault(k, v) != v:
            problems.append(f"{k[0]}.{k[1]}: named {rename[k]} and {v}")
    inline |= inl
    checked |= seen
    missing = props - covered - {"apiVersion", "kind"}
    for p in sorted(missing):
        problems.append(f"{defname(msg)}.{p}: no field of {msg}")
if problems:
    sys.exit("\n".join(problems))

# Kinds: what the description lists, and every object of the groups'
# other versions (a message with an ObjectMeta field named metadata).
kinds = {}
group_of = {}  # package -> group
for dname, d in DEFS.items():
    for gvk in d.get("x-kubernetes-group-version-kind", []):
        msg = msgname(dname)
        if msg not in messages:
            continue
        api = gvk["version"] if not gvk["group"] else gvk["group"] + "/" + gvk["version"]
        kinds[f"{api} {gvk['kind']}"] = msg
        pkg = msg.rsplit(".", 1)[0]
        if pkg.startswith("k8s.io.apimachinery"):
            continue
        g = group_of.setdefault(pkg, gvk["group"])
        if g != gvk["group"]:
            sys.exit(f"{pkg}: groups {g} and {gvk['group']}")
groups = {}  # folder without version -> group
for pkg, g in group_of.items():
    groups[packages[pkg].rsplit("/", 1)[0]] = g
OBJMETA = "k8s.io.apimachinery.pkg.apis.meta.v1.ObjectMeta"
for msg, fields in messages.items():
    pkg, kind = msg.rsplit(".", 1)
    rel = packages[pkg]
    base, version = rel.rsplit("/", 1)
    if base not in groups or rel.startswith("apimachinery"):
        continue
    if any(f[1] == "metadata" and f[2] == OBJMETA for f in fields):
        g = groups[base]
        api = version if not g else g + "/" + version
        kinds.setdefault(f"{api} {kind}", msg)

# Keep the messages the kinds reach.
keep, todo = set(), list(set(kinds.values()))
while todo:
    m = todo.pop()
    if m in keep:
        continue
    keep.add(m)
    for _, _, typ, _ in messages[m]:
        t = typ[2] if isinstance(typ, tuple) else typ
        if t in messages and t not in keep:
            todo.append(t)


# Messages the description does not have (older versions, and messages
# only ever inline) take the names of the same message in another version
# of the group, field by field.
unverified = []
for m in sorted(keep):
    if m in checked or m in SPECIAL or m in lists:
        continue
    pkg, name = m.rsplit(".", 1)
    base = packages[pkg].rsplit("/", 1)[0]
    sib = [c for c in checked if c.rsplit(".", 1)[1] == name and packages[c.rsplit(".", 1)[0]].rsplit("/", 1)[0] == base]
    for num, fname, typ, rep in messages[m]:
        hits = {(rename.get((c, fname), fname), (c, fname) in inline) for c in sib if any(f[0] == num and f[1] == fname for f in messages[c])}
        if len(hits) > 1:
            sys.exit(f"{m}.{fname}: siblings disagree: {hits}")
        if hits:
            j, inl = hits.pop()
            if j != fname:
                rename[(m, fname)] = j
            if inl:
                inline.add((m, fname))
        else:
            unverified.append(f"{m}.{fname}")
if os.environ.get("KUBEPROTO_LIST_UNCHECKED"):
    print("\n".join(unverified))


def short(m):
    return m[len("k8s.io."):] if m.startswith("k8s.io.") else m


out = {"kubernetes": TAG, "kinds": {k: short(v) for k, v in sorted(kinds.items())},
       "lists": sorted(short(m) for m in lists if m in keep),
       "special": sorted(short(m) for m in SPECIAL if m in keep),
       "messages": {}}
for m in sorted(keep):
    rows = []
    for num, name, typ, rep in sorted(messages[m]):
        if isinstance(typ, tuple):
            v = typ[2] if typ[2] in SCALARS else short(typ[2])
            t = f"map:{typ[1]}:{v}"
        else:
            t = typ if typ in SCALARS else short(typ)
        flags = ("r" if rep else "") + ("i" if (m, name) in inline else "")
        jname = rename.get((m, name), name)
        rows.append([num, jname, t, flags] if flags else [num, jname, t])
    out["messages"][short(m)] = rows

data = json.dumps(out, separators=(",", ":"), sort_keys=False).encode()
with gzip.GzipFile(OUT, "wb", mtime=0) as f:
    f.write(data)
print(f"{len(out['kinds'])} kinds, {len(out['messages'])} messages, {sum(len(v) for v in out['messages'].values())} fields, "
      f"{len(inline)} inline fields, {len(unverified)} fields named as in the .proto file only; "
      f"{len(data)} bytes, {os.path.getsize(OUT)} gzipped")
