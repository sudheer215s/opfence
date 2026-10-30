package engine

import (
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/catalog"
	"github.com/rakeshnitb23/opfence/internal/classes"
	"github.com/rakeshnitb23/opfence/internal/policy"
)

func callKube(t *testing.T, user *policy.File, tool string, args map[string]any) Evaluation {
	t.Helper()
	c, err := catalog.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	e := New(c, policy.Resolve(user, nil))
	return e.EvaluateTool(c.Provider("kubernetes-mcp"), tool, args).Evaluations[0]
}

func TestKubernetesTools(t *testing.T) {
	cases := []struct {
		tool     string
		args     map[string]any
		class    classes.Class
		decision classes.Decision
		resource string
		source   string
	}{
		{"resources_delete", map[string]any{"apiVersion": "apps/v1", "kind": "Deployment", "name": "web", "namespace": "shop"},
			classes.Delete, classes.Ask, "web", "kubernetes.apps.deployments.delete delete"},
		{"resources_delete", map[string]any{"apiVersion": "v1", "kind": "Namespace", "name": "shop"},
			classes.Irreversible, classes.Confirm, "shop", "kubernetes.core.namespaces.delete irreversible"},
		{"resources_get", map[string]any{"apiVersion": "v1", "kind": "Secret", "name": "db", "namespace": "shop"},
			classes.Credential, classes.Deny, "db", "kubernetes.core.secrets.get"},
		{"kubectl_get", map[string]any{"resourceType": "po", "namespace": "shop"},
			classes.Read, classes.Allow, "", "GET /api/v1/namespaces/shop/pods"},
		// A manifest takes its strictest object.
		{"resources_create_or_update", map[string]any{"resource": "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: a}\n---\n" +
			"apiVersion: v1\nkind: Pod\nmetadata: {name: p}\nspec:\n  hostPID: yes\n  containers: [{name: c, image: busybox}]\n"},
			classes.Access, classes.Ask, "", "kubernetes.core.pods.create access"},
		// What Opfence cannot read keeps the rule's class.
		{"resources_create_or_update", map[string]any{"resource": "apiVersion: example.com/v1\nkind: Widget\nmetadata: {name: w}\n"},
			classes.Irreversible, classes.Confirm, "", "rule class, for what Opfence cannot read"},
		{"resources_create_or_update", map[string]any{"resource": 7.0}, classes.Irreversible, classes.Confirm, "", "the manifest is not text"},
		{"kubectl_rollout", map[string]any{"subCommand": "frobnicate", "resourceType": "deployment", "name": "web"},
			classes.Write, classes.Ask, "web", "an action Opfence does not read"},
		{"kubectl_scale", map[string]any{"name": "web", "replicas": 0.0, "namespace": "shop"},
			classes.Delete, classes.Ask, "web", "kubernetes.apps.deployments.scale.patch delete"},
		{"node_management", map[string]any{"operation": "drain", "nodeName": "n1"},
			classes.Delete, classes.Ask, "n1", "kubernetes.core.pods.eviction.create delete"},
	}
	for _, c := range cases {
		ev := callKube(t, nil, c.tool, c.args)
		if ev.Class != c.class || ev.Decision != c.decision || ev.Resource != c.resource || !strings.Contains(ev.ClassSource, c.source) {
			t.Errorf("%s %v: %s %s resource %q (%s); want %s %s %q (%s)", c.tool, c.args, ev.Class, ev.Decision, ev.Resource, ev.ClassSource,
				c.class, c.decision, c.resource, c.source)
		}
	}
}

// The kubernetes provider's environments and rule overrides apply to tool
// calls, as they do to the same requests through the proxy.
func TestKubernetesToolPolicy(t *testing.T) {
	user := &policy.File{
		Environments: map[string]map[string]map[string][]string{
			policy.Development: {"kubernetes": {"namespace": {"dev"}, "cluster": {"kind-dev"}}},
		},
	}
	ev := callKube(t, user, "kubectl_delete", map[string]any{"resourceType": "deployment", "name": "web", "namespace": "dev"})
	if ev.Environment != policy.Development {
		t.Errorf("a mapped namespace: %s (%s)", ev.Environment, ev.EnvSource)
	}
	// Flux's server defaults the namespace to "default", which is not mapped.
	if ev := callKube(t, user, "kubectl_delete", map[string]any{"resourceType": "deployment", "name": "web"}); ev.Environment != policy.Production {
		t.Errorf("the default namespace: %s (%s)", ev.Environment, ev.EnvSource)
	}
	// The context stands for the cluster.
	if ev := callKube(t, user, "kubectl_delete", map[string]any{"resourceType": "deployment", "name": "web", "context": "kind-dev"}); ev.Environment != policy.Development {
		t.Errorf("a mapped context: %s (%s)", ev.Environment, ev.EnvSource)
	}
	// A namespace the call leaves to the kubeconfig cannot be mapped.
	if ev := callKube(t, user, "resources_delete", map[string]any{"apiVersion": "v1", "kind": "Pod", "name": "x"}); ev.Environment != policy.Production {
		t.Errorf("the kubeconfig's namespace: %s (%s)", ev.Environment, ev.EnvSource)
	}
	override := &policy.File{Rules: []policy.RuleOverride{{Rule: "kubernetes.core.secrets.*", Decision: classes.Ask}}}
	if ev := callKube(t, override, "kubectl_get", map[string]any{"resourceType": "secret", "name": "x", "namespace": "shop"}); ev.Decision != classes.Ask {
		t.Errorf("override on kubernetes.core.secrets.*: %s (%s)", ev.Decision, ev.DecisionSource)
	}
}
