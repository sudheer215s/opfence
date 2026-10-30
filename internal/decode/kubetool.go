package decode

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"

	"go.yaml.in/yaml/v3"
)

// kubeAPIData is the resource table of Kubernetes' built-in API, written by
// tools/catalog-gen/k8sgen.py from the OpenAPI description.
//
//go:embed kubeapi.json
var kubeAPIData []byte

// KubeResource is one resource of the Kubernetes API.
type KubeResource struct {
	Group        string   `json:"group"`
	Kind         string   `json:"kind"`
	Plural       string   `json:"plural"`
	Singular     string   `json:"singular"`
	Short        []string `json:"short"`
	Versions     []string `json:"versions"` // preferred first
	Namespaced   bool     `json:"namespaced"`
	Subresources []string `json:"subresources"`
}

var kubeAPI = sync.OnceValues(func() ([]*KubeResource, error) {
	var t struct {
		Resources []*KubeResource `json:"resources"`
	}
	if err := json.Unmarshal(kubeAPIData, &t); err != nil {
		return nil, err
	}
	return t.Resources, nil
})

// Kubernetes tool actions: what a tool call asks of the API, which
// KubeToolOps turns into the requests kubectl or a client library would
// make. The catalog's classify.kubernetes names one, or the argument that
// does.
const (
	KubeGet       = "get"         // read an object, or list without a name
	KubeList      = "list"        // list, across namespaces without one
	KubeCreate    = "create"      // POST the object
	KubeReplace   = "replace"     // PUT the object
	KubeApply     = "apply"       // create or update: POST and PATCH both
	KubePatch     = "patch"       // PATCH with the patch argument
	KubeDelete    = "delete"      // DELETE the object, or the collection without a name
	KubeScale     = "scale"       // PATCH the scale subresource; a read without replicas
	KubeExec      = "exec"        // run a command in a pod
	KubeAttach    = "attach"      // attach to a pod's container
	KubeLogs      = "logs"        // read a pod's log
	KubePortFwd   = "portforward" // forward a pod's ports
	KubeRun       = "run"         // create a pod from an image
	KubeLabel     = "label"       // label or annotate: PATCH the object's metadata
	KubeRestart   = "restart"     // rollout restart: PATCH the pod template's annotations
	KubeUndo      = "undo"        // rollout undo: PATCH the template back to one Opfence cannot see
	KubePause     = "pause"       // rollout pause
	KubeResume    = "resume"      // rollout resume
	KubeCordon    = "cordon"      // mark a node unschedulable
	KubeUncordon  = "uncordon"    // mark it schedulable
	KubeDrain     = "drain"       // cordon a node and evict its pods
	KubeUnknown   = "unknown"     // an action Opfence does not read
	kubeAliasRead = "read"        // the EKS MCP server's name for get
	kubeAliasDesc = "describe"    // kubectl describe: a get
)

// KubeActions lists the actions classify.kubernetes may name.
var KubeActions = []string{KubeGet, KubeList, KubeCreate, KubeReplace, KubeApply, KubePatch, KubeDelete, KubeScale,
	KubeExec, KubeAttach, KubeLogs, KubePortFwd, KubeRun, KubeLabel, KubeRestart, KubeUndo, KubePause, KubeResume,
	KubeCordon, KubeUncordon, KubeDrain, KubeUnknown, kubeAliasRead, kubeAliasDesc}

// KubeNoNamespace stands for the namespace a tool call leaves to the
// server's kubeconfig, and KubeAllNamespaces for every namespace. Neither
// is a valid namespace name, so neither can be mapped to an environment by
// mistake.
const (
	KubeNoNamespace   = "@kubeconfig"
	KubeAllNamespaces = "@all"
	KubeNoCluster     = "@kubeconfig"
)

// KubeCall is a Kubernetes tool call's arguments, as the catalog names
// them; each is the argument's value, or nil when the call leaves it out.
type KubeCall struct {
	Action                              string
	APIVersion, Kind, Resource, Name    any
	Namespace, AllNamespaces, Selector  any
	Manifest, Object, Patch, PatchType  any
	Replicas, Command, Container, Ports any
	Image, Context, ServiceType, DryRun any
}

