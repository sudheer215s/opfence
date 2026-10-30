package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"reflect"
	"sort"
	"strings"
	"testing"
	"time"

	"github.com/rakeshnitb23/opfence/internal/decode"
	apiextv1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	apiextv1b1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/runtime/serializer/protobuf"
	"k8s.io/apimachinery/pkg/util/intstr"
	"k8s.io/client-go/kubernetes/scheme"
	aggv1 "k8s.io/kube-aggregator/pkg/apis/apiregistration/v1"
	aggv1b1 "k8s.io/kube-aggregator/pkg/apis/apiregistration/v1beta1"
	"sigs.k8s.io/randfill"
)

// notBodies are kinds no request carries as its body, or that the API
// server no longer serves (extensions/v1beta1, rollbacks).
func notBody(gvk schema.GroupVersionKind) bool {
	k := gvk.Kind
	return strings.HasSuffix(k, "List") || strings.HasSuffix(k, "Options") || k == "WatchEvent" ||
		k == "ConversionReview" || k == "SerializedReference" || k == "DeploymentRollback" || gvk.Group == "extensions"
}

// TestRoundTrip fills every built-in kind with random values, encodes it as
// client-go does, and checks that decode reads the protobuf as the object's
// JSON: every JSON value is there, and what only the protobuf has is a zero
// value (protobuf writes the fields JSON leaves out as empty).
func TestRoundTrip(t *testing.T) {
	s := runtime.NewScheme()
	for _, add := range []func(*runtime.Scheme) error{scheme.AddToScheme, apiextv1.AddToScheme, apiextv1b1.AddToScheme, aggv1.AddToScheme, aggv1b1.AddToScheme} {
		if err := add(s); err != nil {
			t.Fatal(err)
		}
	}
	ser := protobuf.NewSerializer(s, s)
	var gvks []schema.GroupVersionKind
	for gvk := range s.AllKnownTypes() {
		if gvk.Version != runtime.APIVersionInternal && !notBody(gvk) {
			gvks = append(gvks, gvk)
		}
	}
	sort.Slice(gvks, func(i, j int) bool { return gvks[i].String() < gvks[j].String() })
	n := 0
	for _, gvk := range gvks {
		for _, cfg := range []struct {
			nil   float64
			elems int
		}{{0.25, 2}, {0.05, 3}, {0.5, 1}} {
			for seed := int64(0); seed < 3; seed++ {
				obj, err := s.New(gvk)
				if err != nil {
					t.Fatal(err)
				}
				filler(seed*7919+int64(len(gvk.String())), cfg.nil, cfg.elems).Fill(obj)
				obj.GetObjectKind().SetGroupVersionKind(gvk)
				var pb bytes.Buffer
				if err := ser.Encode(obj, &pb); err != nil {
					t.Fatalf("%s: %v", gvk, err)
				}
				js, err := json.Marshal(obj)
				if err != nil {
					t.Fatalf("%s: %v", gvk, err)
				}
				got, err := decode.ParseKubeProtobuf(pb.Bytes())
				if err != nil {
					t.Errorf("%s: %v", gvk, err)
					continue
				}
				dec := json.NewDecoder(bytes.NewReader(js))
				dec.UseNumber()
				var want any
				if err := dec.Decode(&want); err != nil {
					t.Fatal(err)
				}
				for _, d := range Compare(got, want, "") {
					t.Errorf("%s: %s", gvk, d)
				}
				n++
			}
		}
	}
	t.Logf("%d objects of %d kinds", n, len(gvks))
}

