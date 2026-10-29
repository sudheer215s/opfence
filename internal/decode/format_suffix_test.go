package decode

import (
	"net/url"
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/request"
)

func TestStripFormatSuffix(t *testing.T) {
	cases := map[string]string{
		"/api/v4/projects/1/archive.json":                 "/api/v4/projects/1/archive",
		"/api/v4/projects/1/repository/merged_branches.x": "/api/v4/projects/1/repository/merged_branches",
		"/api/v4/projects/1/archive%2Ejson":               "/api/v4/projects/1/archive",
		"/api/v4/projects/1/archive%2ejson":               "/api/v4/projects/1/archive",
		"/api/v4/projects/1/archive.j-s":                  "/api/v4/projects/1/archive",
		"/api/v4/projects/1/archive.json/":                "/api/v4/projects/1/archive",
		"/api/v4/projects/1/./archive.json":               "/api/v4/projects/1/archive",
		"/api/v4/x/../projects/1/archive.json":            "/api/v4/projects/1/archive",
		"/api/v4/projects/a%2Fb.json":                     "/api/v4/projects/a%2Fb",
		"/api/v4/projects/1/files/a.tar.gz":               "/api/v4/projects/1/files/a.tar",
		"/api/v4/mcp.json":                                "/api/v4/mcp",
		"/api/v4/projects/1/archive":                      "",
		"/api/v4/projects/1/.json":                        "",
		"/api/v4/projects/1/archive.":                     "",
		"/api/v4.1/projects":                              "",
		"/":                                               "",
		"relative.json":                                   "",
		"/../a.json":                                      "",
		"/a/%zz.json":                                     "",
		// What is left would be a dot segment, which resolves elsewhere.
		"/%2E%2E0":    "",
		"/a/..json":   "",
		"/a/...json":  "",
		"/a/%2E.json": "",
	}
	for in, want := range cases {
		if got := StripFormatSuffix(in); got != want {
			t.Errorf("StripFormatSuffix(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestFormatSuffixDecode(t *testing.T) {
	gitlab := Hints{FormatSuffix: true, MCP: true, MCPPaths: []string{"/api/v4/mcp"}, GraphQLPaths: []string{"/api/graphql"}}

	// REST: decoded at the path as sent and without the extension, with
	// every method override at both.
	ops := Decode(fixture(t, "POST /api/v4/projects/1/archive.json HTTP/1.1\nHost: gitlab.com\nX-HTTP-Method-Override: DELETE\n\n"), gitlab)
	var got []string
	for _, o := range ops {
		if o.Protocol != REST {
			t.Fatalf("op = %+v", o)
		}
		got = append(got, o.Method+" "+o.Path)
	}
	want := []string{"POST /api/v4/projects/1/archive.json", "DELETE /api/v4/projects/1/archive.json",
		"POST /api/v4/projects/1/archive", "DELETE /api/v4/projects/1/archive"}
	if len(got) != len(want) {
		t.Fatalf("ops = %q, want %q", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("ops = %q, want %q", got, want)
		}
	}

	// No extension: one reading.
	if ops := Decode(fixture(t, "POST /api/v4/projects/1/archive HTTP/1.1\nHost: gitlab.com\n\n"), gitlab); len(ops) != 1 {
		t.Fatalf("ops = %+v", ops)
	}
	// A provider without the flag reads the path as sent only.
	if ops := Decode(fixture(t, "POST /api/v4/projects/1/archive.json HTTP/1.1\nHost: gitlab.com\n\n"), Hints{}); len(ops) != 1 {
		t.Fatalf("ops = %+v", ops)
	}

	// MCP and GraphQL paths are recognised with an extension, so a tool
	// call cannot reach a REST reading.
	call := `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"start_duo_session","arguments":{"goal":"x"}}}`
	for _, p := range []string{"/api/v4/mcp.json", "/api/v4/mcp%2Ejson", "/api/v4/mcp.anything"} {
		ops := Decode(fixture(t, "POST "+p+" HTTP/1.1\nHost: gitlab.com\nContent-Type: application/json\n\n"+call), gitlab)
		if len(ops) != 1 || ops[0].Protocol != MCP || ops[0].Tool != "start_duo_session" {
			t.Fatalf("%s: ops = %+v", p, ops)
		}
	}
	gql := Decode(fixture(t, "POST /api/graphql.json HTTP/1.1\nHost: gitlab.com\nContent-Type: application/json\n\n"+`{"query":"mutation { projectDelete }"}`), gitlab)
	if len(gql) != 1 || gql[0].Protocol != GraphQL || gql[0].Field != "projectDelete" {
		t.Fatalf("graphql = %+v", gql)
	}
	// Without the flag, /api/v4/mcp.json is not an MCP path.
	noFlag := gitlab
	noFlag.FormatSuffix = false
	if ops := Decode(fixture(t, "POST /api/v4/mcp.json HTTP/1.1\nHost: gitlab.com\nContent-Type: application/json\n\n"+call), noFlag); ops[0].Protocol != REST {
		t.Fatalf("no flag: ops = %+v", ops)
	}
}

// The stripped path keeps every segment but the last, and the last loses
// exactly one extension: nothing else about where the request goes changes.
func FuzzStripFormatSuffix(f *testing.F) {
	for _, s := range []string{"/a/b.json", "/a/b%2Ejson", "/a/../b.c.d", "/.json", "/a/b.", "/a/%zz.x", "/a/b%2Fc.json"} {
		f.Add(s)
	}
	f.Fuzz(func(t *testing.T, p string) {
		got := StripFormatSuffix(p)
		if got == "" {
			return
		}
		in, ok1 := request.NormalizePath(p)
		out, ok2 := request.NormalizePath(got)
		if !ok1 || !ok2 || len(in) != len(out) {
			t.Fatalf("%q -> %q changes the segments", p, got)
		}
		for i := range in[:len(in)-1] {
			if in[i] != out[i] {
				t.Fatalf("%q -> %q changes segment %d", p, got, i)
			}
		}
		a, err1 := url.PathUnescape(in[len(in)-1])
		b, err2 := url.PathUnescape(out[len(out)-1])
		if err1 != nil || err2 != nil || b == "" || !strings.HasPrefix(a, b+".") || strings.Contains(a[len(b)+1:], ".") {
			t.Fatalf("%q -> %q: last segment %q -> %q", p, got, a, b)
		}
	})
}
