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

// runGemini runs one Gemini CLI hook call and returns what it printed,
// decoded (nil for no output).
func runGemini(t *testing.T, user *policy.File, in string, proxied bool) (map[string]any, error) {
	t.Helper()
	return runGeminiFlags(t, user, in, GeminiFlags{Proxied: proxied})
}

func runGeminiFlags(t *testing.T, user *policy.File, in string, flags GeminiFlags) (map[string]any, error) {
	t.Helper()
	c := embedded(t)
	var out bytes.Buffer
	err := Gemini(strings.NewReader(in), &out, func(string) (*engine.Engine, error) {
		return engine.New(c, policy.Resolve(user, nil)), nil
	}, flags)
	if err != nil || out.Len() == 0 {
		return nil, err
	}
	var o map[string]any
	if jerr := json.Unmarshal(out.Bytes(), &o); jerr != nil {
		t.Fatalf("hook printed invalid JSON %q: %v", out.String(), jerr)
	}
	return o, nil
}

// geminiEvent writes a BeforeTool input as Gemini CLI 0.66.0 sends it for
// an MCP tool; ctx is the mcp_context object, or "" for none.
func geminiEvent(event, tool, args, ctx string) string {
	s := `{"session_id":"s1","transcript_path":"/t.json","cwd":"/repo","hook_event_name":"` + event +
		`","timestamp":"2026-10-29T00:00:00.000Z","tool_name":"` + tool + `","tool_input":` + args
	if ctx != "" {
		s += `,"mcp_context":` + ctx
	}
	return s + "}"
}

const geminiSupabase = `{"server_name":"supabase","tool_name":"execute_sql","command":"npx","args":["-y","@supabase/mcp-server-supabase"]}`

func TestGeminiDecisions(t *testing.T) {
	deny := &policy.File{Rules: []policy.RuleOverride{{Rule: "supabase-mcp.*", Decision: classes.Deny}}}
	read := `{"project_id":"p1","query":"select 1"}`
	drop := `{"project_id":"p1","query":"drop table users"}`
	cases := []struct {
		name string
		user *policy.File
		args string
		want string
	}{
		{"allowed read leaves Gemini's own approval", nil, read, ""},
		{"confirm asks", nil, drop, "ask"},
		{"deny", deny, read, "deny"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			o, err := runGemini(t, tc.user, geminiEvent("BeforeTool", "mcp_supabase_execute_sql", tc.args, geminiSupabase), false)
			if err != nil {
				t.Fatal(err)
			}
			got := ""
			if o != nil {
				got, _ = o["decision"].(string)
			}
			if got != tc.want {
				t.Fatalf("got %q, want %q (%v)", got, tc.want, o)
			}
			switch got {
			case "deny":
				if r, _ := o["reason"].(string); !strings.Contains(r, "Opfence denies") {
					t.Fatalf("deny reason %q", r)
				}
			case "ask":
				if m, _ := o["systemMessage"].(string); !strings.Contains(m, "Opfence needs confirmation") {
					t.Fatalf("ask message %q", m)
				}
			}
		})
	}
}

func TestGeminiServerFromContext(t *testing.T) {
	// The function name is ambiguous (a server "my_db" and tool "x_y"), so
	// the server comes from mcp_context, and an alias maps it.
	user := &policy.File{Servers: map[string]string{"my_db": "supabase-mcp"}}
	ctx := `{"server_name":"my_db","tool_name":"execute_sql","command":"npx"}`
	o, err := runGemini(t, user, geminiEvent("BeforeTool", "mcp_my_db_execute_sql", `{"project_id":"p1","query":"drop table users"}`, ctx), false)
	if err != nil || o == nil || o["decision"] != "ask" {
		t.Fatalf("got %v, %v; want ask", o, err)
	}
	bad := &policy.File{Servers: map[string]string{"my_db": "nope"}}
	if _, err := runGemini(t, bad, geminiEvent("BeforeTool", "mcp_my_db_execute_sql", `{}`, ctx), false); err == nil {
		t.Fatal("a servers: entry naming no provider did not fail")
	}
}

func TestGeminiNameWithoutContext(t *testing.T) {
	drop := `{"project_id":"p1","query":"drop table users"}`
	o, err := runGemini(t, nil, geminiEvent("BeforeTool", "mcp_supabase_execute_sql", drop, ""), false)
	if err != nil || o == nil || o["decision"] != "ask" {
		t.Fatalf("got %v, %v; want ask from the function name", o, err)
	}
	// An alias with an underscore is tried before a shorter name.
	user := &policy.File{Servers: map[string]string{"supabase_prod": "supabase-mcp"}}
	o, err = runGemini(t, user, geminiEvent("BeforeTool", "mcp_supabase_prod_execute_sql", drop, ""), false)
	if err != nil || o == nil || o["decision"] != "ask" {
		t.Fatalf("got %v, %v; want ask through the alias", o, err)
	}
	// A shortened name cannot be split.
	if o, err := runGemini(t, nil, geminiEvent("BeforeTool", "mcp_supabase_exec...sql", drop, ""), false); err != nil || o != nil {
		t.Fatalf("got %v, %v; want no output", o, err)
	}
}