// KubeStep is one API request a tool call makes, as an operation for the
// provider's REST rules, or why Opfence cannot tell what it is.
type KubeStep struct {
	Op     *Operation
	Reason string
}

// KubeToolOps returns the requests a Kubernetes tool call makes. Every
// step the call needs is there; what Opfence cannot read (a kind that is
// not built in, a manifest it cannot parse, an argument of the wrong type)
// is a step with a reason, which the engine decides as unknown.
func KubeToolOps(c KubeCall) []KubeStep {
	targets, why := kubeTargets(c)
	if why != "" {
		return []KubeStep{{Reason: why}}
	}
	cluster := KubeNoCluster
	if s, ok := c.Context.(string); ok && s != "" {
		cluster = s
	}
	var out []KubeStep
	for _, t := range targets {
		if t.reason != "" {
			out = append(out, KubeStep{Reason: t.reason})
			continue
		}
		for _, st := range kubeActionOps(c, t) {
			if st.Op != nil {
				st.Op.Args["cluster"] = cluster
			}
			out = append(out, st)
		}
	}
	if len(out) == 0 {
		return []KubeStep{{Reason: "the call names no object"}}
	}
	return out
}

// kubeTarget is one object a call acts on.
type kubeTarget struct {
	res       *KubeResource
	version   string
	namespace string // "" for cluster-scoped resources
	name      string
	object    map[string]any // from a manifest or object argument
	reason    string         // set when the object cannot be read
}

// kubeTargets resolves what a call acts on: the objects of its manifest or
// object argument, or the resource its kind or resource name gives.
func kubeTargets(c KubeCall) ([]kubeTarget, string) {
	ns, err := optString(c.Namespace, "namespace")
	if err != nil {
		return nil, err.Error()
	}
	all, _ := c.AllNamespaces.(bool)
	if c.AllNamespaces != nil {
		if _, ok := c.AllNamespaces.(bool); !ok {
			return nil, "allNamespaces is not a boolean"
		}
	}
	var objects []map[string]any
	switch {
	case c.Manifest != nil && c.Action != KubePatch:
		s, ok := c.Manifest.(string)
		if !ok {
			return nil, "the manifest is not text"
		}
		objs, err := ParseKubeManifest(s)
		if err != nil {
			return nil, "the manifest cannot be read: " + err.Error()
		}
		objects = objs
	case c.Object != nil && c.Action != KubePatch:
		obj, ok := c.Object.(map[string]any)
		if !ok {
			if s, isText := c.Object.(string); isText {
				objs, err := ParseKubeManifest(s)
				if err != nil || len(objs) != 1 {
					return nil, "the object cannot be read"
				}
				obj = objs[0]
			} else {
				return nil, "the object is not an object"
			}
		}
		objects = []map[string]any{fillObject(obj, c)}
	}
	if objects != nil {
		var out []kubeTarget
		for _, obj := range objects {
			out = append(out, objectTarget(c, obj, ns))
		}
		if len(out) == 0 {
			return nil, "the manifest holds no object"
		}
		return out, ""
	}
	name, err := optString(c.Name, "name")
	if err != nil {
		return nil, err.Error()
	}
	var cands []*KubeResource
	version := ""
	switch {
	case c.Kind != nil:
		kind, err := optString(c.Kind, "kind")
		if err != nil {
			return nil, err.Error()
		}
		apiVersion, err := optString(c.APIVersion, "apiVersion")
		if err != nil {
			return nil, err.Error()
		}
		cands, version = KubeResourcesByKind(apiVersion, kind)
		if len(cands) == 0 {
			return nil, fmt.Sprintf("%s %s is not a built-in kind", apiVersion, kind)
		}
	case c.Resource != nil:
		r, err := optString(c.Resource, "resource type")
		if err != nil {
			return nil, err.Error()
		}
		// kubectl takes "deployment/web" as well as a type and a name.
		if t, n, ok := strings.Cut(r, "/"); ok && name == "" {
			r, name = t, n
		}
		cands, version = KubeResourcesByName(r)
		if len(cands) == 0 {
			return nil, fmt.Sprintf("%q is not a built-in resource type", r)
		}
	default:
		switch c.Action {
		case KubeExec, KubeAttach, KubeLogs, KubePortFwd, KubeRun:
			cands, version = KubeResourcesByName("pods")
		case KubeCordon, KubeUncordon, KubeDrain:
			cands, version = KubeResourcesByName("nodes")
		default:
			return nil, "the call names no kind or resource type"
		}
	}
	var out []kubeTarget
	for _, r := range cands {
		t := kubeTarget{res: r, version: version, name: name}
		if t.version == "" {
			t.version = r.Versions[0]
		}
		if r.Namespaced {
			switch {
			case all:
				t.namespace = KubeAllNamespaces
			case ns != "":
				t.namespace = ns
			case c.Action == KubeList || (c.Action == KubeGet && name == ""):
				// Listing without a namespace lists every one.
				t.namespace = KubeAllNamespaces
			default:
				t.namespace = KubeNoNamespace
			}
		}
		out = append(out, t)
	}
	return out, ""
}