func filler(seed int64, nilChance float64, elems int) *randfill.Filler {
	const letters = "abcdefghijklmnopqrstuvwxyzABC-._/"
	str := func(c randfill.Continue) string {
		b := make([]byte, c.Intn(6)+1)
		for i := range b {
			b[i] = letters[c.Intn(len(letters))]
		}
		return string(b)
	}
	return randfill.NewWithSeed(seed).NilChance(nilChance).NumElements(1, elems).MaxDepth(9).Funcs(
		func(q *resource.Quantity, c randfill.Continue) {
			*q = resource.MustParse([]string{"100m", "1Gi", "5", "2500Mi"}[c.Intn(4)])
		},
		// JSON writes times to the second (MicroTime to the microsecond).
		func(t *metav1.Time, c randfill.Continue) {
			*t = metav1.NewTime(time.Unix(1700000000+int64(c.Intn(100000)), 0))
		},
		func(t *metav1.MicroTime, c randfill.Continue) {
			*t = metav1.NewMicroTime(time.Unix(1700000000+int64(c.Intn(100000)), int64(c.Intn(1000000))*1000))
		},
		func(d *metav1.Duration, c randfill.Continue) {
			d.Duration = time.Duration(c.Intn(100000)) * time.Millisecond
		},
		func(i *intstr.IntOrString, c randfill.Continue) {
			if c.Bool() {
				*i = intstr.FromInt32(int32(c.Intn(70000)) - 100)
			} else {
				*i = intstr.FromString(str(c))
			}
		},
		func(r *runtime.RawExtension, c randfill.Continue) { r.Raw = []byte(`{"a":1,"b":["x"]}`) },
		func(r *metav1.FieldsV1, c randfill.Continue) { r.SetRawBytes([]byte(`{"f:spec":{}}`)) },
		func(j *apiextv1.JSON, c randfill.Continue) { j.Raw = []byte(`{"x":true}`) },
		func(j *apiextv1b1.JSON, c randfill.Continue) { j.Raw = []byte(`[1,2]`) },
		func(p *apiextv1.JSONSchemaPropsOrBool, c randfill.Continue) {
			if c.Bool() {
				*p = apiextv1.JSONSchemaPropsOrBool{Allows: c.Bool()}
			} else {
				*p = apiextv1.JSONSchemaPropsOrBool{Allows: true, Schema: &apiextv1.JSONSchemaProps{Type: "string"}}
			}
		},
		func(p *apiextv1.JSONSchemaPropsOrArray, c randfill.Continue) {
			if c.Bool() {
				*p = apiextv1.JSONSchemaPropsOrArray{Schema: &apiextv1.JSONSchemaProps{Type: "integer"}}
			} else {
				*p = apiextv1.JSONSchemaPropsOrArray{JSONSchemas: []apiextv1.JSONSchemaProps{{Type: "a"}, {Type: "b"}}}
			}
		},
		func(p *apiextv1.JSONSchemaPropsOrStringArray, c randfill.Continue) {
			if c.Bool() {
				*p = apiextv1.JSONSchemaPropsOrStringArray{Schema: &apiextv1.JSONSchemaProps{Type: "object"}}
			} else {
				*p = apiextv1.JSONSchemaPropsOrStringArray{Property: []string{"p", "q"}}
			}
		},
		func(p *apiextv1b1.JSONSchemaPropsOrBool, c randfill.Continue) {
			*p = apiextv1b1.JSONSchemaPropsOrBool{Allows: c.Bool()}
		},
		func(p *apiextv1b1.JSONSchemaPropsOrArray, c randfill.Continue) {
			*p = apiextv1b1.JSONSchemaPropsOrArray{JSONSchemas: []apiextv1b1.JSONSchemaProps{{Type: "a"}}}
		},
		func(p *apiextv1b1.JSONSchemaPropsOrStringArray, c randfill.Continue) {
			*p = apiextv1b1.JSONSchemaPropsOrStringArray{Property: []string{"p"}}
		},
		// A schema's own fields, set by hand: random ones recurse without end.
		func(p *apiextv1.JSONSchemaProps, c randfill.Continue) {
			ref, lt, yes := "#/x", "map", true
			*p = apiextv1.JSONSchemaProps{Type: str(c), ID: str(c), Ref: &ref, Description: str(c), XListType: &lt,
				XPreserveUnknownFields: &yes, XEmbeddedResource: c.Bool(), XIntOrString: c.Bool(),
				Properties:           map[string]apiextv1.JSONSchemaProps{"inner": {Type: "string", Default: &apiextv1.JSON{Raw: []byte(`"d"`)}}},
				Items:                &apiextv1.JSONSchemaPropsOrArray{Schema: &apiextv1.JSONSchemaProps{Type: "integer"}},
				AdditionalProperties: &apiextv1.JSONSchemaPropsOrBool{Allows: false},
				Dependencies:         apiextv1.JSONSchemaDependencies{"d": {Property: []string{"e"}}},
				XValidations:         apiextv1.ValidationRules{{Rule: "self > 0", Message: "m"}},
				Minimum:              func() *float64 { f := 1.5; return &f }()}
		},
		func(p *apiextv1b1.JSONSchemaProps, c randfill.Continue) {
			*p = apiextv1b1.JSONSchemaProps{Type: str(c), Properties: map[string]apiextv1b1.JSONSchemaProps{"inner": {Type: "string"}}}
		},
		func(s *string, c randfill.Continue) { *s = str(c) },
		func(f *float64, c randfill.Continue) { *f = float64(c.Intn(1000)) / 8 },
		func(b *[]byte, c randfill.Continue) { *b = []byte(str(c)) },
		// Nested objects carry no type meta in protobuf.
		func(tm *metav1.TypeMeta, c randfill.Continue) {},
	)
}

// Compare lists where got (decoded protobuf) differs from want (the JSON):
// a JSON value missing or different, or a value only got has that is not
// a zero value.
func Compare(got, want any, path string) []string {
	switch w := want.(type) {
	case nil:
		if zero(got) {
			return nil
		}
		return []string{fmt.Sprintf("%s: JSON null, protobuf %v", path, got)}
	case map[string]any:
		g, ok := got.(map[string]any)
		if !ok {
			return []string{fmt.Sprintf("%s: JSON object, protobuf %v", path, got)}
		}
		var out []string
		for k, v := range w {
			if gv, ok := g[k]; ok {
				out = append(out, Compare(gv, v, path+"."+k)...)
			} else if !zero(v) {
				out = append(out, path+"."+k+": not in protobuf")
			}
		}
		for k, v := range g {
			if _, ok := w[k]; !ok && !zero(v) {
				out = append(out, fmt.Sprintf("%s.%s: only in protobuf: %v", path, k, v))
			}
		}
		return out
	case []any:
		g, ok := got.([]any)
		if !ok || len(g) != len(w) {
			return []string{fmt.Sprintf("%s: JSON %v, protobuf %v", path, want, got)}
		}
		var out []string
		for i := range w {
			out = append(out, Compare(g[i], w[i], fmt.Sprintf("%s[%d]", path, i))...)
		}
		return out
	case json.Number:
		g, ok := got.(json.Number)
		a, _ := new(big.Float).SetString(string(g))
		b, _ := new(big.Float).SetString(string(w))
		if !ok || a == nil || b == nil || a.Cmp(b) != 0 {
			return []string{fmt.Sprintf("%s: JSON %v, protobuf %v", path, want, got)}
		}
		return nil
	}
	if !reflect.DeepEqual(got, want) {
		return []string{fmt.Sprintf("%s: JSON %v, protobuf %v", path, want, got)}
	}
	return nil
}

func zero(v any) bool {
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
			if !zero(e) {
				return false
			}
		}
		return true
	}
	return false
}
