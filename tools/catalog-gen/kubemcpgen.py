# Writes catalog/kubernetes-mcp (rules and fixtures): the tools of the two
# most used Kubernetes MCP servers, which both run locally and call each
# cluster's API with the user's kubeconfig. Run from the repo root:
#   python3 -I tools/catalog-gen/kubemcpgen.py
# The tools were read from the servers' source at the commits below. A tool
# that acts on Kubernetes objects names its arguments for classify.kubernetes,
# so the engine builds the API requests it makes and decides them with
# catalog/kubernetes's rules; the rest have a fixed class.
import json, os

D = "catalog/kubernetes-mcp/"
DATE = "2026-10-30"
KMCP = "https://github.com/containers/kubernetes-mcp-server/blob/7797d3937ba3b85905d8942279daab6cf3eaec89/"
FLUX = "https://github.com/Flux159/mcp-server-kubernetes/blob/4.2.1/"
R, W, DEL, I, A, C, M, U = "read", "write", "delete", "irreversible", "access", "credential", "money", "unknown"

PRIV = ("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: node-shell\n  namespace: shop\nspec:\n  selector:\n"
        "    matchLabels: {app: node-shell}\n  template:\n    metadata:\n      labels: {app: node-shell}\n    spec:\n"
        "      hostNetwork: true\n      containers:\n      - name: shell\n        image: busybox:1.36\n"
        "        securityContext:\n          privileged: true\n")
WEB = ("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n  namespace: shop\nspec:\n  replicas: 3\n  selector:\n"
       "    matchLabels: {app: web}\n  template:\n    metadata:\n      labels: {app: web}\n    spec:\n      containers:\n"
       "      - name: web\n        image: ghcr.io/acme/web:1.4.2\n")
LB = "apiVersion: v1\nkind: Service\nmetadata:\n  name: web\n  namespace: shop\nspec:\n  type: LoadBalancer\n  ports:\n  - port: 443\n"
CRD_OBJ = "apiVersion: cert-manager.io/v1\nkind: Certificate\nmetadata:\n  name: web\n  namespace: shop\nspec:\n  secretName: web-tls\n"

# (id, tool, class, classify or None, resource arg, card, sources, notes, tests)
# tests: (fixture suffix, description, arguments, expected class, resource)
T = []
def tool(id_, name, cls, card, src, notes, tests, k=None, res=None, when=None):
    T.append(dict(id=id_, tool=name, cls=cls, k=k, res=res, card=card, src=src, notes=notes, tests=tests, when=when or []))

GET_NOTE = ("Reads; a Secret's data makes it credential, as reading it through the API is. Custom resources are not "
            "in Kubernetes' description and are read as reads.")