// fillObject completes an object argument with the kind, apiVersion, name
// and namespace the call gives beside it (the EKS MCP server takes the body
// without them), keeping what the object says itself.
func fillObject(obj map[string]any, c KubeCall) map[string]any {
	out := make(map[string]any, len(obj)+2)
	for k, v := range obj {
		out[k] = v
	}
	for key, v := range map[string]any{"apiVersion": c.APIVersion, "kind": c.Kind} {
		if s, ok := v.(string); ok && s != "" && out[key] == nil {
			out[key] = s
		}
	}
	meta := map[string]any{}
	if m, ok := out["metadata"].(map[string]any); ok {
		for k, v := range m {
			meta[k] = v
		}
	}
	for key, v := range map[string]any{"name": c.Name, "namespace": c.Namespace} {
		if s, ok := v.(string); ok && s != "" && meta[key] == nil {
			meta[key] = s
		}
	}
	out["metadata"] = meta
	return out
}

// objectTarget reads one object of a manifest.
func objectTarget(c KubeCall, obj map[string]any, ns string) kubeTarget {
	apiVersion, _ := obj["apiVersion"].(string)
	kind, _ := obj["kind"].(string)
	if kind == "" {
		return kubeTarget{reason: "an object without a kind"}
	}
	rs, version := KubeResourcesByKind(apiVersion, kind)
	if len(rs) != 1 || apiVersion == "" {
		return kubeTarget{reason: fmt.Sprintf("%s %s is not a built-in kind", apiVersion, kind)}
	}
	t := kubeTarget{res: rs[0], version: version, object: obj}
	meta, _ := obj["metadata"].(map[string]any)
	t.name, _ = meta["name"].(string)
	if rs[0].Namespaced {
		t.namespace, _ = meta["namespace"].(string)
		if t.namespace == "" {
			t.namespace = ns
		}
		if t.namespace == "" {
			t.namespace = KubeNoNamespace
		}
	}
	return t
}

// kubeActionOps builds the requests one action makes on one target.
func kubeActionOps(c KubeCall, t kubeTarget) []KubeStep {
	need := func(what string) []KubeStep {
		return []KubeStep{{Reason: fmt.Sprintf("%s of %s needs %s", c.Action, t.res.Plural, what)}}
	}
	body := func() any {
		if t.object != nil {
			return t.object
		}
		// A create named by type and name (kubectl create configmap x):
		// the object as far as the call tells.
		meta := map[string]any{}
		if t.name != "" {
			meta["name"] = t.name
		}
		if t.namespace != "" {
			meta["namespace"] = t.namespace
		}
		obj := map[string]any{"apiVersion": kubeAPIVersion(t.res, t.version), "kind": t.res.Kind, "metadata": meta}
		if st, ok := c.ServiceType.(string); ok && t.res.Plural == "services" {
			// kubectl create service loadbalancer
			types := map[string]string{"clusterip": "ClusterIP", "nodeport": "NodePort", "loadbalancer": "LoadBalancer", "externalname": "ExternalName"}
			typ := types[strings.ToLower(st)]
			if typ == "" {
				typ = st
			}
			obj["spec"] = map[string]any{"type": typ}
		}
		return obj
	}
	steps := kubeActionSteps(c, t, need, body)
	if dry, _ := c.DryRun.(bool); dry {
		// Nothing is written: the server checks the request and stops.
		for _, st := range steps {
			if st.Op == nil {
				continue
			}
			switch st.Op.Method {
			case "POST", "PUT", "PATCH":
				q, _ := st.Op.Args["query"].(map[string]any)
				q["dryRun"] = "All"
			case "DELETE":
				st.Op.Args["body"] = map[string]any{"dryRun": []any{"All"}}
			}
		}
	}
	return steps
}