func TestGeminiIgnores(t *testing.T) {
	drop := `{"project_id":"p1","query":"drop table users"}`
	for _, tc := range []struct {
		name, in string
		proxied  bool
	}{
		{"built-in tool", geminiEvent("BeforeTool", "run_shell_command", `{"command":"ls"}`, ""), false},
		{"unknown server", geminiEvent("BeforeTool", "mcp_acme-wiki_search", `{}`, `{"server_name":"acme-wiki","tool_name":"search","command":"wiki"}`), false},
		{"other event", geminiEvent("AfterTool", "mcp_supabase_execute_sql", drop, geminiSupabase), false},
		{"remote server under the proxy", geminiEvent("BeforeTool", "mcp_supabase_execute_sql", drop, `{"server_name":"supabase","tool_name":"execute_sql","url":"https://mcp.supabase.com/mcp"}`), true},
	} {
		o, err := runGemini(t, nil, tc.in, tc.proxied)
		if err != nil || o != nil {
			t.Errorf("%s: got %v, %v; want no output", tc.name, o, err)
		}
	}
	// Without the proxy, a remote server is decided by the hook.
	in := geminiEvent("BeforeTool", "mcp_supabase_execute_sql", drop, `{"server_name":"supabase","tool_name":"execute_sql","url":"https://mcp.supabase.com/mcp"}`)
	if o, err := runGemini(t, nil, in, false); err != nil || o == nil || o["decision"] != "ask" {
		t.Fatalf("remote server outside opfence run: got %v, %v; want ask", o, err)
	}
	// Under the proxy, a local server is still decided by the hook.
	in = geminiEvent("BeforeTool", "mcp_supabase_execute_sql", drop, geminiSupabase)
	if o, err := runGemini(t, nil, in, true); err != nil || o == nil || o["decision"] != "ask" {
		t.Fatalf("stdio server under the proxy: got %v, %v; want ask", o, err)
	}
}

func TestGeminiBadInput(t *testing.T) {
	var out bytes.Buffer
	if err := Gemini(strings.NewReader("{"), &out, nil, GeminiFlags{}); err == nil {
		t.Fatal("invalid JSON did not fail")
	}
	big := strings.NewReader(`{"x":"` + strings.Repeat("a", MaxInput) + `"}`)
	if err := Gemini(big, &out, nil, GeminiFlags{}); err == nil {
		t.Fatal("oversized input did not fail")
	}
}

func TestGeminiHeadless(t *testing.T) {
	drop := geminiEvent("BeforeTool", "mcp_supabase_execute_sql", `{"project_id":"p1","query":"drop table users"}`, geminiSupabase)
	read := geminiEvent("BeforeTool", "mcp_supabase_execute_sql", `{"project_id":"p1","query":"select 1"}`, geminiSupabase)
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	for _, tc := range []struct {
		name  string
		flags GeminiFlags
		in    string
		want  string
	}{
		{"headless confirm is denied", GeminiFlags{Headless: true}, drop, "deny"},
		{"headless read is left alone", GeminiFlags{Headless: true}, read, ""},
		{"CI is headless", GeminiFlags{Getenv: env(map[string]string{"CI": "true"})}, drop, "deny"},
		{"GitHub Actions is headless", GeminiFlags{Getenv: env(map[string]string{"GITHUB_ACTIONS": "true"})}, drop, "deny"},
		{"Gemini's own tests are not", GeminiFlags{Getenv: env(map[string]string{"CI": "true", "GEMINI_CLI_INTEGRATION_TEST": "true"})}, drop, "ask"},
		{"a terminal asks", GeminiFlags{Getenv: env(nil)}, drop, "ask"},
		{"opfence run says headless", GeminiFlags{Getenv: env(map[string]string{EnvGeminiHeadless: "1"})}, drop, "deny"},
	} {
		o, err := runGeminiFlags(t, nil, tc.in, tc.flags)
		if err != nil {
			t.Fatal(err)
		}
		got := ""
		if o != nil {
			got = o["decision"].(string)
		}
		if got != tc.want {
			t.Errorf("%s: got %q, want %q", tc.name, got, tc.want)
		}
		if got == "deny" && tc.flags.headless() && !strings.HasPrefix(o["reason"].(string), "Gemini CLI is running with nobody to ask") {
			t.Errorf("%s: reason %q", tc.name, o["reason"])
		}
	}
}
