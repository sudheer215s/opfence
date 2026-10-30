// Command check writes the protobuf bodies of hand-built objects, encoded
// as client-go (and so kubectl) encodes them, with their JSON, for
// internal/decode's tests and catalog/kubernetes' fixtures:
//
//	cd tools/kubeprotogen/check && go run . ../../../internal/decode/testdata/kubeproto
//
// Its test fills every built-in kind with random values and checks that
// internal/decode reads each one's protobuf as its JSON.
package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	autoscalingv1 "k8s.io/api/autoscaling/v1"
	batchv1 "k8s.io/api/batch/v1"
	certv1 "k8s.io/api/certificates/v1"
	coordv1 "k8s.io/api/coordination/v1"
	corev1 "k8s.io/api/core/v1"
	rbacv1 "k8s.io/api/rbac/v1"
	apiextv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/serializer/protobuf"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/client-go/kubernetes/scheme"
)

func ptr[T any](v T) *T { return &v }

func main() {
	out := os.Args[1]
	s := scheme.Scheme
	if err := apiextv1.AddToScheme(s); err != nil {
		panic(err)
	}
	ser := protobuf.NewSerializer(s, s)
	priv := corev1.PodSpec{
		HostNetwork: true,
		Containers: []corev1.Container{{
			Name: "shell", Image: "busybox", Command: []string{"sleep", "3600"},
			SecurityContext: &corev1.SecurityContext{Privileged: ptr(true)},
			Resources:       corev1.ResourceRequirements{Limits: corev1.ResourceList{"cpu": resource.MustParse("500m"), "memory": resource.MustParse("128Mi")}},
			LivenessProbe:   &corev1.Probe{ProbeHandler: corev1.ProbeHandler{HTTPGet: &corev1.HTTPGetAction{Path: "/healthz", Port: intstr.FromInt32(8080)}}},
		}},
		InitContainers: []corev1.Container{{
			Name: "init", Image: "busybox",
			SecurityContext: &corev1.SecurityContext{Capabilities: &corev1.Capabilities{Add: []corev1.Capability{"SYS_ADMIN"}}},
		}},
		Volumes: []corev1.Volume{{Name: "root", VolumeSource: corev1.VolumeSource{HostPath: &corev1.HostPathVolumeSource{Path: "/"}}}},
	}
	plain := corev1.PodSpec{Containers: []corev1.Container{{Name: "web", Image: "nginx:1.29", Ports: []corev1.ContainerPort{{ContainerPort: 80}}}}}
	labels := map[string]string{"app": "web"}
	tmpl := func(spec corev1.PodSpec) corev1.PodTemplateSpec {
		return corev1.PodTemplateSpec{ObjectMeta: metav1.ObjectMeta{Labels: labels}, Spec: spec}
	}
	meta := func(name, ns string) metav1.ObjectMeta { return metav1.ObjectMeta{Name: name, Namespace: ns} }
	cases := map[string]runtime.Object{
		"deployment-privileged": &appsv1.Deployment{ObjectMeta: meta("node-shell", "shop"), Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(1)), Selector: &metav1.LabelSelector{MatchLabels: labels}, Template: tmpl(priv)}},
		"deployment-plain": &appsv1.Deployment{ObjectMeta: meta("web", "shop"), Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(3)), Selector: &metav1.LabelSelector{MatchLabels: labels}, Template: tmpl(plain),
			Strategy: appsv1.DeploymentStrategy{Type: appsv1.RollingUpdateDeploymentStrategyType, RollingUpdate: &appsv1.RollingUpdateDeployment{MaxSurge: ptr(intstr.FromString("25%"))}}}},
		"deployment-zero": &appsv1.Deployment{ObjectMeta: meta("web", "shop"), Spec: appsv1.DeploymentSpec{
			Replicas: ptr(int32(0)), Selector: &metav1.LabelSelector{MatchLabels: labels}, Template: tmpl(plain)}},
		"pod-host-pid": &corev1.Pod{ObjectMeta: meta("debug", "shop"), Spec: corev1.PodSpec{HostPID: true, Containers: plain.Containers}},
		"cronjob-privileged": &batchv1.CronJob{ObjectMeta: meta("nightly", "shop"), Spec: batchv1.CronJobSpec{Schedule: "0 3 * * *",
			JobTemplate: batchv1.JobTemplateSpec{Spec: batchv1.JobSpec{Template: tmpl(priv)}}}},
		"service-load-balancer": &corev1.Service{ObjectMeta: meta("web", "shop"), Spec: corev1.ServiceSpec{Type: corev1.ServiceTypeLoadBalancer,
			Selector: labels, Ports: []corev1.ServicePort{{Port: 80, TargetPort: intstr.FromInt32(8080), Protocol: corev1.ProtocolTCP}}}},
		"service-cluster-ip": &corev1.Service{ObjectMeta: meta("web", "shop"), Spec: corev1.ServiceSpec{
			Selector: labels, Ports: []corev1.ServicePort{{Port: 80, TargetPort: intstr.FromString("http")}}}},
		"configmap-aws-auth": &corev1.ConfigMap{ObjectMeta: meta("aws-auth", "kube-system"),
			Data:       map[string]string{"mapRoles": "- rolearn: arn:aws:iam::111122223333:role/agent\n  username: agent\n  groups: [system:masters]\n"},
			BinaryData: map[string][]byte{"blob": {0, 1, 2, 255}}},
		"secret":     &corev1.Secret{ObjectMeta: meta("db", "shop"), Type: corev1.SecretTypeOpaque, Data: map[string][]byte{"password": []byte("hunter2")}},
		"scale-zero": &autoscalingv1.Scale{ObjectMeta: meta("web", "shop"), Spec: autoscalingv1.ScaleSpec{Replicas: 0}},
		"clusterrolebinding": &rbacv1.ClusterRoleBinding{ObjectMeta: meta("agent-admin", ""),
			RoleRef:  rbacv1.RoleRef{APIGroup: "rbac.authorization.k8s.io", Kind: "ClusterRole", Name: "cluster-admin"},
			Subjects: []rbacv1.Subject{{Kind: "User", APIGroup: "rbac.authorization.k8s.io", Name: "agent"}}},
		"csr": &certv1.CertificateSigningRequest{ObjectMeta: meta("agent", ""), Spec: certv1.CertificateSigningRequestSpec{
			Request: []byte("-----BEGIN CERTIFICATE REQUEST-----\n"), SignerName: "kubernetes.io/kube-apiserver-client",
			Usages: []certv1.KeyUsage{certv1.UsageClientAuth}, Extra: map[string]certv1.ExtraValue{"scopes": {"a", "b"}}, ExpirationSeconds: ptr(int32(3600))}},
		"lease": &coordv1.Lease{ObjectMeta: meta("leader", "kube-system"), Spec: coordv1.LeaseSpec{HolderIdentity: ptr("node-1"),
			LeaseDurationSeconds: ptr(int32(15)), RenewTime: ptr(metav1.NewMicroTime(time.Date(2026, 10, 30, 1, 2, 3, 456789000, time.UTC))),
			AcquireTime: ptr(metav1.NewMicroTime(time.Date(2026, 10, 30, 1, 0, 0, 0, time.UTC)))}},
		"crd": &apiextv1.CustomResourceDefinition{ObjectMeta: meta("widgets.example.com", ""), Spec: apiextv1.CustomResourceDefinitionSpec{
			Group: "example.com", Scope: apiextv1.NamespaceScoped,
			Names: apiextv1.CustomResourceDefinitionNames{Plural: "widgets", Kind: "Widget"},
			Versions: []apiextv1.CustomResourceDefinitionVersion{{Name: "v1", Served: true, Storage: true, Schema: &apiextv1.CustomResourceValidation{
				OpenAPIV3Schema: &apiextv1.JSONSchemaProps{Type: "object", XPreserveUnknownFields: ptr(true),
					Properties: map[string]apiextv1.JSONSchemaProps{
						"spec": {Type: "object", Required: []string{"size"}, AdditionalProperties: &apiextv1.JSONSchemaPropsOrBool{Allows: false},
							Properties: map[string]apiextv1.JSONSchemaProps{
								"size":  {Type: "integer", Minimum: ptr(1.5), Default: &apiextv1.JSON{Raw: []byte(`3`)}},
								"tags":  {Type: "array", Items: &apiextv1.JSONSchemaPropsOrArray{Schema: &apiextv1.JSONSchemaProps{Type: "string"}}, XListType: ptr("set")},
								"ports": {XIntOrString: true, AnyOf: []apiextv1.JSONSchemaProps{{Type: "integer"}, {Type: "string"}}},
							}},
					}, XValidations: apiextv1.ValidationRules{{Rule: "self.spec.size < 10"}}}}}},
		}},
	}
	for name, obj := range cases {
		gvks, _, err := s.ObjectKinds(obj)
		if err != nil {
			panic(err)
		}
		obj.GetObjectKind().SetGroupVersionKind(gvks[0])
		var pb bytes.Buffer
		if err := ser.Encode(obj, &pb); err != nil {
			panic(err)
		}
		js, err := json.Marshal(obj)
		if err != nil {
			panic(err)
		}
		os.WriteFile(filepath.Join(out, name+".pb"), pb.Bytes(), 0o644)
		os.WriteFile(filepath.Join(out, name+".json"), append(js, '\n'), 0o644)
	}
}