// kubeActionSteps builds the requests of one action.
func kubeActionSteps(c KubeCall, t kubeTarget, need func(string) []KubeStep, body func() any) []KubeStep {
	switch c.Action {
	case KubeGet, kubeAliasRead, kubeAliasDesc:
		if t.name == "" {
			return []KubeStep{kubeOp("GET", t, "", "", nil, nil)}
		}
		return []KubeStep{kubeOp("GET", t, t.name, "", nil, nil)}
	case KubeList:
		return []KubeStep{kubeOp("GET", t, "", "", kubeSelector(c), nil)}
	case KubeCreate:
		return []KubeStep{kubeOp("POST", t, "", "", nil, body())}
	case KubeReplace:
		if t.name == "" {
			return need("a name")
		}
		return []KubeStep{kubeOp("PUT", t, t.name, "", nil, body())}
	case KubeApply:
		steps := []KubeStep{kubeOp("POST", t, "", "", nil, body())}
		if t.name != "" {
			steps = append(steps, kubeOp("PATCH", t, t.name, "", nil, body()))
		}
		return steps
	case KubePatch:
		if t.name == "" {
			return need("a name")
		}
		p, err := kubePatchBody(c.Patch, c.PatchType)
		if err != nil {
			return []KubeStep{{Reason: "the patch cannot be read: " + err.Error()}}
		}
		return []KubeStep{kubeOp("PATCH", t, t.name, "", nil, p)}
	case KubeDelete:
		if t.name == "" {
			q := kubeSelector(c)
			if q == nil {
				q = url.Values{}
			}
			return []KubeStep{kubeOp("DELETE", t, "", "", q, nil)}
		}
		return []KubeStep{kubeOp("DELETE", t, t.name, "", nil, nil)}
	case KubeScale:
		if t.name == "" {
			return need("a name")
		}
		if !slices.Contains(t.res.Subresources, "scale") {
			return []KubeStep{{Reason: t.res.Plural + " cannot be scaled"}}
		}
		if c.Replicas == nil {
			return []KubeStep{kubeOp("GET", t, t.name, "scale", nil, nil)}
		}
		n, ok := kubeInt(c.Replicas)
		if !ok {
			return []KubeStep{{Reason: "replicas is not a whole number"}}
		}
		return []KubeStep{kubeOp("PATCH", t, t.name, "scale", nil, map[string]any{"spec": map[string]any{"replicas": json.Number(strconv.FormatInt(n, 10))}})}
	case KubeExec, KubeAttach, KubeLogs, KubePortFwd:
		if t.name == "" {
			return need("a name")
		}
		// kubectl exec deploy/web runs in one of the workload's pods.
		pods, _ := KubeResourcesByName("pods")
		p := kubeTarget{res: pods[0], version: "v1", namespace: t.namespace, name: t.name}
		if t.namespace == "" {
			p.namespace = KubeNoNamespace
		}
		q := url.Values{}
		if s, ok := c.Container.(string); ok && s != "" {
			q.Set("container", s)
		}
		switch c.Action {
		case KubeExec:
			cmd, ok := kubeStrings(c.Command)
			if !ok {
				return []KubeStep{{Reason: "the command is not text or a list of words"}}
			}
			q["command"] = cmd
			return []KubeStep{kubeOp("POST", p, p.name, "exec", q, nil)}
		case KubeAttach:
			return []KubeStep{kubeOp("POST", p, p.name, "attach", q, nil)}
		case KubeLogs:
			return []KubeStep{kubeOp("GET", p, p.name, "log", q, nil)}
		}
		if ports, ok := kubeStrings(c.Ports); ok && len(ports) > 0 {
			q["ports"] = ports
		}
		return []KubeStep{kubeOp("POST", p, p.name, "portforward", q, nil)}
	case KubeRun:
		image, _ := c.Image.(string)
		name := t.name
		if name == "" {
			name = "run"
		}
		container := map[string]any{"name": name, "image": image}
		steps := []KubeStep{kubeOp("POST", t, "", "", nil, map[string]any{"apiVersion": "v1", "kind": "Pod",
			"metadata": map[string]any{"name": name}, "spec": map[string]any{"containers": []any{container}}})}
		if c.Ports != nil {
			// With a port, the Kubernetes MCP server also makes a Service,
			// and on OpenShift a Route that publishes it.
			steps = append(steps, kubeOp("POST", kubeTarget{res: kubeServices(), version: "v1", namespace: t.namespace}, "", "", nil,
				map[string]any{"apiVersion": "v1", "kind": "Service", "metadata": map[string]any{"name": name}, "spec": map[string]any{"type": "ClusterIP"}}),
				KubeStep{Reason: "on OpenShift a Route publishes the port, and Routes are not built in"})
		}
		return steps
	case KubeLabel:
		if t.name == "" {
			return need("a name")
		}
		return []KubeStep{kubeOp("PATCH", t, t.name, "", nil, map[string]any{"metadata": map[string]any{}})}
	case KubeRestart, KubePause, KubeResume, KubeUndo:
		if t.name == "" {
			return need("a name")
		}
		var patch any
		switch c.Action {
		case KubeRestart:
			patch = map[string]any{"spec": map[string]any{"template": map[string]any{"metadata": map[string]any{
				"annotations": map[string]any{"kubectl.kubernetes.io/restartedAt": "now"}}}}}
		case KubePause, KubeResume:
			patch = map[string]any{"spec": map[string]any{"paused": c.Action == KubePause}}
		case KubeUndo:
			st := kubeOp("PATCH", t, t.name, "", nil, nil)
			// The template it restores is a revision's, not the call's.
			st.Op.BodyErr = "rollout undo restores a pod template that is not in the call"
			return []KubeStep{st}
		}
		return []KubeStep{kubeOp("PATCH", t, t.name, "", nil, patch)}
	case KubeCordon, KubeUncordon, KubeDrain:
		if t.res.Plural != "nodes" || t.name == "" {
			return need("a node's name")
		}
		steps := []KubeStep{kubeOp("PATCH", t, t.name, "", nil, map[string]any{"spec": map[string]any{"unschedulable": c.Action != KubeUncordon}})}
		if c.Action == KubeDrain {
			// Every pod on the node is evicted.
			pods, _ := KubeResourcesByName("pods")
			p := kubeTarget{res: pods[0], version: "v1", namespace: KubeAllNamespaces, name: "@" + t.name}
			steps = append(steps, kubeOp("POST", p, p.name, "eviction", nil, map[string]any{"apiVersion": "policy/v1", "kind": "Eviction"}))
		}
		return steps
	}
	return []KubeStep{{Reason: fmt.Sprintf("Opfence does not read the action %q", c.Action)}}
}

