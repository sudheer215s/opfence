package hook

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/classes"
	"github.com/rakeshnitb23/opfence/internal/engine"
	"github.com/rakeshnitb23/opfence/internal/policy"
)

// runCursor runs one Cursor hook call and returns what it printed, decoded.
// The hook must always print a JSON object: Cursor runs it with
// failClosed, which blocks on empty output.
func runCursor(t *testing.T, user *policy.File, in string) (map[string]any, error) {
	t.Helper()
	c := embedded(t)
	var out bytes.Buffer
	var gotCwd string
	err := Cursor(strings.NewReader(in), &out, func(cwd string) (*engine.Engine, error) {
		gotCwd = cwd
		return engine.New(c, policy.Resolve(user, nil)), nil
	})
	if err != nil {
		return nil, err
	}
	if gotCwd != "" && gotCwd != "/repo" {
		t.Fatalf("engine built for %q, want the first workspace root", gotCwd)
	}
	var o map[string]any
	if jerr := json.Unmarshal(out.Bytes(), &o); jerr != nil || o == nil {
		t.Fatalf("hook printed %q, want a JSON object: %v", out.String(), jerr)
	}
	return o, nil
}

// cursorEvent writes a beforeMCPExecution input as cursor-agent 2026.10.22
// sends it for a stdio server: tool_input is a JSON string.
func cursorEvent(event, server, tool, args string) string {
	q, _ := json.Marshal(args)
	return `{"conversation_id":"c1","generation_id":"g1","model":"m","hook_event_name":"` + event +
		`","cursor_version":"2026.10.22-27dcf5f","workspace_roots":["/repo"],"user_email":null,"tool_name":"` + tool +
		`","tool_input":` + string(q) + `,"tool_use_id":"u1","mcp_server_name":"` + server + `","command":"npx -y @supabase/mcp-server-supabase"}`
}

func TestCursorDecisions(t *testing.T) {
	deny := &policy.File{Rules: []policy.RuleOverride{{Rule: "supabase-mcp.*", Decision: classes.Deny}}}
	read := `{"project_id":"p1","query":"select 1"}`
	drop := `{"project_id":"p1","query":"drop table users"}`
	cases := []struct {
		name string
		user *policy.File
		args string
		want string
	}{
		{"allowed read", nil, read, "allow"},
		{"confirm asks", nil, drop, "ask"},
		{"deny", deny, read, "deny"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			o, err := runCursor(t, tc.user, cursorEvent("beforeMCPExecution", "supabase", "execute_sql", tc.args))
			if err != nil {
				t.Fatal(err)
			}
			if o["permission"] != tc.want {
				t.Fatalf("got %v, want %s", o, tc.want)
			}
			if tc.want != "allow" && (o["user_message"] == "" || o["agent_message"] != o["user_message"]) {
				t.Fatalf("messages missing: %v", o)
			}
		})
	}
}

func TestCursorIgnores(t *testing.T) {
	drop := `{"project_id":"p1","query":"drop table users"}`
	for _, in := range []string{
		cursorEvent("beforeMCPExecution", "acme-wiki", "search", `{}`),
		cursorEvent("beforeShellExecution", "supabase", "execute_sql", drop),
		`{"hook_event_name":"beforeMCPExecution"}`,
	} {
		o, err := runCursor(t, nil, in)
		if err != nil || len(o) != 0 {
			t.Errorf("%s: got %v, %v; want {}", in, o, err)
		}
	}
}

func TestCursorBadInput(t *testing.T) {
	for _, in := range []string{
		"{",
		cursorEvent("beforeMCPExecution", "supabase", "execute_sql", "{"),
		cursorEvent("beforeMCPExecution", "supabase", "execute_sql", `["drop table users"]`),
	} {
		var out bytes.Buffer
		c := embedded(t)
		err := Cursor(strings.NewReader(in), &out, func(string) (*engine.Engine, error) {
			return engine.New(c, policy.Resolve(nil, nil)), nil
		})
		if err == nil {
			t.Errorf("%s: no error (printed %q)", in, out.String())
		}
	}
	// An empty argument string is no arguments.
	o, err := runCursor(t, nil, cursorEvent("beforeMCPExecution", "supabase", "list_projects", ""))
	if err != nil || o["permission"] == nil {
		t.Fatalf("got %v, %v", o, err)
	}
}
