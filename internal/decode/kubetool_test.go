package decode

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func TestKubeResources(t *testing.T) {
	for _, c := range []struct {
		name, plural, group, version string
		n                            int
	}{
		{"po", "pods", "", "", 1},
		{"Pod", "pods", "", "", 1},
		{"deploy", "deployments", "apps", "", 1},
		{"deployments.apps", "deployments", "apps", "", 1},
		{"deployment.v1.apps", "deployments", "apps", "v1", 1},
		{"crds", "customresourcedefinitions", "apiextensions.k8s.io", "", 1},
		{"events", "events", "", "", 2}, // core and events.k8s.io
		{"ev.events.k8s.io", "events", "events.k8s.io", "", 1},
		{"widgets.example.com", "", "", "", 0},
		{"all", "pods", "", "", 10},
		{"deployments.batch", "", "", "", 0},
	} {
		rs, v := KubeResourcesByName(c.name)
		if len(rs) != c.n || v != c.version || (c.n > 0 && (rs[0].Plural != c.plural || (c.n == 1 && rs[0].Group != c.group))) {
			t.Errorf("%s: %d resources, version %q: %+v", c.name, len(rs), v, rs)
		}
	}
	rs, v := KubeResourcesByKind("apps/v1", "Deployment")
	if len(rs) != 1 || rs[0].Plural != "deployments" || v != "v1" || !rs[0].Namespaced {
		t.Errorf("apps/v1 Deployment: %+v %q", rs, v)
	}
	if rs, _ := KubeResourcesByKind("v1", "Namespace"); len(rs) != 1 || rs[0].Namespaced {
		t.Errorf("v1 Namespace: %+v", rs)
	}
	if rs, _ := KubeResourcesByKind("apps/../v1", "Deployment"); rs != nil {
		t.Errorf("a version that is not one: %+v", rs)
	}
	if rs, _ := KubeResourcesByKind("example.com/v1", "Widget"); rs != nil {
		t.Errorf("a custom resource: %+v", rs)
	}
}

// kubeOps renders a call's steps as "METHOD path body" lines.
func kubeOps(t *testing.T, c KubeCall) []string {
	t.Helper()
	var out []string
	for _, st := range KubeToolOps(c) {
		if st.Op == nil {
			out = append(out, "unknown: "+st.Reason)
			continue
		}
		line := st.Op.Method + " " + st.Op.Path
		if q, _ := st.Op.Args["query"].(map[string]any); len(q) > 0 {
			b, _ := json.Marshal(q)
			line += " ?" + string(b)
		}
		if b, ok := st.Op.Args["body"]; ok {
			j, _ := json.Marshal(b)
			line += " " + string(j)
		}
		if st.Op.BodyErr != "" {
			line += " (body: " + st.Op.BodyErr + ")"
		}
		if st.Op.Args["cluster"] == nil {
			t.Errorf("%s: no cluster", line)
		}
		out = append(out, line)
	}
	return out
}

