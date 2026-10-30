package decode

import (
	"bytes"
	"compress/gzip"
	_ "embed"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

// KubeProtobuf is the media type of Kubernetes' protobuf encoding, which
// kubectl and other Go clients send built-in objects in.
const KubeProtobuf = "application/vnd.kubernetes.protobuf"

// kubeProtoMagic starts every protobuf-encoded object, before the
// runtime.Unknown envelope that names its kind.
var kubeProtoMagic = []byte("k8s\x00")

// kubeProtoData describes the messages of Kubernetes' built-in kinds,
// written by tools/kubeprotogen from Kubernetes' .proto files and OpenAPI
// description.
//
//go:embed kubeproto.json.gz
var kubeProtoData []byte

type kpType struct {
	scalar string // string, bool, int32, int64, double or bytes
	msg    *kpMsg
}

type kpField struct {
	name     string
	typ      kpType
	mapKey   string // set for a map field: the key's scalar type
	repeated bool
	inline   bool
}

type kpMsg struct {
	name   string
	fields map[uint64]*kpField
	list   bool // stands for a JSON array of its items
}

type kpSchema struct {
	kubernetes string
	kinds      map[string]*kpMsg // "apiVersion Kind"
}

var kubeProto = sync.OnceValues(func() (*kpSchema, error) {
	zr, err := gzip.NewReader(bytes.NewReader(kubeProtoData))
	if err != nil {
		return nil, err
	}
	var raw struct {
		Kubernetes string                         `json:"kubernetes"`
		Kinds      map[string]string              `json:"kinds"`
		Lists      []string                       `json:"lists"`
		Messages   map[string][][]json.RawMessage `json:"messages"`
	}
	if err := json.NewDecoder(zr).Decode(&raw); err != nil {
		return nil, err
	}
	msgs := make(map[string]*kpMsg, len(raw.Messages))
	for name := range raw.Messages {
		msgs[name] = &kpMsg{name: name, fields: map[uint64]*kpField{}}
	}
	typ := func(t string) (kpType, error) {
		switch t {
		case "string", "bool", "int32", "int64", "double", "bytes":
			return kpType{scalar: t}, nil
		}
		if m := msgs[t]; m != nil {
			return kpType{msg: m}, nil
		}
		return kpType{}, fmt.Errorf("no message %s", t)
	}
	for name, rows := range raw.Messages {
		m := msgs[name]
		for _, row := range rows {
			var num uint64
			var fname, t, flags string
			if len(row) < 3 {
				return nil, fmt.Errorf("%s: short field", name)
			}
			if err := errors.Join(json.Unmarshal(row[0], &num), json.Unmarshal(row[1], &fname), json.Unmarshal(row[2], &t)); err != nil {
				return nil, err
			}
			if len(row) > 3 {
				if err := json.Unmarshal(row[3], &flags); err != nil {
					return nil, err
				}
			}
			f := &kpField{name: fname, repeated: strings.Contains(flags, "r"), inline: strings.Contains(flags, "i")}
			if rest, ok := strings.CutPrefix(t, "map:"); ok {
				k, v, _ := strings.Cut(rest, ":")
				f.mapKey, t = k, v
			}
			if f.typ, err = typ(t); err != nil {
				return nil, fmt.Errorf("%s.%s: %w", name, fname, err)
			}
			m.fields[num] = f
		}
	}
	for _, name := range raw.Lists {
		if m := msgs[name]; m != nil {
			m.list = true
		}
	}
	s := &kpSchema{kubernetes: raw.Kubernetes, kinds: make(map[string]*kpMsg, len(raw.Kinds))}
	for k, name := range raw.Kinds {
		if s.kinds[k] = msgs[name]; s.kinds[k] == nil {
			return nil, fmt.Errorf("kind %s: no message %s", k, name)
		}
	}
	return s, nil
})

// KubeProtoVersion is the Kubernetes release the protobuf schema was
// generated from.
func KubeProtoVersion() string {
	s, err := kubeProto()
	if err != nil {
		return ""
	}
	return s.kubernetes
}

// ParseKubeProtobuf reads a Kubernetes protobuf body as the JSON object it
// stands for: the runtime.Unknown envelope names the object's apiVersion
// and kind, and the schema of that kind gives its fields' JSON names. Field
// numbers the schema does not know are skipped, as the API server skips
// them. A field set twice is an error, as a repeated JSON key is: the
// server would merge the two.
func ParseKubeProtobuf(body []byte) (any, error) {
	rest, ok := bytes.CutPrefix(body, kubeProtoMagic)
	if !ok {
		return nil, errors.New("protobuf body without Kubernetes' prefix")
	}
	s, err := kubeProto()
	if err != nil {
		return nil, fmt.Errorf("protobuf schema: %w", err)
	}
	var apiVersion, kind, encoding, ctype string
	var raw []byte
	var seen [5]bool
	err = protoFields(rest, func(num uint64, wire int, v uint64, b []byte) error {
		if num >= 1 && num <= 4 {
			if seen[num] {
				return fmt.Errorf("protobuf envelope field %d set twice", num)
			}
			seen[num] = true
			if wire != 2 {
				return fmt.Errorf("protobuf envelope field %d has wire type %d", num, wire)
			}
		}
		switch num {
		case 1:
			var tm [3]bool
			return protoFields(b, func(n uint64, w int, _ uint64, s []byte) error {
				if n != 1 && n != 2 {
					return nil
				}
				if w != 2 || tm[n] {
					return errors.New("protobuf envelope: bad type meta")
				}
				tm[n] = true
				if n == 1 {
					apiVersion = string(s)
				} else {
					kind = string(s)
				}
				return nil
			})
		case 2:
			raw = b
		case 3:
			encoding = string(b)
		case 4:
			ctype = string(b)
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if encoding != "" || ctype != "" {
		return nil, fmt.Errorf("protobuf envelope with content encoding %q and type %q", encoding, ctype)
	}
	m := s.kinds[apiVersion+" "+kind]
	if m == nil {
		return nil, fmt.Errorf("no protobuf schema for %s %s", apiVersion, kind)
	}
	obj := map[string]any{}
	if err := decodeKPInto(obj, raw, m, 0); err != nil {
		return nil, err
	}
	for k, v := range map[string]string{"apiVersion": apiVersion, "kind": kind} {
		if _, dup := obj[k]; dup {
			return nil, fmt.Errorf("protobuf object sets %s", k)
		}
		obj[k] = v
	}
	return obj, nil
}

// decodeKP reads one message as its JSON value.
func decodeKP(b []byte, m *kpMsg, depth int) (any, error) {
	if depth > maxJSONDepth {
		return nil, fmt.Errorf("protobuf nested deeper than %d levels", maxJSONDepth)
	}
	if v, ok, err := decodeKPSpecial(b, m, depth); ok || err != nil {
		return v, err
	}
	if m.list {
		var items []any
		err := protoFields(b, func(num uint64, wire int, v uint64, s []byte) error {
			f := m.fields[num]
			if f == nil {
				return nil
			}
			vals, err := kpValues(f, wire, v, s, depth)
			items = append(items, vals...)
			return err
		})
		if items == nil {
			items = []any{}
		}
		return items, err
	}
	obj := map[string]any{}
	err := decodeKPInto(obj, b, m, depth)
	return obj, err
}

// decodeKPInto reads a message's fields into obj, inline ones included.
func decodeKPInto(obj map[string]any, b []byte, m *kpMsg, depth int) error {
	if depth > maxJSONDepth {
		return fmt.Errorf("protobuf nested deeper than %d levels", maxJSONDepth)
	}
	set := map[uint64]bool{}
	return protoFields(b, func(num uint64, wire int, v uint64, s []byte) error {
		f := m.fields[num]
		if f == nil {
			return nil // unknown to this schema; the server skips it too
		}
		if !f.repeated && f.mapKey == "" {
			if set[num] {
				return fmt.Errorf("protobuf field %s.%s set twice", m.name, f.name)
			}
			set[num] = true
		}
		if f.inline {
			if wire != 2 || f.typ.msg == nil {
				return fmt.Errorf("protobuf field %s.%s: wire type %d", m.name, f.name, wire)
			}
			return decodeKPInto(obj, s, f.typ.msg, depth+1)
		}
		if f.mapKey != "" {
			return kpMapEntry(obj, f, wire, s, depth)
		}
		vals, err := kpValues(f, wire, v, s, depth)
		if err != nil {
			return err
		}
		if f.repeated {
			list, _ := obj[f.name].([]any)
			if _, dup := obj[f.name]; dup && list == nil {
				return fmt.Errorf("protobuf field %s.%s set twice", m.name, f.name)
			}
			obj[f.name] = append(list, vals...)
			return nil
		}
		if _, dup := obj[f.name]; dup {
			return fmt.Errorf("protobuf field %s.%s set twice", m.name, f.name)
		}
		obj[f.name] = vals[0]
		return nil
	})
}

// kpMapEntry reads one entry of a map field (key 1, value 2).
func kpMapEntry(obj map[string]any, f *kpField, wire int, b []byte, depth int) error {
	if wire != 2 {
		return fmt.Errorf("protobuf map %s: wire type %d", f.name, wire)
	}
	var key string
	var val any
	var haveKey, haveVal bool
	err := protoFields(b, func(num uint64, w int, v uint64, s []byte) error {
		switch num {
		case 1:
			if w != 2 || haveKey {
				return fmt.Errorf("protobuf map %s: bad key", f.name)
			}
			if !utf8.Valid(s) {
				return fmt.Errorf("protobuf map %s: key is not UTF-8", f.name)
			}
			key, haveKey = string(s), true
		case 2:
			if haveVal {
				return fmt.Errorf("protobuf map %s: value set twice", f.name)
			}
			vals, err := kpValues(&kpField{name: f.name, typ: f.typ}, w, v, s, depth)
			if err != nil {
				return err
			}
			val, haveVal = vals[0], true
		}
		return nil
	})
	if err != nil {
		return err
	}
	if !haveVal {
		val = kpZero(f.typ)
	}
	m, _ := obj[f.name].(map[string]any)
	if m == nil {
		if _, dup := obj[f.name]; dup {
			return fmt.Errorf("protobuf field %s set twice", f.name)
		}
		m = map[string]any{}
		obj[f.name] = m
	}
	if _, dup := m[key]; dup {
		return fmt.Errorf("protobuf map %s: key %q set twice", f.name, key)
	}
	m[key] = val
	return nil
}

// kpZero is a map value the entry leaves out: its type's zero value.
func kpZero(t kpType) any {
	switch t.scalar {
	case "string", "bytes":
		return ""
	case "bool":
		return false
	case "int32", "int64", "double":
		return json.Number("0")
	}
	return map[string]any{}
}

// kpValues reads one field occurrence: one value, or several for a packed
// repeated scalar.
func kpValues(f *kpField, wire int, v uint64, b []byte, depth int) ([]any, error) {
	bad := func() ([]any, error) {
		return nil, fmt.Errorf("protobuf field %s: wire type %d for %s", f.name, wire, kpTypeName(f.typ))
	}
	if f.typ.msg != nil {
		if wire != 2 {
			return bad()
		}
		x, err := decodeKP(b, f.typ.msg, depth+1)
		return []any{x}, err
	}
	switch f.typ.scalar {
	case "string":
		if wire != 2 {
			return bad()
		}
		if !utf8.Valid(b) {
			return nil, fmt.Errorf("protobuf field %s: string is not UTF-8", f.name)
		}
		return []any{string(b)}, nil
	case "bytes":
		if wire != 2 {
			return bad()
		}
		return []any{base64.StdEncoding.EncodeToString(b)}, nil
	case "bool", "int32", "int64":
		switch wire {
		case 0:
			return []any{kpVarint(f.typ.scalar, v)}, nil
		case 2:
			if !f.repeated {
				return bad()
			}
			var out []any
			for len(b) > 0 {
				x, n := binary.Uvarint(b)
				if n <= 0 {
					return nil, fmt.Errorf("protobuf field %s: bad packed varint", f.name)
				}
				out = append(out, kpVarint(f.typ.scalar, x))
				b = b[n:]
			}
			return out, nil
		}
		return bad()
	case "double":
		var out []any
		switch wire {
		case 1:
			x, err := kpDouble(v)
			return []any{x}, err
		case 2:
			if !f.repeated || len(b)%8 != 0 {
				return bad()
			}
			for ; len(b) > 0; b = b[8:] {
				x, err := kpDouble(binary.LittleEndian.Uint64(b))
				if err != nil {
					return nil, err
				}
				out = append(out, x)
			}
			return out, nil
		}
		return bad()
	}
	return bad()
}

func kpTypeName(t kpType) string {
	if t.msg != nil {
		return t.msg.name
	}
	return t.scalar
}

func kpVarint(scalar string, v uint64) any {
	switch scalar {
	case "bool":
		return v != 0
	case "int32":
		return json.Number(strconv.FormatInt(int64(int32(v)), 10))
	}
	return json.Number(strconv.FormatInt(int64(v), 10))
}

func kpDouble(bits uint64) (any, error) {
	f := math.Float64frombits(bits)
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return nil, errors.New("protobuf double is not a number")
	}
	return json.Number(strconv.FormatFloat(f, 'g', -1, 64)), nil
}

// decodeKPSpecial reads the messages whose JSON form is not an object of
// their fields, as the API's own JSON encoding writes them.
func decodeKPSpecial(b []byte, m *kpMsg, depth int) (any, bool, error) {
	name := m.name[strings.LastIndexByte(m.name, '.')+1:]
	pkg := m.name[:max(strings.LastIndexByte(m.name, '.'), 0)]
	switch {
	case m.name == "apimachinery.pkg.api.resource.Quantity":
		s, _, err := kpScalars(b, m)
		return s["string"], true, err
	case m.name == "apimachinery.pkg.util.intstr.IntOrString":
		s, n, err := kpScalars(b, m)
		if err != nil {
			return nil, true, err
		}
		if n["type"] == 1 {
			return s["strVal"], true, nil
		}
		return json.Number(strconv.FormatInt(int64(int32(n["intVal"])), 10)), true, nil
	case m.name == "apimachinery.pkg.apis.meta.v1.Time" || m.name == "apimachinery.pkg.apis.meta.v1.MicroTime":
		_, n, err := kpScalars(b, m)
		if err != nil {
			return nil, true, err
		}
		if n["seconds"] == 0 && n["nanos"] == 0 {
			return nil, true, nil
		}
		t := time.Unix(int64(n["seconds"]), int64(int32(n["nanos"]))).UTC()
		if name == "MicroTime" {
			return t.Format("2006-01-02T15:04:05.000000Z07:00"), true, nil
		}
		return t.Format(time.RFC3339), true, nil
	case m.name == "apimachinery.pkg.apis.meta.v1.Duration":
		_, n, err := kpScalars(b, m)
		return time.Duration(int64(n["duration"])).String(), true, err
	case m.name == "apimachinery.pkg.runtime.RawExtension" || m.name == "apimachinery.pkg.apis.meta.v1.FieldsV1" ||
		strings.HasPrefix(pkg, "apiextensions_apiserver.") && name == "JSON":
		var raw []byte
		var have bool
		err := protoFields(b, func(num uint64, wire int, _ uint64, s []byte) error {
			if num != 1 {
				return nil
			}
			if wire != 2 || have {
				return fmt.Errorf("protobuf %s: bad raw field", m.name)
			}
			raw, have = s, true
			return nil
		})
		if err != nil || len(raw) == 0 {
			return nil, true, err
		}
		if bytes.HasPrefix(raw, kubeProtoMagic) {
			v, err := ParseKubeProtobuf(raw)
			return v, true, err
		}
		v, err := parseJSON(raw)
		return v, true, err
	case strings.HasPrefix(pkg, "apiextensions_apiserver.") && strings.HasPrefix(name, "JSONSchemaPropsOr"):
		// The schema when it is set, else the other form: a bool, a list
		// of schemas or a list of strings.
		obj := map[string]any{}
		if err := decodeKPInto(obj, b, m, depth); err != nil {
			return nil, true, err
		}
		if s, ok := obj["schema"]; ok {
			return s, true, nil
		}
		for _, k := range []string{"allows", "jSONSchemas", "property"} {
			if v, ok := obj[k]; ok {
				return v, true, nil
			}
		}
		if name == "JSONSchemaPropsOrBool" {
			return false, true, nil
		}
		return []any{}, true, nil
	}
	return nil, false, nil
}

// kpScalars reads a special message's string and varint fields by name.
func kpScalars(b []byte, m *kpMsg) (map[string]any, map[string]uint64, error) {
	s, n := map[string]any{}, map[string]uint64{}
	set := map[uint64]bool{}
	err := protoFields(b, func(num uint64, wire int, v uint64, x []byte) error {
		f := m.fields[num]
		if f == nil {
			return nil
		}
		if set[num] {
			return fmt.Errorf("protobuf %s: field %s set twice", m.name, f.name)
		}
		set[num] = true
		switch {
		case f.typ.scalar == "string" && wire == 2:
			if !utf8.Valid(x) {
				return fmt.Errorf("protobuf %s: string is not UTF-8", m.name)
			}
			s[f.name] = string(x)
		case (f.typ.scalar == "int32" || f.typ.scalar == "int64") && wire == 0:
			n[f.name] = v
		default:
			return fmt.Errorf("protobuf %s: field %s has wire type %d", m.name, f.name, wire)
		}
		return nil
	})
	return s, n, err
}

// protoFields calls fn for each field of a protobuf message: its number,
// wire type, and value (a varint or fixed one in v, a length-delimited one
// in b). Groups and fields numbered 0 are errors.
func protoFields(b []byte, fn func(num uint64, wire int, v uint64, b []byte) error) error {
	for len(b) > 0 {
		key, n := binary.Uvarint(b)
		if n <= 0 {
			return errors.New("protobuf: bad field key")
		}
		b = b[n:]
		num, wire := key>>3, int(key&7)
		if num == 0 || num > math.MaxInt32 {
			return fmt.Errorf("protobuf: field number %d", num)
		}
		var v uint64
		var s []byte
		switch wire {
		case 0:
			v, n = binary.Uvarint(b)
			if n <= 0 {
				return errors.New("protobuf: bad varint")
			}
			b = b[n:]
		case 1:
			if len(b) < 8 {
				return errors.New("protobuf: short fixed64")
			}
			v, b = binary.LittleEndian.Uint64(b), b[8:]
		case 2:
			l, n := binary.Uvarint(b)
			if n <= 0 || l > uint64(len(b)-n) {
				return errors.New("protobuf: bad length")
			}
			s, b = b[n:n+int(l)], b[n+int(l):]
		case 5:
			if len(b) < 4 {
				return errors.New("protobuf: short fixed32")
			}
			v, b = uint64(binary.LittleEndian.Uint32(b)), b[4:]
		default:
			return fmt.Errorf("protobuf: wire type %d", wire)
		}
		if err := fn(num, wire, v, s); err != nil {
			return err
		}
	}
	return nil
}