# --- containers/kubernetes-mcp-server: core, config and helm toolsets --------
K_RES = KMCP + "pkg/toolsets/core/resources.go"
K_PODS = KMCP + "pkg/toolsets/core/pods.go"
CTX = {"context": "context"}
tool("kubernetes-mcp.resources.list", "resources_list", R, "List {kind} objects in namespace {namespace}", [K_RES], GET_NOTE,
     [("", "List the Deployments in shop", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop"}, R, None),
      ("-secrets", "List every namespace's Secrets", {"apiVersion": "v1", "kind": "Secret"}, C, None),
      ("-custom", "List cert-manager Certificates", {"apiVersion": "cert-manager.io/v1", "kind": "Certificate", "namespace": "shop"}, U, None)],
     k=dict(action="list", api_version="apiVersion", kind="kind", namespace="namespace", label_selector="labelSelector", **CTX))
tool("kubernetes-mcp.resources.get", "resources_get", R, "Read {kind} {name} in namespace {namespace}", [K_RES], GET_NOTE,
     [("", "Read Deployment web", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop", "name": "web"}, R, "web"),
      ("-secret", "Read Secret shop-db", {"apiVersion": "v1", "kind": "Secret", "namespace": "shop", "name": "shop-db"}, C, "shop-db")],
     k=dict(action="get", api_version="apiVersion", kind="kind", name="name", namespace="namespace", **CTX), res="name")
tool("kubernetes-mcp.resources.create-or-update", "resources_create_or_update", I,
     "Create or update the objects of a manifest", [K_RES, KMCP + "pkg/kubernetes/resources.go"],
     "Server-side apply of a YAML or JSON manifest: decided as both creating and updating each object, so a privileged "
     "pod spec, a LoadBalancer Service, a Secret or a role binding gets the class those get through the API. A custom "
     "resource, which Opfence cannot read, keeps this rule's class.",
     [("", "Apply Deployment web", {"resource": WEB}, W, None),
      ("-privileged", "Apply a privileged Deployment on the host's network", {"resource": PRIV}, A, None),
      ("-load-balancer", "Apply a LoadBalancer Service", {"resource": LB}, M, None),
      ("-custom", "Apply a cert-manager Certificate", {"resource": CRD_OBJ}, I, None)],
     k=dict(action="apply", manifest="resource", **CTX))
tool("kubernetes-mcp.resources.delete", "resources_delete", I, "Delete {kind} {name} in namespace {namespace}", [K_RES],
     "Decided as the DELETE it sends: deleting a Namespace, PersistentVolumeClaim or Secret is irreversible, a Deployment "
     "delete. A custom resource keeps this rule's class.",
     [("", "Delete Deployment web", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop", "name": "web"}, DEL, "web"),
      ("-namespace", "Delete Namespace shop", {"apiVersion": "v1", "kind": "Namespace", "name": "shop"}, I, "shop")],
     k=dict(action="delete", api_version="apiVersion", kind="kind", name="name", namespace="namespace", **CTX), res="name")
tool("kubernetes-mcp.resources.scale", "resources_scale", W, "Scale {kind} {name} in namespace {namespace} to {scale}", [K_RES],
     "Without scale it only reads the current scale. Scaling to zero replicas is delete.",
     [("", "Scale Deployment web to 3", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop", "name": "web", "scale": 3}, W, "web"),
      ("-zero", "Scale StatefulSet postgres to 0", {"apiVersion": "apps/v1", "kind": "StatefulSet", "namespace": "shop", "name": "postgres", "scale": 0}, DEL, "postgres"),
      ("-read", "Read Deployment web's scale", {"apiVersion": "apps/v1", "kind": "Deployment", "namespace": "shop", "name": "web"}, R, "web")],
     k=dict(action="scale", api_version="apiVersion", kind="kind", name="name", namespace="namespace", replicas="scale", **CTX), res="name")
tool("kubernetes-mcp.pods.list", "pods_list", R, "List Pods in every namespace", [K_PODS], "Reads.",
     [("", "List every Pod", {"labelSelector": "app=web"}, R, None)],
     k=dict(action="list", resource_default="pods", label_selector="labelSelector", **CTX))
tool("kubernetes-mcp.pods.list-in-namespace", "pods_list_in_namespace", R, "List Pods in namespace {namespace}", [K_PODS], "Reads.",
     [("", "List the Pods in shop", {"namespace": "shop"}, R, None)],
     k=dict(action="list", resource_default="pods", namespace="namespace", label_selector="labelSelector", **CTX))
tool("kubernetes-mcp.pods.get", "pods_get", R, "Read Pod {name} in namespace {namespace}", [K_PODS], "Reads.",
     [("", "Read Pod web-0", {"namespace": "shop", "name": "web-0"}, R, "web-0")],
     k=dict(action="get", resource_default="pods", name="name", namespace="namespace", **CTX), res="name")
tool("kubernetes-mcp.pods.delete", "pods_delete", DEL, "Delete Pod {name} in namespace {namespace}",
     [K_PODS, KMCP + "pkg/kubernetes/pods.go"],
     "Deletes the pod, and for a pod pods_run made, its Service and Route.",
     [("", "Delete Pod web-0", {"namespace": "shop", "name": "web-0"}, DEL, "web-0")],
     k=dict(action="delete", resource_default="pods", name="name", namespace="namespace", **CTX), res="name")
tool("kubernetes-mcp.pods.top", "pods_top", R, "Read Pods' CPU and memory use", [K_PODS], "Reads the metrics API.",
     [("", "Read every Pod's resource use", {"all_namespaces": True}, R, None)])
tool("kubernetes-mcp.pods.exec", "pods_exec", I, "Run {command} in Pod {name} in namespace {namespace}", [K_PODS],
     "Runs a command in a container, with its access to data, secrets and the network.",
     [("", "Run env in Pod web-0", {"namespace": "shop", "name": "web-0", "command": ["sh", "-c", "env"]}, I, "web-0")],
     k=dict(action="exec", name="name", namespace="namespace", command="command", container="container", **CTX), res="name")
tool("kubernetes-mcp.pods.log", "pods_log", R, "Read the log of Pod {name} in namespace {namespace}", [K_PODS], "Reads.",
     [("", "Read Pod web-0's log", {"namespace": "shop", "name": "web-0", "tail": 100}, R, "web-0")],
     k=dict(action="logs", name="name", namespace="namespace", container="container", **CTX), res="name")
tool("kubernetes-mcp.pods.run", "pods_run", A, "Run image {image} as Pod {name} in namespace {namespace}",
     [K_PODS, KMCP + "pkg/kubernetes/pods.go"],
     "Creates a pod from an image (write). With a port it also creates a Service and, on OpenShift, a Route that "
     "publishes the port, which Opfence cannot tell apart from a cluster without Routes: that is this rule's class.",
     [("", "Run busybox in shop", {"namespace": "shop", "name": "tmp", "image": "busybox:1.36"}, W, "tmp"),
      ("-port", "Run nginx in shop with port 80", {"namespace": "shop", "name": "web", "image": "nginx:1.29", "port": 80}, A, "web")],
     k=dict(action="run", name="name", namespace="namespace", image="image", ports="port", **CTX), res="name")
for name, card in [("namespaces_list", "List namespaces"), ("projects_list", "List OpenShift projects"),
                   ("events_list", "List events in namespace {namespace}")]:
    tool("kubernetes-mcp." + name.replace("_", "."), name, R, card, [KMCP + "pkg/toolsets/core/" + ("events.go" if "events" in name else "namespaces.go")],
         "Reads.", [("", card.replace("{namespace}", "shop"), {"namespace": "shop"} if "events" in name else {}, R, None)])
for name, card in [("nodes_log", "Read node {name}'s logs"), ("nodes_stats_summary", "Read node {name}'s resource use"),
                   ("nodes_top", "Read nodes' CPU and memory use")]:
    tool("kubernetes-mcp." + name.replace("_", "."), name, R, card, [KMCP + "pkg/toolsets/core/nodes.go"],
         "Reads through the kubelet's API (the API server's node proxy), which this tool uses only for logs and stats.",
         [("", card.replace("{name}", "ip-10-0-1-23"), {"name": "ip-10-0-1-23", "query": "kubelet"} if name == "nodes_log" else {"name": "ip-10-0-1-23"}, R, None)])
K_CFG = KMCP + "pkg/toolsets/config/configuration.go"
tool("kubernetes-mcp.configuration.contexts-list", "configuration_contexts_list", R, "List kubeconfig contexts", [K_CFG],
     "Names and servers only.", [("", "List contexts", {}, R, None)])
tool("kubernetes-mcp.configuration.targets-list", "targets_list", R, "List clusters", [K_CFG], "Names only.", [("", "List clusters", {}, R, None)])
tool("kubernetes-mcp.configuration.view", "configuration_view", C, "Read the kubeconfig", [K_CFG, KMCP + "pkg/kubernetes/configuration.go"],
     "Returns the kubeconfig as it is, flattened: its tokens, client keys and passwords included.",
     [("", "Read the kubeconfig", {"minified": True}, C, None)])
K_HELM = KMCP + "pkg/toolsets/helm/helm.go"
tool("kubernetes-mcp.helm.install", "helm_install", I, "Install chart {chart} as release {name} in namespace {namespace}", [K_HELM],
     "A chart's templates can create any object, role bindings and privileged pods included, and its hooks run jobs; "
     "Opfence cannot see them.", [("", "Install chart oci://ghcr.io/acme/web", {"chart": "oci://ghcr.io/acme/web", "name": "web", "namespace": "shop"}, I, "web")],
     res="name")
tool("kubernetes-mcp.helm.list", "helm_list", R, "List Helm releases", [K_HELM], "Names and status only.",
     [("", "List Helm releases", {"namespace": "shop"}, R, None)])
tool("kubernetes-mcp.helm.uninstall", "helm_uninstall", I, "Uninstall release {name} in namespace {namespace}", [K_HELM],
     "Deletes every object the release made, volume claims and namespaces included.",
     [("", "Uninstall release web", {"name": "web", "namespace": "shop"}, I, "web")], res="name")

# --- Flux159/mcp-server-kubernetes (npm mcp-server-kubernetes) ---------------
def F(f):
    return FLUX + "src/tools/" + f
FCTX = {"context": "context", "namespace_default": "default"}
tool("kubernetes-mcp.kubectl.get", "kubectl_get", R, "Get {resourceType} {name} in namespace {namespace}", [F("kubectl-get.ts")], GET_NOTE,
     [("", "Get the Deployments in shop", {"resourceType": "deployments", "namespace": "shop"}, R, None),
      ("-secret", "Get Secret shop-db as YAML", {"resourceType": "secret", "name": "shop-db", "namespace": "shop", "output": "yaml"}, C, "shop-db"),
      ("-all-secrets", "Get every namespace's Secrets", {"resourceType": "secrets", "allNamespaces": True}, C, None)],
     k=dict(action="get", resource="resourceType", name="name", namespace="namespace", all_namespaces="allNamespaces",
            label_selector="labelSelector", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.describe", "kubectl_describe", R, "Describe {resourceType} {name} in namespace {namespace}",
     [F("kubectl-describe.ts")], GET_NOTE + " kubectl describe prints a Secret's keys and sizes, but reads it whole, as the proxy would see.",
     [("", "Describe Pod web-0", {"resourceType": "pod", "name": "web-0", "namespace": "shop"}, R, "web-0")],
     k=dict(action="describe", resource="resourceType", name="name", namespace="namespace", all_namespaces="allNamespaces", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.apply", "kubectl_apply", I, "Apply a manifest to namespace {namespace}", [F("kubectl-apply.ts")],
     "Decided as creating and updating each object in the manifest. A file on the server's machine (filename), and custom "
     "resources, keep this rule's class; dryRun validates on the client and sends nothing.",
     [("", "Apply Deployment web", {"manifest": WEB}, W, None),
      ("-privileged", "Apply a privileged Deployment", {"manifest": PRIV}, A, None),
      ("-file", "Apply a file", {"filename": "/srv/deploy/web.yaml"}, I, None),
      ("-dry-run", "Apply Deployment web as a dry run", {"manifest": WEB, "dryRun": True}, R, None)],
     k=dict(action="apply", manifest="manifest", dry_run="dryRun", **FCTX))
tool("kubernetes-mcp.kubectl.delete", "kubectl_delete", I, "Delete {resourceType} {name} in namespace {namespace}", [F("kubectl-delete.ts")],
     "Decided as the DELETEs it sends: by name, by label selector, every object of the type, or each object of a "
     "manifest. A file on the server's machine and custom resources keep this rule's class.",
     [("", "Delete Deployment web", {"resourceType": "deployment", "name": "web", "namespace": "shop"}, DEL, "web"),
      ("-namespace", "Delete Namespace shop", {"resourceType": "namespace", "name": "shop"}, I, "shop"),
      ("-every", "Delete every Pod in shop", {"resourceType": "pods", "namespace": "shop"}, I, None),
      ("-selector", "Delete the Pods labelled app=web", {"resourceType": "pods", "namespace": "shop", "labelSelector": "app=web"}, DEL, None),
      ("-manifest", "Delete the objects of a manifest", {"manifest": LB}, DEL, None)],
     k=dict(action="delete", resource="resourceType", name="name", namespace="namespace", label_selector="labelSelector",
            all_namespaces="allNamespaces", manifest="manifest", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.create", "kubectl_create", I, "Create {resourceType} {name} in namespace {namespace}", [F("kubectl-create.ts")],
     "Decided as the object it creates: from a manifest, or by type (a Secret is credential, kube-system/aws-auth access, "
     "a LoadBalancer Service money).",
     [("", "Create Deployment web", {"resourceType": "deployment", "name": "web", "namespace": "shop", "image": "nginx:1.29"}, W, "web"),
      ("-secret", "Create Secret shop-db", {"resourceType": "secret", "secretType": "generic", "name": "shop-db", "namespace": "shop",
                                            "fromLiteral": ["password=EXAMPLE"]}, C, "shop-db"),
      ("-load-balancer", "Create LoadBalancer Service web", {"resourceType": "service", "serviceType": "loadbalancer", "name": "web",
                                                            "namespace": "shop", "tcpPort": ["443:8443"]}, M, "web"),
      ("-aws-auth", "Create ConfigMap aws-auth", {"resourceType": "configmap", "name": "aws-auth", "namespace": "kube-system",
                                                  "fromLiteral": ["mapRoles=- rolearn: arn:aws:iam::111122223333:role/agent"]}, A, "aws-auth")],
     k=dict(action="create", resource="resourceType", name="name", namespace="namespace", manifest="manifest",
            service_type="serviceType", dry_run="dryRun", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.logs", "kubectl_logs", R, "Read the logs of {resourceType} {name} in namespace {namespace}", [F("kubectl-logs.ts")],
     "Reads.", [("", "Read Pod web-0's logs", {"resourceType": "pod", "name": "web-0", "namespace": "shop"}, R, "web-0")],
     k=dict(action="logs", resource="resourceType", name="name", namespace="namespace", container="container", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.scale", "kubectl_scale", W, "Scale {resourceType} {name} in namespace {namespace} to {replicas}",
     [F("kubectl-scale.ts")], "Scaling to zero replicas is delete. The type defaults to deployment, as the server's does.",
     [("", "Scale Deployment web to 3", {"name": "web", "namespace": "shop", "replicas": 3}, W, "web"),
      ("-zero", "Scale StatefulSet postgres to 0", {"resourceType": "statefulset", "name": "postgres", "namespace": "shop", "replicas": 0}, DEL, "postgres")],
     k=dict(action="scale", resource="resourceType", resource_default="deployment", name="name", namespace="namespace",
            replicas="replicas", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.patch", "kubectl_patch", I, "Patch {resourceType} {name} in namespace {namespace}", [F("kubectl-patch.ts")],
     "Decided as the PATCH it sends: a JSON Patch on a pod or workload is access, since Opfence cannot see its result. "
     "A patch in a file on the server's machine keeps this rule's class.",
     [("", "Label Deployment web", {"resourceType": "deployment", "name": "web", "namespace": "shop",
                                    "patchData": {"metadata": {"labels": {"team": "shop"}}}}, W, "web"),
      ("-json", "JSON Patch Deployment web", {"resourceType": "deployment", "name": "web", "namespace": "shop", "patchType": "json",
                                              "patchData": [{"op": "add", "path": "/spec/template/spec/hostNetwork", "value": True}]}, A, "web"),
      ("-privileged", "Make Deployment web privileged", {"resourceType": "deployment", "name": "web", "namespace": "shop",
                                                         "patchData": {"spec": {"template": {"spec": {"containers": [{"name": "web", "securityContext": {"privileged": True}}]}}}}}, A, "web")],
     k=dict(action="patch", resource="resourceType", name="name", namespace="namespace", patch="patchData", patch_type="patchType",
            dry_run="dryRun", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.rollout", "kubectl_rollout", W, "Roll out ({subCommand}) {resourceType} {name} in namespace {namespace}",
     [F("kubectl-rollout.ts")],
     "history and status read; restart, pause and resume change the workload; undo restores an earlier pod template, "
     "which Opfence cannot see, so it is unknown.",
     [("", "Restart Deployment web", {"subCommand": "restart", "resourceType": "deployment", "name": "web", "namespace": "shop"}, W, "web"),
      ("-status", "Read Deployment web's rollout status", {"subCommand": "status", "resourceType": "deployment", "name": "web", "namespace": "shop"}, R, "web"),
      ("-undo", "Undo Deployment web's rollout", {"subCommand": "undo", "resourceType": "deployment", "name": "web", "namespace": "shop"}, U, "web")],
     k=dict(action_arg="subCommand", actions={"history": "get", "status": "get", "restart": "restart", "pause": "pause",
                                               "resume": "resume", "undo": "undo"},
            resource="resourceType", name="name", namespace="namespace", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.generic", "kubectl_generic", I, "Run kubectl {command} {subCommand} {resourceType} {name}", [F("kubectl-generic.ts"),
     FLUX + "src/security/kubectl-flags.ts"],
     "Any kubectl command. The common ones are decided as the requests they send (get, describe, logs, top, delete, "
     "scale, label, annotate, cordon, drain, rollout); flags are not read, except replicas and selector. Every other "
     "command (set, expose, debug, cp, auth, certificate, taint, run, replace, wait) keeps this rule's class.",
     [("", "kubectl get pods", {"command": "get", "resourceType": "pods", "namespace": "shop"}, R, None),
      ("-delete-namespace", "kubectl delete namespace shop", {"command": "delete", "resourceType": "namespace", "name": "shop"}, I, "shop"),
      ("-scale-zero", "kubectl scale deployment web --replicas=0", {"command": "scale", "resourceType": "deployment", "name": "web",
                                                                    "namespace": "shop", "flags": {"replicas": 0}}, DEL, "web"),
      ("-label", "kubectl label pod web-0 team=shop", {"command": "label", "resourceType": "pod", "name": "web-0", "namespace": "shop",
                                                        "args": ["team=shop"]}, W, "web-0"),
      ("-debug", "kubectl debug pod web-0", {"command": "debug", "resourceType": "pod", "name": "web-0", "namespace": "shop",
                                             "flags": {"image": "busybox"}}, I, "web-0")],
     k=dict(action_arg="command", actions={"get": "get", "describe": "describe", "logs": "logs", "top": "get", "delete": "delete",
                                            "scale": "scale", "label": "label", "annotate": "label", "cordon": "cordon",
                                            "uncordon": "uncordon", "drain": "drain"},
            resource="resourceType", name="name", namespace="namespace", all_namespaces="allNamespaces",
            label_selector="flags.selector", replicas="flags.replicas", **FCTX), res="name")
tool("kubernetes-mcp.kubectl.context", "kubectl_context", W, "{operation} the kubeconfig context {name}", [F("kubectl-context.ts")],
     "list and get read; set changes which cluster later calls reach.",
     [("", "Switch to context prod", {"operation": "set", "name": "prod"}, W, None),
      ("-list", "List contexts", {"operation": "list"}, R, None)],
     when=[('{ arg: operation, in: ["list", "get"] }', R)])
for name, card, f in [("kubectl_reconnect", "Reconnect to the cluster", "kubectl-reconnect.ts"), ("ping", "Check the server", "ping.ts"),
                      ("explain_resource", "Explain {resource}", "kubectl-operations.ts"), ("list_api_resources", "List API resources", "kubectl-operations.ts"),
                      ("stop_port_forward", "Stop port forward {id}", "port_forward.ts")]:
    tool("kubernetes-mcp." + name.replace("_", "-"), name, R, card, [F(f)],
         "Stops a local process." if name == "stop_port_forward" else "Reads.",
         [("", card.replace("{resource}", "deployments").replace("{id}", "pf-1"), {"id": "pf-1"} if name == "stop_port_forward" else {}, R, None)])
tool("kubernetes-mcp.exec-in-pod", "exec_in_pod", I, "Run {command} in Pod {name} in namespace {namespace}", [F("exec_in_pod.ts")],
     "Runs a command in a container, with its access to data, secrets and the network.",
     [("", "Run env in Pod web-0", {"name": "web-0", "namespace": "shop", "command": ["sh", "-c", "env"]}, I, "web-0"),
      ("-string", "Run a shell command in Pod web-0", {"name": "web-0", "command": "rm -rf /data"}, I, "web-0")],
     k=dict(action="exec", name="name", namespace="namespace", command="command", container="container", **FCTX), res="name")
tool("kubernetes-mcp.port-forward", "port_forward", A, "Forward port {targetPort} of {resourceType} {resourceName} in namespace {namespace}",
     [F("port_forward.ts")], "Opens the pod's port on the server's machine, past the cluster's network policies.",
     [("", "Forward Service db's port 5432", {"resourceType": "service", "resourceName": "db", "localPort": 15432, "targetPort": 5432, "namespace": "shop"}, A, "db")],
     k=dict(action="portforward", resource="resourceType", name="resourceName", namespace="namespace", ports="targetPort", **FCTX), res="resourceName")
tool("kubernetes-mcp.node-management", "node_management", W, "{operation} node {nodeName}", [F("node-management.ts")],
     "cordon and uncordon mark the node; drain also evicts every pod on it (delete).",
     [("", "Cordon node ip-10-0-1-23", {"operation": "cordon", "nodeName": "ip-10-0-1-23"}, W, "ip-10-0-1-23"),
      ("-drain", "Drain node ip-10-0-1-23", {"operation": "drain", "nodeName": "ip-10-0-1-23", "ignoreDaemonsets": True, "confirmDrain": True}, DEL, "ip-10-0-1-23")],
     k=dict(action_arg="operation", actions={"cordon": "cordon", "uncordon": "uncordon", "drain": "drain"}, name="nodeName", **CTX),
     res="nodeName")
F_HELM = F("helm-operations.ts")
for name, verb in [("install_helm_chart", "Install"), ("upgrade_helm_chart", "Upgrade")]:
    tool("kubernetes-mcp.helm." + name.split("_")[0] + "-chart", name, I, verb + " chart {chart} as release {name} in namespace {namespace}", [F_HELM],
         "A chart's templates can create any object, role bindings and privileged pods included, and its hooks run jobs; "
         "Opfence cannot see them.",
         [("", verb + " chart bitnami/postgresql", {"name": "db", "chart": "bitnami/postgresql", "namespace": "shop",
                                                    "repo": "https://charts.bitnami.com/bitnami"}, I, "db")], res="name")
tool("kubernetes-mcp.helm.uninstall-chart", "uninstall_helm_chart", I, "Uninstall release {name} in namespace {namespace}", [F_HELM],
     "Deletes every object the release made.", [("", "Uninstall release db", {"name": "db", "namespace": "shop"}, I, "db")], res="name")


# ---------------------------------------------------------------------------
def flow(v):
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{k}: {flow(x)}" for k, x in v.items()) + " }"
    if isinstance(v, str):
        return v if v.replace(".", "").replace("_", "").isalnum() else json.dumps(v)
    return json.dumps(v)

def wrap(text, indent="      ", width=100):
    out, line = [], indent
    for w in text.split():
        if len(line) + len(w) + 1 > width and line.strip():
            out.append(line)
            line = indent
        line += ("" if not line.strip() else " ") + w
    out.append(line)
    return out

files = {"kubernetes-mcp-server.yaml": [], "mcp-server-kubernetes.yaml": []}
fixtures = {}
seen = set()
for t in T:
    f = "mcp-server-kubernetes.yaml" if t["src"][0].startswith(FLUX) else "kubernetes-mcp-server.yaml"
    if t["id"] in seen or t["tool"] in seen:
        raise SystemExit(f"duplicate {t['id']} {t['tool']}")
    seen |= {t["id"], t["tool"]}
    L = files[f]
    L += [f"  - id: {t['id']}", f"    match: {{ mcp: {{ tool: {t['tool']} }} }}", f"    class: {t['cls']}"]
    if t["k"]:
        k = dict(t["k"])
        L += ["    classify:", "      provider: kubernetes", "      kubernetes:"]
        for key, v in k.items():
            L.append(f"        {key}: {flow(v)}")
    if t["when"]:
        L.append("    when:")
        for cond, cls in t["when"]:
            L += [f"      - if: {cond}", f"        class: {cls}"]
    if t["res"]:
        L.append(f"    resource: {{ arg: {t['res']}, kind: k8s-resource }}")
    L += [f"    card: {json.dumps(t['card'])}", "    status: verified", f"    verified: {DATE}", "    sources:"]
    L += [f"      - {u}" for u in t["src"]]
    L += ["    notes: >-"] + wrap(t["notes"])
    L.append("    tests:")
    base = t["tool"].replace("_", "-")
    for suffix, desc, args, exp, res in t["tests"]:
        name = base + suffix + ".json"
        if name in fixtures:
            raise SystemExit("duplicate fixture " + name)
        fixtures[name] = json.dumps({"description": desc, "tool": t["tool"], "arguments": args}, indent=2) + "\n"
        L += [f"      - fixture: fixtures/{name}", f"        expect: {exp}"]
        if res:
            L.append(f"        resource: {json.dumps(res)}")
    L.append("")

os.makedirs(D + "fixtures", exist_ok=True)
for f in os.listdir(D + "fixtures"):
    os.remove(D + "fixtures/" + f)
for name, text in fixtures.items():
    open(D + "fixtures/" + name, "w").write(text)
head = {"kubernetes-mcp-server.yaml": "# containers/kubernetes-mcp-server: the core, config and helm toolsets (the defaults).",
        "mcp-server-kubernetes.yaml": "# Flux159/mcp-server-kubernetes (npm mcp-server-kubernetes)."}
for f, L in files.items():
    open(D + f, "w").write("\n".join([head[f], "# Generated by tools/catalog-gen/kubemcpgen.py.", "operations:"] + L))
print(len(T), "rules,", len(fixtures), "fixtures")