func TestKubeToolOps(t *testing.T) {
	priv := "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: shell\nspec:\n  template:\n    spec:\n      hostNetwork: yes\n      containers:\n      - name: c\n        image: busybox\n        securityContext: {privileged: true}\n---\napiVersion: v1\nkind: Service\nmetadata: {name: web, namespace: shop}\nspec: {type: LoadBalancer, ports: [{port: 443}]}\n"
	for _, c := range []struct {
		name string
		call KubeCall
		want []string
	}{
		{"get by kind", KubeCall{Action: "get", APIVersion: "apps/v1", Kind: "Deployment", Name: "web", Namespace: "shop"},
			[]string{"GET /apis/apps/v1/namespaces/shop/deployments/web"}},
		{"read is get", KubeCall{Action: "read", APIVersion: "v1", Kind: "Secret", Name: "db", Namespace: "shop"},
			[]string{"GET /api/v1/namespaces/shop/secrets/db"}},
		{"list without a namespace lists every one", KubeCall{Action: "list", Resource: "secrets"},
			[]string{"GET /api/v1/secrets"}},
		{"get without a name lists", KubeCall{Action: "get", Resource: "deploy", Namespace: "shop", Selector: "app=web"},
			[]string{"GET /apis/apps/v1/namespaces/shop/deployments"}},
		{"list with a selector", KubeCall{Action: "list", Resource: "pods", Namespace: "shop", Selector: "app=web"},
			[]string{`GET /api/v1/namespaces/shop/pods ?{"labelSelector":"app=web"}`}},
		{"cluster-scoped", KubeCall{Action: "delete", Resource: "ns", Name: "shop"},
			[]string{"DELETE /api/v1/namespaces/shop"}},
		{"no namespace is the kubeconfig's", KubeCall{Action: "delete", Resource: "pod", Name: "web"},
			[]string{"DELETE /api/v1/namespaces/@kubeconfig/pods/web"}},
		{"type/name", KubeCall{Action: "delete", Resource: "deployment/web", Namespace: "shop"},
			[]string{"DELETE /apis/apps/v1/namespaces/shop/deployments/web"}},
		{"delete every one", KubeCall{Action: "delete", Resource: "pods", Namespace: "shop"},
			[]string{"DELETE /api/v1/namespaces/shop/pods"}},
		{"delete across namespaces", KubeCall{Action: "delete", Resource: "pods", AllNamespaces: true, Selector: "app=web"},
			[]string{`DELETE /api/v1/namespaces/@all/pods ?{"labelSelector":"app=web"}`}},
		{"events in both groups", KubeCall{Action: "delete", Resource: "events", Name: "e", Namespace: "shop"},
			[]string{"DELETE /api/v1/namespaces/shop/events/e", "DELETE /apis/events.k8s.io/v1/namespaces/shop/events/e"}},
		{"apply a manifest", KubeCall{Action: "apply", Manifest: priv, Namespace: "dev"},
			[]string{
				`POST /apis/apps/v1/namespaces/dev/deployments {"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"shell"},"spec":{"template":{"spec":{"containers":[{"image":"busybox","name":"c","securityContext":{"privileged":true}}],"hostNetwork":"yes"}}}}`,
				`PATCH /apis/apps/v1/namespaces/dev/deployments/shell {"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"shell"},"spec":{"template":{"spec":{"containers":[{"image":"busybox","name":"c","securityContext":{"privileged":true}}],"hostNetwork":"yes"}}}}`,
				`POST /api/v1/namespaces/shop/services {"apiVersion":"v1","kind":"Service","metadata":{"name":"web","namespace":"shop"},"spec":{"ports":[{"port":443}],"type":"LoadBalancer"}}`,
				`PATCH /api/v1/namespaces/shop/services/web {"apiVersion":"v1","kind":"Service","metadata":{"name":"web","namespace":"shop"},"spec":{"ports":[{"port":443}],"type":"LoadBalancer"}}`,
			}},
		{"a list manifest", KubeCall{Action: "delete", Manifest: `{"apiVersion":"v1","kind":"List","items":[{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"a"}}]}`},
			[]string{"DELETE /api/v1/namespaces/@kubeconfig/configmaps/a"}},
		{"a custom resource", KubeCall{Action: "create", Manifest: "apiVersion: example.com/v1\nkind: Widget\nmetadata: {name: w}\n"},
			[]string{"unknown: example.com/v1 Widget is not a built-in kind"}},
		{"an unreadable manifest", KubeCall{Action: "create", Manifest: "a: [1"},
			[]string{"unknown: the manifest cannot be read: yaml: line 1: did not find expected ',' or ']'"}},
		{"a repeated key", KubeCall{Action: "create", Manifest: "apiVersion: v1\nkind: Pod\nkind: Secret\n"},
			[]string{"unknown: the manifest cannot be read: key \"kind\" repeated"}},
		{"an object argument", KubeCall{Action: "create", Kind: "Secret", APIVersion: "v1", Object: map[string]any{"apiVersion": "v1", "kind": "Secret", "metadata": map[string]any{"name": "db"}}, Namespace: "shop"},
			[]string{`POST /api/v1/namespaces/shop/secrets {"apiVersion":"v1","kind":"Secret","metadata":{"name":"db","namespace":"shop"}}`}},
		{"an object without its kind", KubeCall{Action: "create", Kind: "ConfigMap", APIVersion: "v1", Name: "aws-auth", Namespace: "kube-system", Object: map[string]any{"data": map[string]any{"mapRoles": "x"}}},
			[]string{`POST /api/v1/namespaces/kube-system/configmaps {"apiVersion":"v1","data":{"mapRoles":"x"},"kind":"ConfigMap","metadata":{"name":"aws-auth","namespace":"kube-system"}}`}},
		{"a service by type", KubeCall{Action: "create", Resource: "service", Name: "web", Namespace: "shop", ServiceType: "loadbalancer"},
			[]string{`POST /api/v1/namespaces/shop/services {"apiVersion":"v1","kind":"Service","metadata":{"name":"web","namespace":"shop"},"spec":{"type":"LoadBalancer"}}`}},
		{"a dry run", KubeCall{Action: "apply", Manifest: "apiVersion: v1\nkind: Namespace\nmetadata: {name: x}\n", DryRun: true},
			[]string{`POST /api/v1/namespaces ?{"dryRun":"All"} {"apiVersion":"v1","kind":"Namespace","metadata":{"name":"x"}}`,
				`PATCH /api/v1/namespaces/x ?{"dryRun":"All"} {"apiVersion":"v1","kind":"Namespace","metadata":{"name":"x"}}`}},
		{"a dry run delete", KubeCall{Action: "delete", Resource: "ns", Name: "x", DryRun: true},
			[]string{`DELETE /api/v1/namespaces/x {"dryRun":["All"]}`}},
		{"create by type and name", KubeCall{Action: "create", Resource: "configmap", Name: "aws-auth", Namespace: "kube-system"},
			[]string{`POST /api/v1/namespaces/kube-system/configmaps {"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"aws-auth","namespace":"kube-system"}}`}},
		{"a JSON Patch", KubeCall{Action: "patch", Resource: "deployment", Name: "web", Namespace: "shop", PatchType: "json", Patch: `[{"op":"replace","path":"/spec/replicas","value":0}]`},
			[]string{`PATCH /apis/apps/v1/namespaces/shop/deployments/web [{"op":"replace","path":"/spec/replicas","value":0}]`}},
		{"a JSON Patch that is not a list", KubeCall{Action: "patch", Resource: "deployment", Name: "web", PatchType: "json", Patch: `{"spec":{}}`},
			[]string{"unknown: the patch cannot be read: a JSON Patch is a list of operations"}},
		{"a patch object", KubeCall{Action: "patch", Kind: "Service", APIVersion: "v1", Name: "web", Namespace: "shop", Patch: map[string]any{"spec": map[string]any{"type": "NodePort"}}},
			[]string{`PATCH /api/v1/namespaces/shop/services/web {"spec":{"type":"NodePort"}}`}},
		{"scale to zero", KubeCall{Action: "scale", Resource: "sts", Name: "db", Namespace: "shop", Replicas: json.Number("0")},
			[]string{`PATCH /apis/apps/v1/namespaces/shop/statefulsets/db/scale {"spec":{"replicas":0}}`}},
		{"scale without replicas reads it", KubeCall{Action: "scale", APIVersion: "apps/v1", Kind: "Deployment", Name: "web", Namespace: "shop"},
			[]string{"GET /apis/apps/v1/namespaces/shop/deployments/web/scale"}},
		{"scale what cannot", KubeCall{Action: "scale", Resource: "configmap", Name: "x", Replicas: json.Number("2")},
			[]string{"unknown: configmaps cannot be scaled"}},
		{"exec", KubeCall{Action: "exec", Name: "web", Namespace: "shop", Command: []any{"sh", "-c", "env"}, Container: "app"},
			[]string{`POST /api/v1/namespaces/shop/pods/web/exec ?{"command":["sh","-c","env"],"container":"app"}`}},
		{"exec, a string command", KubeCall{Action: "exec", Name: "web", Command: "rm -rf /data"},
			[]string{`POST /api/v1/namespaces/@kubeconfig/pods/web/exec ?{"command":["rm","-rf","/data"]}`}},
		{"logs of a deployment", KubeCall{Action: "logs", Resource: "deployment", Name: "web", Namespace: "shop"},
			[]string{"GET /api/v1/namespaces/shop/pods/web/log"}},
		{"port forward", KubeCall{Action: "portforward", Resource: "service", Name: "db", Namespace: "shop", Ports: json.Number("5432")},
			[]string{`POST /api/v1/namespaces/shop/pods/db/portforward ?{"ports":"5432"}`}},
		{"run", KubeCall{Action: "run", Name: "tmp", Image: "busybox", Namespace: "shop"},
			[]string{`POST /api/v1/namespaces/shop/pods {"apiVersion":"v1","kind":"Pod","metadata":{"name":"tmp"},"spec":{"containers":[{"image":"busybox","name":"tmp"}]}}`}},
		{"run with a port", KubeCall{Action: "run", Name: "tmp", Image: "busybox", Ports: json.Number("8080")},
			[]string{`POST /api/v1/namespaces/@kubeconfig/pods {"apiVersion":"v1","kind":"Pod","metadata":{"name":"tmp"},"spec":{"containers":[{"image":"busybox","name":"tmp"}]}}`,
				`POST /api/v1/namespaces/@kubeconfig/services {"apiVersion":"v1","kind":"Service","metadata":{"name":"tmp"},"spec":{"type":"ClusterIP"}}`,
				"unknown: on OpenShift a Route publishes the port, and Routes are not built in"}},
		{"restart", KubeCall{Action: "restart", Resource: "deployment", Name: "web", Namespace: "shop"},
			[]string{`PATCH /apis/apps/v1/namespaces/shop/deployments/web {"spec":{"template":{"metadata":{"annotations":{"kubectl.kubernetes.io/restartedAt":"now"}}}}}`}},
		{"undo", KubeCall{Action: "undo", Resource: "deployment", Name: "web", Namespace: "shop"},
			[]string{"PATCH /apis/apps/v1/namespaces/shop/deployments/web (body: rollout undo restores a pod template that is not in the call)"}},
		{"drain", KubeCall{Action: "drain", Name: "node-1"},
			[]string{`PATCH /api/v1/nodes/node-1 {"spec":{"unschedulable":true}}`,
				`POST /api/v1/namespaces/@all/pods/@node-1/eviction {"apiVersion":"policy/v1","kind":"Eviction"}`}},
		{"uncordon", KubeCall{Action: "uncordon", Name: "node-1"}, []string{`PATCH /api/v1/nodes/node-1 {"spec":{"unschedulable":false}}`}},
		{"an action Opfence does not read", KubeCall{Action: "edit", Resource: "pods", Name: "x"},
			[]string{`unknown: Opfence does not read the action "edit"`}},
		{"no kind", KubeCall{Action: "delete", Name: "x"}, []string{"unknown: the call names no kind or resource type"}},
		{"a name that is not text", KubeCall{Action: "delete", Resource: "pods", Name: json.Number("1")}, []string{"unknown: name is not text"}},
		{"YAML aliases", KubeCall{Action: "create", Manifest: "a: &x [1]\nb: *x\n"}, []string{"unknown: the manifest cannot be read: YAML aliases are not read"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			if got := kubeOps(t, c.call); !reflect.DeepEqual(got, c.want) {
				t.Errorf("got\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(c.want, "\n"))
			}
		})
	}
	// The context, when the call names one, stands for the cluster.
	st := KubeToolOps(KubeCall{Action: "get", Resource: "pods", Name: "x", Namespace: "a", Context: "prod-eu"})
	if st[0].Op.Args["cluster"] != "prod-eu" {
		t.Errorf("cluster = %v", st[0].Op.Args["cluster"])
	}
}

func TestParseKubeManifest(t *testing.T) {
	objs, err := ParseKubeManifest("---\n# a comment\n---\napiVersion: v1\nkind: Pod\nspec:\n  replicas: 3\n  ratio: 1.5\n  big: 0x10\n  on: on\n  t: True\n  n: ~\n")
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"apiVersion": "v1", "kind": "Pod", "spec": map[string]any{"replicas": json.Number("3"), "ratio": json.Number("1.5"),
		"big": "0x10", "on": "on", "t": true, "n": nil}}
	if len(objs) != 1 || !reflect.DeepEqual(objs[0], want) {
		t.Errorf("%#v", objs)
	}
	for _, bad := range []string{"- 1\n", "{a: 1, a: 2}", "a: {b: [", "? [a]\n: 1\n", strings.Repeat("[", 100) + strings.Repeat("]", 100)} {
		if _, err := ParseKubeManifest(bad); err == nil {
			t.Errorf("%q read", bad)
		}
	}
	if _, err := ParseKubeManifest(strings.Repeat("---\na: 1\n", MaxOperations+1)); err == nil {
		t.Error("too many objects read")
	}
}

// FuzzKubeTool checks that any manifest and patch either fail or give
// requests on API paths, without panicking.
func FuzzKubeTool(f *testing.F) {
	f.Add("apply", "apiVersion: v1\nkind: Pod\nmetadata: {name: p}\n", `{"spec":{}}`)
	f.Add("patch", "", `[{"op":"add","path":"/a","value":1}]`)
	f.Add("delete", `{"apiVersion":"v1","kind":"List","items":[{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"d"}}]}`, "")
	f.Fuzz(func(t *testing.T, action, manifest, patch string) {
		c := KubeCall{Action: action, Resource: "deploy", Name: "web", Patch: patch}
		if manifest != "" {
			c.Manifest = manifest
		}
		for _, st := range KubeToolOps(c) {
			if st.Op == nil {
				if st.Reason == "" {
					t.Fatal("a step with neither a request nor a reason")
				}
				continue
			}
			if !strings.HasPrefix(st.Op.Path, "/api/v1/") && !strings.HasPrefix(st.Op.Path, "/apis/") {
				t.Fatalf("path %q", st.Op.Path)
			}
		}
	})
}
