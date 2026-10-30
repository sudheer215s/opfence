package decode

import (
	"bytes"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

// The testdata pairs were written by tools/kubeprotogen/check, which
// encodes each object as client-go (and kubectl) does; its own test checks
// every built-in kind with random values the same way.
func TestKubeProtobufCases(t *testing.T) {
	files, err := filepath.Glob("testdata/kubeproto/*.pb")
	if err != nil || len(files) == 0 {
		t.Fatalf("no testdata: %v", err)
	}
	for _, f := range files {
		name := strings.TrimSuffix(filepath.Base(f), ".pb")
		t.Run(name, func(t *testing.T) {
			pb, err := os.ReadFile(f)
			if err != nil {
				t.Fatal(err)
			}
			js, err := os.ReadFile(strings.TrimSuffix(f, ".pb") + ".json")
			if err != nil {
				t.Fatal(err)
			}
			got, err := ParseKubeProtobuf(pb)
			if err != nil {
				t.Fatal(err)
			}
			want, err := parseJSON(bytes.TrimSpace(js))
			if err != nil {
				t.Fatal(err)
			}
			for _, d := range kpCompare(got, want, "") {
				t.Error(d)
			}
		})
	}
}

// The values conditions read, through the REST decoder as a rule sees them.
func TestKubeProtobufREST(t *testing.T) {
	body := func(name string) string {
		b, err := os.ReadFile("testdata/kubeproto/" + name + ".pb")
		if err != nil {
			t.Fatal(err)
		}
		return base64.StdEncoding.EncodeToString(b)
	}
	op := func(name, ct string) Operation {
		return Decode(fixture(t, "# body: base64\nPOST /apis/apps/v1/namespaces/shop/deployments HTTP/1.1\nHost: x.eks.amazonaws.com\nContent-Type: "+ct+"\n\n"+body(name)), Hints{})[0]
	}
	o := op("deployment-privileged", "application/vnd.kubernetes.protobuf")
	if o.BodyErr != "" {
		t.Fatal(o.BodyErr)
	}
	for path, want := range map[string]any{
		"body.kind":                                     "Deployment",
		"body.apiVersion":                               "apps/v1",
		"body.metadata.name":                            "node-shell",
		"body.spec.replicas":                            json.Number("1"),
		"body.spec.template.spec.hostNetwork":           true,
		"body.spec.template.spec.hostPID":               false,
		"body.spec.template.spec.volumes.hostPath.path": []any{"/"},
		"body.spec.template.spec.containers.securityContext.privileged":           []any{true},
		"body.spec.template.spec.initContainers.securityContext.capabilities.add": []any{[]any{"SYS_ADMIN"}},
		"body.spec.template.spec.containers.resources.limits.cpu":                 []any{"500m"},
		"body.spec.template.spec.containers.livenessProbe.httpGet.port":           []any{json.Number("8080")},
	} {
		got, ok := kpLookup(o.Args, path)
		if !ok || !reflect.DeepEqual(got, want) {
			t.Errorf("%s = %#v (%v), want %#v", path, got, ok, want)
		}
	}
	// The media type decides, as it does for the API server: protobuf sent
	// as JSON is unreadable, and so is a protobuf type without the prefix.
	if o := op("deployment-privileged", "application/json"); o.BodyErr == "" {
		t.Error("protobuf body sent as JSON was read")
	}
	jsonBody := Decode(fixture(t, "POST /api/v1/namespaces/shop/pods HTTP/1.1\nHost: x.eks.amazonaws.com\nContent-Type: application/vnd.kubernetes.protobuf; charset=x\n\n{\"kind\":\"Pod\"}"), Hints{})[0]
	if !strings.Contains(jsonBody.BodyErr, "prefix") {
		t.Errorf("JSON sent as protobuf: BodyErr = %q", jsonBody.BodyErr)
	}
}

func TestKubeProtoSchema(t *testing.T) {
	if v := KubeProtoVersion(); v != "v1.37.2" {
		t.Errorf("KubeProtoVersion = %q", v)
	}
	s, err := kubeProto()
	if err != nil {
		t.Fatal(err)
	}
	for _, k := range []string{"v1 Pod", "apps/v1 Deployment", "batch/v1 CronJob", "v1 DeleteOptions", "autoscaling/v1 Scale",
		"apps/v1beta2 Deployment", "rbac.authorization.k8s.io/v1 ClusterRoleBinding", "apiextensions.k8s.io/v1 CustomResourceDefinition",
		"apiregistration.k8s.io/v1 APIService", "policy/v1 Eviction"} {
		if s.kinds[k] == nil {
			t.Errorf("no kind %s", k)
		}
	}
}

// Protobuf builders for malformed bodies.
func pbKey(num, wire int) []byte { return binary.AppendUvarint(nil, uint64(num<<3|wire)) }
func pbBytes(num int, b []byte) []byte {
	return append(binary.AppendUvarint(pbKey(num, 2), uint64(len(b))), b...)
}
func pbVarint(num int, v uint64) []byte { return binary.AppendUvarint(pbKey(num, 0), v) }
func pbJoin(parts ...[]byte) []byte     { return bytes.Join(parts, nil) }
func pbObject(apiVersion, kind string, raw []byte, extra ...[]byte) []byte {
	env := pbJoin(pbBytes(1, pbJoin(pbBytes(1, []byte(apiVersion)), pbBytes(2, []byte(kind)))), pbBytes(2, raw))
	return append([]byte("k8s\x00"), pbJoin(append([][]byte{env}, extra...)...)...)
}

func TestKubeProtobufMalformed(t *testing.T) {
	meta := pbBytes(1, pbBytes(1, []byte("p"))) // ObjectMeta{name: p}
	spec := func(f ...[]byte) []byte { return pbBytes(2, pbJoin(f...)) }
	ok := []struct {
		name string
		body []byte
		path string
		want any
	}{
		// Field numbers the schema does not know are skipped, as the
		// API server skips them.
		{"unknown field", pbObject("v1", "Pod", pbJoin(meta, pbVarint(999, 1), spec(pbVarint(11, 1)))), "spec.hostNetwork", true},
		{"repeated string", pbObject("v1", "Pod", pbJoin(meta, spec(pbBytes(2, pbJoin(pbBytes(1, []byte("c")), pbBytes(15, pbBytes(1, pbJoin(pbBytes(1, []byte("NET_ADMIN")), pbBytes(1, []byte("BPF")))))))))), "spec.containers.securityContext.capabilities.add", []any{[]any{"NET_ADMIN", "BPF"}}},
		{"packed repeated", pbObject("v1", "Pod", pbJoin(meta, spec(pbBytes(14, pbBytes(4, []byte{1, 2, 0x80, 1}))))), "spec.securityContext.supplementalGroups", []any{json.Number("1"), json.Number("2"), json.Number("128")}},
		{"negative int32", pbObject("apps/v1", "Deployment", pbJoin(meta, spec(pbVarint(1, math.MaxUint64)))), "spec.replicas", json.Number("-1")},
		{"empty map value", pbObject("v1", "ConfigMap", pbJoin(meta, pbBytes(2, pbBytes(1, []byte("k"))))), "data.k", ""},
	}
	for _, c := range ok {
		v, err := ParseKubeProtobuf(c.body)
		if err != nil {
			t.Errorf("%s: %v", c.name, err)
			continue
		}
		got, found := kpLookup(map[string]any{"b": v}, "b."+c.path)
		if !found || !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: %s = %#v, want %#v", c.name, c.path, got, c.want)
		}
	}
	// A CRD's schema: spec.versions[].schema.openAPIV3Schema.
	crd := func(schema []byte) []byte {
		return pbObject("apiextensions.k8s.io/v1", "CustomResourceDefinition",
			pbJoin(meta, pbBytes(2, pbBytes(7, pbJoin(pbBytes(1, []byte("v1")), pbBytes(4, pbBytes(1, schema)))))))
	}
	deep := pbBytes(5, []byte("string"))
	for range 70 {
		deep = pbBytes(29, pbJoin(pbBytes(1, []byte("k")), pbBytes(2, deep))) // properties: {k: ...}
	}
	nan := binary.LittleEndian.AppendUint64(pbKey(11, 1), math.Float64bits(math.NaN())) // minimum
	bad := map[string][]byte{
		"no prefix":          []byte("\x0a\x00"),
		"unknown kind":       pbObject("example.com/v1", "Widget", meta),
		"envelope encoding":  pbObject("v1", "Pod", meta, pbBytes(3, []byte("gzip"))),
		"envelope twice":     pbObject("v1", "Pod", meta, pbBytes(2, meta)),
		"field twice":        pbObject("v1", "Pod", pbJoin(meta, spec(pbVarint(11, 0), pbVarint(11, 1)))),
		"message twice":      pbObject("v1", "Pod", pbJoin(meta, spec(), spec(pbVarint(11, 1)))),
		"map key twice":      pbObject("v1", "ConfigMap", pbJoin(meta, pbBytes(2, pbJoin(pbBytes(1, []byte("k")), pbBytes(2, []byte("a")))), pbBytes(2, pbJoin(pbBytes(1, []byte("k")), pbBytes(2, []byte("b")))))),
		"wrong wire type":    pbObject("v1", "Pod", pbJoin(meta, spec(pbBytes(11, []byte{1})))),
		"truncated":          pbObject("v1", "Pod", pbJoin(meta, []byte{0x12, 0x05, 0x58})),
		"group":              pbObject("v1", "Pod", pbJoin(meta, pbKey(5, 3))),
		"field zero":         pbObject("v1", "Pod", pbJoin(meta, pbVarint(0, 1))),
		"bad UTF-8":          pbObject("v1", "Pod", pbBytes(1, pbBytes(1, []byte{0xff}))),
		"too deep":           crd(deep),
		"not a number":       crd(nan),
		"raw extension junk": pbObject("apps/v1", "ControllerRevision", pbJoin(meta, pbBytes(2, pbBytes(1, []byte("{nope"))))),
	}
	if v, err := ParseKubeProtobuf(crd(pbBytes(5, []byte("object")))); err != nil {
		t.Errorf("a CRD: %v", err)
	} else if got, _ := kpLookup(v, "spec.versions.schema.openAPIV3Schema.type"); !reflect.DeepEqual(got, []any{"object"}) {
		t.Errorf("a CRD's schema type = %v", got)
	}
	for name, b := range bad {
		if v, err := ParseKubeProtobuf(b); err == nil {
			t.Errorf("%s: read as %v", name, v)
		}
	}
}