// kubeOp is a REST operation on a target's path.
func kubeOp(method string, t kubeTarget, name, sub string, q url.Values, body any) KubeStep {
	p := "/api/v1"
	if t.res.Group != "" {
		p = "/apis/" + t.res.Group + "/" + t.version
	}
	if t.namespace != "" && !(t.namespace == KubeAllNamespaces && name == "" && method == "GET") {
		p += "/namespaces/" + url.PathEscape(t.namespace)
	}
	p += "/" + t.res.Plural
	if name != "" {
		p += "/" + url.PathEscape(name)
	}
	if sub != "" {
		p += "/" + sub
	}
	query, err := formArgs(q)
	if err != nil {
		query = valuesToMap(q)
	}
	if query == nil {
		query = map[string]any{}
	}
	args := map[string]any{"query": query}
	if body != nil {
		args["body"] = body
	}
	return KubeStep{Op: &Operation{Protocol: REST, Method: method, Path: p, Args: args}}
}

func kubeSelector(c KubeCall) url.Values {
	s, ok := c.Selector.(string)
	if !ok || s == "" {
		return nil
	}
	return url.Values{"labelSelector": {s}}
}

// kubePatchBody reads a patch argument: JSON or YAML text, or an object or
// list already parsed. A JSON Patch is a list of operations.
func kubePatchBody(p, typ any) (any, error) {
	if p == nil {
		return nil, errors.New("no patch")
	}
	if s, ok := p.(string); ok {
		docs, err := parseYAMLDocs(s)
		if err != nil {
			return nil, err
		}
		if len(docs) != 1 {
			return nil, errors.New("not one document")
		}
		p = docs[0]
	}
	switch p.(type) {
	case map[string]any, []any:
	default:
		return nil, errors.New("not an object or a list")
	}
	if t, _ := typ.(string); t == "json" {
		if _, ok := p.([]any); !ok {
			return nil, errors.New("a JSON Patch is a list of operations")
		}
	}
	return p, nil
}

