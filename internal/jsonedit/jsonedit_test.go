package jsonedit

import (
	"encoding/json"
	"reflect"
	"testing"
)

func TestRoundTripKeepsOrder(t *testing.T) {
	in := `{
  "z": 1,
  "a": {
    "y": [1.50, 1e3, -0, "x"],
    "b": {},
    "c": []
  },
  "dup": 1,
  "s": "<a href=\"x\">é\u0001</a>",
  "dup": 2,
  "t": true,
  "n": null
}
`
	v, err := Parse([]byte(in))
	if err != nil {
		t.Fatal(err)
	}
	out, err := Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	want := `{
  "z": 1,
  "a": {
    "y": [
      1.50,
      1e3,
      -0,
      "x"
    ],
    "b": {},
    "c": []
  },
  "dup": 1,
  "s": "<a href=\"x\">é\u0001</a>",
  "dup": 2,
  "t": true,
  "n": null
}
`
	if string(out) != want {
		t.Fatalf("got\n%s\nwant\n%s", out, want)
	}
	o := v.(*Object)
	if d, _ := o.Get("dup"); d != json.Number("2") {
		t.Fatalf("Get returned %v, want the last occurrence", d)
	}
	o.Set("dup", json.Number("3"))
	o.Set("new", "v")
	o.Delete("z")
	if o.Members[0].Key != "a" || o.Members[1].Value != json.Number("1") || o.Members[3].Value != json.Number("3") || o.Members[len(o.Members)-1].Key != "new" {
		t.Fatalf("Set and Delete: %+v", o.Members)
	}
}

func TestParseErrors(t *testing.T) {
	for _, in := range []string{"", "{", `{"a":1}{}`, `{"a":1,}`, `[1 2]`, `{1:2}`, `// c` + "\n{}", "nul"} {
		if _, err := Parse([]byte(in)); err == nil {
			t.Errorf("%q parsed", in)
		}
	}
	for _, in := range []string{"{}", "[]", `"s"`, "1", " true ", "null"} {
		if _, err := Parse([]byte(in)); err != nil {
			t.Errorf("%q: %v", in, err)
		}
	}
}

func TestStripComments(t *testing.T) {
	cases := []struct {
		in, want string
		found    bool
	}{
		{`{"a": "x // y"}`, `{"a": "x // y"}`, false},
		{`{"a": "q\"//"} // c`, `{"a": "q\"//"}     `, true},
		{"{\n// line\n\"a\": 1 /* b\nc */}", "{\n       \n\"a\": 1     \n    }", true},
		{`{"a": "/* not */"}`, `{"a": "/* not */"}`, false},
		{`{} /* open`, `{}        `, true},
		{`{"a":"\\"}//x`, `{"a":"\\"}   `, true},
	}
	for _, tc := range cases {
		got, found := StripComments([]byte(tc.in))
		if string(got) != tc.want || found != tc.found {
			t.Errorf("%q: got %q %v, want %q %v", tc.in, got, found, tc.want, tc.found)
		}
	}
}

func FuzzRoundTrip(f *testing.F) {
	for _, s := range []string{`{"a":[1,{"b":null}],"a":"x"}`, `[]`, `"\u2028"`, `{"k":1.0e-5}`} {
		f.Add([]byte(s))
	}
	f.Fuzz(func(t *testing.T, data []byte) {
		v, err := Parse(data)
		if err != nil {
			return
		}
		out, err := Marshal(v)
		if err != nil {
			t.Fatalf("Marshal: %v", err)
		}
		if !json.Valid(out) {
			t.Fatalf("invalid JSON written: %q", out)
		}
		v2, err := Parse(out)
		if err != nil {
			t.Fatalf("reparse: %v", err)
		}
		if !reflect.DeepEqual(v, v2) {
			t.Fatalf("round trip changed the value: %q -> %q", data, out)
		}
		// Stripping comments from comment-free JSON changes nothing.
		if s, found := StripComments(out); found || string(s) != string(out) {
			t.Fatalf("StripComments changed %q", out)
		}
	})
}