// kpLookup follows a dotted path, through lists, as rule conditions do.
func kpLookup(v any, path string) (any, bool) {
	for i, k := range strings.Split(path, ".") {
		switch x := v.(type) {
		case map[string]any:
			n, ok := x[k]
			if !ok {
				return nil, false
			}
			v = n
		case []any:
			var out []any
			rest := strings.Join(strings.Split(path, ".")[i:], ".")
			for _, e := range x {
				if got, ok := kpLookup(e, rest); ok {
					out = append(out, got)
				}
			}
			return out, len(out) > 0
		default:
			return nil, false
		}
	}
	return v, true
}

// kpCompare lists where got (decoded protobuf) differs from want (the JSON):
// a JSON value missing or different, or a value only got has that is not a
// zero value (protobuf writes the fields JSON leaves out as empty).
func kpCompare(got, want any, path string) []string {
	switch w := want.(type) {
	case nil:
		if kpIsZero(got) {
			return nil
		}
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			break
		}
		var out []string
		for k, v := range w {
			if gv, ok := g[k]; ok {
				out = append(out, kpCompare(gv, v, path+"."+k)...)
			} else if !kpIsZero(v) {
				out = append(out, path+"."+k+": not in protobuf")
			}
		}
		for k, v := range g {
			if _, ok := w[k]; !ok && !kpIsZero(v) {
				out = append(out, fmt.Sprintf("%s.%s: only in protobuf: %v", path, k, v))
			}
		}
		return out
	case []any:
		g, ok := got.([]any)
		if !ok || len(g) != len(w) {
			break
		}
		var out []string
		for i := range w {
			out = append(out, kpCompare(g[i], w[i], fmt.Sprintf("%s[%d]", path, i))...)
		}
		return out
	case json.Number:
		g, _ := got.(json.Number)
		a, _ := new(big.Float).SetString(string(g))
		b, _ := new(big.Float).SetString(string(w))
		if a != nil && b != nil && a.Cmp(b) == 0 {
			return nil
		}
	default:
		if reflect.DeepEqual(got, want) {
			return nil
		}
	}
	return []string{fmt.Sprintf("%s: JSON %v, protobuf %v", path, want, got)}
}

func kpIsZero(v any) bool {
	switch x := v.(type) {
	case nil:
		return true
	case bool:
		return !x
	case string:
		return x == ""
	case json.Number:
		f, _ := new(big.Float).SetString(string(x))
		return f != nil && f.Sign() == 0
	case []any:
		return len(x) == 0
	case map[string]any:
		for _, e := range x {
			if !kpIsZero(e) {
				return false
			}
		}
		return true
	}
	return false
}

// FuzzKubeProtobuf checks that any body either fails or reads as a JSON
// object with the envelope's apiVersion and kind, without panicking.
func FuzzKubeProtobuf(f *testing.F) {
	files, _ := filepath.Glob("testdata/kubeproto/*.pb")
	for _, file := range files {
		if b, err := os.ReadFile(file); err == nil {
			f.Add(b)
		}
	}
	f.Fuzz(func(t *testing.T, body []byte) {
		v, err := ParseKubeProtobuf(body)
		if err != nil {
			return
		}
		obj, ok := v.(map[string]any)
		if !ok || obj["apiVersion"] == nil || obj["kind"] == nil {
			t.Fatalf("read as %#v", v)
		}
		if _, err := json.Marshal(obj); err != nil {
			t.Fatal(err)
		}
	})
}