// KubeResourcesByKind finds the resources of a kind, in the group an
// apiVersion names ("apps/v1"; "v1" is the core group; "" any group), and
// the version to use: the apiVersion's, or "" for each one's preferred.
func KubeResourcesByKind(apiVersion, kind string) ([]*KubeResource, string) {
	all, err := kubeAPI()
	if err != nil || kind == "" {
		return nil, ""
	}
	group, version, hasGroup := "", apiVersion, apiVersion != ""
	if g, v, ok := strings.Cut(apiVersion, "/"); ok {
		group, version = g, v
	}
	var out []*KubeResource
	for _, r := range all {
		if strings.EqualFold(r.Kind, kind) && (!hasGroup || r.Group == group) {
			out = append(out, r)
		}
	}
	if hasGroup && !kubeVersionRe.MatchString(version) {
		return nil, ""
	}
	return out, version
}

var kubeVersionRe = regexp.MustCompile(`^v[1-9][0-9]*((alpha|beta)[1-9][0-9]*)?$`)

// KubeResourcesByName finds the resources kubectl's resource argument
// names: a plural, singular, short name or kind, optionally followed by
// ".group" or ".version.group" (deployments.apps, deploy.v1.apps). A name
// several groups serve (events) gives each.
func KubeResourcesByName(name string) ([]*KubeResource, string) {
	all, err := kubeAPI()
	if err != nil {
		return nil, ""
	}
	name = strings.ToLower(strings.TrimSpace(name))
	if name == "all" {
		// kubectl's "all" category: the workloads and their services.
		var out []*KubeResource
		for _, n := range []string{"pods", "services", "replicationcontrollers", "daemonsets", "deployments", "replicasets",
			"statefulsets", "horizontalpodautoscalers", "cronjobs", "jobs"} {
			rs, _ := KubeResourcesByName(n)
			out = append(out, rs...)
		}
		return out, ""
	}
	base, rest, qualified := strings.Cut(name, ".")
	group, version := "", ""
	if qualified {
		group = rest
		if v, g, ok := strings.Cut(rest, "."); ok && kubeVersionRe.MatchString(v) {
			version, group = v, g
		}
	}
	var out []*KubeResource
	for _, r := range all {
		if qualified && r.Group != group {
			continue
		}
		if r.Plural == base || r.Singular == base || strings.ToLower(r.Kind) == base || slices.Contains(r.Short, base) {
			out = append(out, r)
		}
	}
	return out, version
}

func kubeServices() *KubeResource {
	rs, _ := KubeResourcesByName("services")
	return rs[0]
}

func kubeAPIVersion(r *KubeResource, version string) string {
	if r.Group == "" {
		return version
	}
	return r.Group + "/" + version
}

// ParseKubeManifest reads YAML or JSON text holding one or more objects
// (YAML documents, or a List's items) as JSON values. Numbers become
// json.Number, as in JSON bodies; a key repeated in a mapping is an error.
func ParseKubeManifest(s string) ([]map[string]any, error) {
	docs, err := parseYAMLDocs(s)
	if err != nil {
		return nil, err
	}
	var out []map[string]any
	for _, d := range docs {
		if d == nil {
			continue
		}
		obj, ok := d.(map[string]any)
		if !ok {
			return nil, errors.New("a document is not an object")
		}
		if kind, _ := obj["kind"].(string); strings.HasSuffix(kind, "List") && obj["items"] != nil {
			items, ok := obj["items"].([]any)
			if !ok {
				return nil, errors.New("a list's items are not a list")
			}
			for _, it := range items {
				o, ok := it.(map[string]any)
				if !ok {
					return nil, errors.New("a list item is not an object")
				}
				out = append(out, o)
			}
			continue
		}
		out = append(out, obj)
	}
	if len(out) > MaxOperations {
		return nil, fmt.Errorf("more than %d objects", MaxOperations)
	}
	return out, nil
}

// parseYAMLDocs reads YAML (JSON included) into JSON values.
func parseYAMLDocs(s string) ([]any, error) {
	if len(s) > 1<<20 {
		return nil, errors.New("over 1 MiB")
	}
	dec := yaml.NewDecoder(strings.NewReader(s))
	var out []any
	for {
		var n yaml.Node
		err := dec.Decode(&n)
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, err
		}
		v, err := yamlValue(&n, 0)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, nil
}

// yamlValue converts a YAML node to a JSON value. Scalars keep the form
// YAML 1.2 gives them; YAML 1.1's yes, no, on and off stay strings, which
// the catalog's conditions list beside true and false.
func yamlValue(n *yaml.Node, depth int) (any, error) {
	if depth > maxJSONDepth {
		return nil, fmt.Errorf("nested deeper than %d levels", maxJSONDepth)
	}
	switch n.Kind {
	case yaml.DocumentNode:
		if len(n.Content) == 0 {
			return nil, nil
		}
		return yamlValue(n.Content[0], depth)
	case yaml.AliasNode:
		return nil, errors.New("YAML aliases are not read")
	case yaml.MappingNode:
		m := make(map[string]any, len(n.Content)/2)
		for i := 0; i+1 < len(n.Content); i += 2 {
			k := n.Content[i]
			if k.Kind != yaml.ScalarNode || k.Tag == "!!merge" {
				return nil, errors.New("a mapping key that is not a plain value")
			}
			if _, dup := m[k.Value]; dup {
				return nil, fmt.Errorf("key %q repeated", k.Value)
			}
			v, err := yamlValue(n.Content[i+1], depth+1)
			if err != nil {
				return nil, err
			}
			m[k.Value] = v
		}
		return m, nil
	case yaml.SequenceNode:
		l := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := yamlValue(c, depth+1)
			if err != nil {
				return nil, err
			}
			l = append(l, v)
		}
		return l, nil
	case yaml.ScalarNode:
		switch n.ShortTag() {
		case "!!null":
			return nil, nil
		case "!!bool":
			return strings.EqualFold(n.Value, "true"), nil
		case "!!int", "!!float":
			if _, err := strconv.ParseFloat(strings.ReplaceAll(n.Value, "_", ""), 64); err == nil && json.Valid([]byte(n.Value)) {
				return json.Number(n.Value), nil
			}
			return n.Value, nil // 0x1f, 0o17, .inf: kept as written
		}
		return n.Value, nil
	}
	return nil, errors.New("a YAML node Opfence does not read")
}

func optString(v any, what string) (string, error) {
	if v == nil {
		return "", nil
	}
	s, ok := v.(string)
	if !ok {
		return "", fmt.Errorf("%s is not text", what)
	}
	return s, nil
}

func kubeInt(v any) (int64, bool) {
	switch x := v.(type) {
	case json.Number:
		n, err := x.Int64()
		return n, err == nil
	case float64:
		return int64(x), x == float64(int64(x))
	case string:
		n, err := strconv.ParseInt(x, 10, 64)
		return n, err == nil
	}
	return 0, false
}

// kubeStrings reads a command or port list: a list of words, or one string
// split at spaces as the MCP servers split it.
func kubeStrings(v any) ([]string, bool) {
	switch x := v.(type) {
	case nil:
		return nil, true
	case string:
		return strings.Fields(x), true
	case json.Number:
		return []string{x.String()}, true
	case []any:
		var out []string
		for _, el := range x {
			switch e := el.(type) {
			case string:
				out = append(out, e)
			case json.Number:
				out = append(out, e.String())
			default:
				return nil, false
			}
		}
		return out, true
	}
	return nil, false
}
