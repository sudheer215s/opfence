package setup

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/rakeshnitb23/opfence/internal/jsonedit"
)

const cmdA = "/usr/local/bin/opfence --user-config /home/u/.config/opfence/config.yaml hook "

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

// decode reads a settings file's contents for checks.
func decode(t *testing.T, data []byte) map[string]any {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(data, &m); err != nil {
		t.Fatalf("not JSON: %v\n%s", err, data)
	}
	return m
}

// commands lists the hook commands under the agent's event, in order.
func commands(t *testing.T, a *Agent, data []byte) []string {
	t.Helper()
	m := decode(t, data)
	hooks, _ := m["hooks"].(map[string]any)
	list, _ := hooks[a.event].([]any)
	var out []string
	for _, e := range list {
		eo := e.(map[string]any)
		if a.ID == "cursor" {
			out = append(out, eo["command"].(string))
			continue
		}
		for _, h := range eo["hooks"].([]any) {
			out = append(out, h.(map[string]any)["command"].(string))
		}
	}
	return out
}

func TestInstallNewFile(t *testing.T) {
	for _, id := range []string{"claude-code", "cursor", "gemini"} {
		t.Run(id, func(t *testing.T) {
			a := Agents[id]
			file := filepath.Join(t.TempDir(), "sub", "settings.json")
			c, err := a.Install(file, cmdA+id)
			if err != nil {
				t.Fatal(err)
			}
			if c.Before != nil || !c.Changed() {
				t.Fatalf("change %+v", c)
			}
			if got := commands(t, a, c.After); len(got) != 1 || got[0] != cmdA+id {
				t.Fatalf("commands %q", got)
			}
			m := decode(t, c.After)
			switch id {
			case "cursor":
				if m["version"] != 1.0 {
					t.Fatalf("no version: %s", c.After)
				}
				e := m["hooks"].(map[string]any)["beforeMCPExecution"].([]any)[0].(map[string]any)
				if e["failClosed"] != true {
					t.Fatalf("not fail-closed: %s", c.After)
				}
			case "claude-code":
				e := m["hooks"].(map[string]any)["PreToolUse"].([]any)[0].(map[string]any)
				if e["matcher"] != "^mcp__" || e["hooks"].([]any)[0].(map[string]any)["onFailure"] != "block" {
					t.Fatalf("entry %s", c.After)
				}
			case "gemini":
				e := m["hooks"].(map[string]any)["BeforeTool"].([]any)[0].(map[string]any)
				h := e["hooks"].([]any)[0].(map[string]any)
				if e["matcher"] != "^mcp_" || h["name"] != "opfence" || h["timeout"] != 30000.0 {
					t.Fatalf("entry %s", c.After)
				}
			}
			if err := Apply(c); err != nil {
				t.Fatal(err)
			}
			if !a.Installed(file) {
				t.Fatal("Installed is false after Apply")
			}
			// Installing again changes nothing.
			again, err := a.Install(file, cmdA+id)
			if err != nil || again.Changed() {
				t.Fatalf("second install: %v, changed %v\n%s", err, again.Changed(), again.After)
			}
			// Undo removes the file, which held nothing else.
			r, err := a.Remove(file)
			if err != nil || r.After != nil || !r.Changed() {
				t.Fatalf("remove: %v %+v", err, r)
			}
			if err := Apply(r); err != nil {
				t.Fatal(err)
			}
			if _, err := os.Stat(file); !os.IsNotExist(err) {
				t.Fatalf("file left behind: %v", err)
			}
		})
	}
}

func TestInstallKeepsOtherSettings(t *testing.T) {
	a := Agents["claude-code"]
	file := filepath.Join(t.TempDir(), "settings.json")
	in := `{
  "zeta": 1.50,
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "audit-bash"
          }
        ]
      },
      {
        "matcher": "^mcp__",
        "hooks": [
          {
            "type": "command",
            "command": "'/old path/opfence' hook claude-code"
          },
          {
            "type": "command",
            "command": "log-mcp"
          }
        ]
      },
      {
        "matcher": "^mcp__",
        "hooks": [
          {
            "type": "command",
            "command": "opfence --catalog x hook claude-code"
          }
        ]
      }
    ],
    "Stop": []
  },
  "alpha": "é<>"
}
`
	write(t, file, in)
	c, err := a.Install(file, cmdA+"claude-code")
	if err != nil {
		t.Fatal(err)
	}
	// The new hook takes the first old one's place; the other old one goes;
	// the handler that shared an entry with it stays, with its matcher.
	got := commands(t, a, c.After)
	want := []string{"audit-bash", cmdA + "claude-code", "log-mcp"}
	if strings.Join(got, "|") != strings.Join(want, "|") {
		t.Fatalf("commands %q, want %q", got, want)
	}
	s := string(c.After)
	if !strings.HasPrefix(s, "{\n  \"zeta\": 1.50,\n  \"hooks\"") || !strings.HasSuffix(s, "  \"alpha\": \"é<>\"\n}\n") || !strings.Contains(s, `"Stop": []`) {
		t.Fatalf("other settings moved or changed:\n%s", s)
	}
	r, err := a.Remove(file)
	if err != nil {
		t.Fatal(err)
	}
	got = commands(t, a, r.After)
	if strings.Join(got, "|") != "audit-bash|log-mcp" {
		t.Fatalf("after remove: %q", got)
	}
}

func TestRemoveDropsEmptyContainers(t *testing.T) {
	a := Agents["gemini"]
	file := filepath.Join(t.TempDir(), "settings.json")
	write(t, file, `{"general":{"vimMode":true},"hooks":{"BeforeTool":[{"matcher":"^mcp_","hooks":[{"type":"command","name":"opfence","command":"opfence hook gemini"}]}]}}`)
	r, err := a.Remove(file)
	if err != nil {
		t.Fatal(err)
	}
	if string(r.After) != "{\n  \"general\": {\n    \"vimMode\": true\n  }\n}\n" {
		t.Fatalf("got\n%s", r.After)
	}
	// Nothing to remove: no change.
	write(t, file, `{"hooks":{"BeforeTool":[{"hooks":[{"type":"command","command":"other hook gemini"}]}]}}`)
	if r, err := a.Remove(file); err != nil || r.Changed() {
		t.Fatalf("got %v, changed %v", err, r.Changed())
	}
	if r, err := a.Remove(filepath.Join(t.TempDir(), "missing.json")); err != nil || r.Changed() {
		t.Fatalf("missing file: %v, %+v", err, r)
	}
}

func TestReadErrors(t *testing.T) {
	dir := t.TempDir()
	cases := []struct {
		agent, content, want string
	}{
		{"claude-code", `{"hooks": `, "not valid JSON"},
		{"claude-code", `[]`, "not a JSON object"},
		{"claude-code", `{"hooks": []}`, `"hooks" is not an object`},
		{"cursor", `{"version":1,"hooks":{"beforeMCPExecution":{}}}`, `"hooks.beforeMCPExecution" is not a list`},
		{"claude-code", "{} // c", "not valid JSON"},
	}
	for _, tc := range cases {
		file := filepath.Join(dir, "f.json")
		write(t, file, tc.content)
		_, err := Agents[tc.agent].Install(file, "opfence hook "+tc.agent)
		if err == nil || !strings.Contains(err.Error(), tc.want) {
			t.Errorf("%s %q: got %v, want %q", tc.agent, tc.content, err, tc.want)
		}
	}
	// Gemini allows comments, which a rewrite would lose: refused.
	file := filepath.Join(dir, "g.json")
	write(t, file, "{\n  // mine\n  \"a\": 1\n}\n")
	if _, err := Agents["gemini"].Install(file, "opfence hook gemini"); err != ErrComments {
		t.Fatalf("got %v, want ErrComments", err)
	}
	// A blank file is an empty one.
	write(t, file, "  \n")
	c, err := Agents["gemini"].Install(file, "opfence hook gemini")
	if err != nil || len(commands(t, Agents["gemini"], c.After)) != 1 {
		t.Fatalf("blank file: %v\n%s", err, c.After)
	}
}

func TestCursorAddsVersion(t *testing.T) {
	a := Agents["cursor"]
	file := filepath.Join(t.TempDir(), "hooks.json")
	write(t, file, `{"hooks":{"stop":[{"command":"say done"}]}}`)
	c, err := a.Install(file, "opfence hook cursor")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(string(c.After), "{\n  \"version\": 1,\n  \"hooks\": {\n    \"stop\"") {
		t.Fatalf("got\n%s", c.After)
	}
	// Removing leaves the user's own hook and the version.
	if err := Apply(c); err != nil {
		t.Fatal(err)
	}
	r, err := a.Remove(file)
	if err != nil || r.After == nil || strings.Contains(string(r.After), "beforeMCPExecution") {
		t.Fatalf("got %v\n%s", err, r.After)
	}
}

func TestNotes(t *testing.T) {
	dir := t.TempDir()
	file := filepath.Join(dir, "s.json")
	write(t, file, `{"disableAllHooks": true}`)
	c, _ := Agents["claude-code"].Install(file, "opfence hook claude-code")
	if len(c.Notes) != 1 || !strings.Contains(c.Notes[0], "disableAllHooks") {
		t.Fatalf("notes %q", c.Notes)
	}
	write(t, file, `{"hooksConfig": {"enabled": false, "disabled": ["x", "opfence"]}}`)
	c, _ = Agents["gemini"].Install(file, "opfence hook gemini")
	if len(c.Notes) != 2 {
		t.Fatalf("notes %q", c.Notes)
	}
}

func TestOurs(t *testing.T) {
	for cmd, want := range map[string]bool{
		"opfence hook claude-code":                                         true,
		"/opt/homebrew/bin/opfence hook claude-code":                       true,
		"'/a b/opfence' --user-config '/c d/config.yaml' hook claude-code": true,
		`C:\bin\opfence.exe hook claude-code`:                              true,
		"opfence hook claude-codex":                                        false,
		"opfence hook codex":                                               false,
		"notopfence hook claude-code":                                      false,
		"opfence-wrapper hook claude-code":                                 false,
		"echo opfence; other hook claude-code":                             false,
		"":                                                                 false,
	} {
		if got := ours("claude-code", cmd); got != want {
			t.Errorf("%q: got %v, want %v", cmd, got, want)
		}
	}
}

func TestApplyKeepsModeAndFollowsLinks(t *testing.T) {
	dir := t.TempDir()
	real := filepath.Join(dir, "dotfiles", "settings.json")
	write(t, real, "{}")
	if err := os.Chmod(real, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "settings.json")
	if err := os.Symlink(real, link); err != nil {
		t.Fatal(err)
	}
	c, err := Agents["claude-code"].Install(link, "opfence hook claude-code")
	if err != nil {
		t.Fatal(err)
	}
	if err := Apply(c); err != nil {
		t.Fatal(err)
	}
	if fi, err := os.Lstat(link); err != nil || fi.Mode()&os.ModeSymlink == 0 {
		t.Fatalf("the link was replaced: %v", err)
	}
	st, _ := os.Stat(real)
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", st.Mode())
	}
	data, _ := os.ReadFile(real)
	if !strings.Contains(string(data), "hook claude-code") {
		t.Fatalf("target not written: %s", data)
	}
	if err := Revert(c); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(real); string(data) != "{}" {
		t.Fatalf("revert left %q", data)
	}
	entries, _ := os.ReadDir(filepath.Dir(real))
	if len(entries) != 1 {
		t.Fatalf("temporary files left: %v", entries)
	}
}

func TestInstalledFiles(t *testing.T) {
	dir := t.TempDir()
	user := filepath.Join(dir, "home", ".cursor", "hooks.json")
	write(t, user, `{"version":1,"hooks":{"beforeMCPExecution":[{"command":"/x/opfence hook cursor","failClosed":true}]}}`)
	files := CursorHookFiles("linux", filepath.Join(dir, "home"), filepath.Join(dir, "proj"))
	if files[0] != "/etc/cursor/hooks.json" || files[1] != user {
		t.Fatalf("files %q", files)
	}
	a := Agents["cursor"]
	if !a.Installed(files...) {
		t.Fatal("not found")
	}
	write(t, user, `{"version":1,"hooks":{"beforeMCPExecution":[{"command":"other"}]}}`)
	if a.Installed(files...) {
		t.Fatal("found another hook")
	}
	if CursorHookFiles("darwin", "/h", "/p")[0] != "/Library/Application Support/Cursor/hooks.json" {
		t.Fatal("macOS system file")
	}
}

func TestFile(t *testing.T) {
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	a := Agents["claude-code"]
	if f := a.File("/h", "", env(nil)); f != "/h/.claude/settings.json" {
		t.Fatal(f)
	}
	if f := a.File("/h", "", env(map[string]string{"CLAUDE_CONFIG_DIR": "/c"})); f != "/c/settings.json" {
		t.Fatal(f)
	}
	if f := a.File("/h", "/p", env(nil)); f != "/p/.claude/settings.json" {
		t.Fatal(f)
	}
	if f := Agents["gemini"].File("/h", "", env(map[string]string{"GEMINI_CLI_HOME": "/g"})); f != "/g/.gemini/settings.json" {
		t.Fatal(f)
	}
	if f := Agents["cursor"].File("/h", "", env(map[string]string{"CURSOR_CONFIG_DIR": "/c"})); f != "/h/.cursor/hooks.json" {
		t.Fatal(f)
	}
}

func TestVerify(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("runs the hook with sh")
	}
	dir := t.TempDir()
	cases := []struct {
		agent, script, want string
		fails               bool
	}{
		{"claude-code", `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask"}}`, "ask", false},
		{"cursor", `{"permission":"deny"}`, "deny", false},
		{"gemini", ``, "allow", false},
		{"gemini", `{"decision":"ask"}`, "ask", false},
		{"cursor", `{}`, "", true},
		{"claude-code", `not json`, "", true},
	}
	for _, tc := range cases {
		script := filepath.Join(dir, "hook.sh")
		// The script checks it got the agent's input for the check call.
		body := "#!/bin/sh\nin=$(cat)\ncase \"$in\" in *opfence-setup-check*) ;; *) exit 3;; esac\nprintf '%s' '" + tc.script + "'\n"
		write(t, script, body)
		if err := os.Chmod(script, 0o755); err != nil {
			t.Fatal(err)
		}
		got, err := Agents[tc.agent].Verify(context.Background(), script, dir)
		if (err != nil) != tc.fails || got != tc.want {
			t.Errorf("%s %q: got %q, %v", tc.agent, tc.script, got, err)
		}
	}
	if _, err := Agents["cursor"].Verify(context.Background(), "exit 2", dir); err == nil {
		t.Error("a failing command verified")
	}
}

func TestSample(t *testing.T) {
	for id, a := range Agents {
		var m map[string]any
		if err := json.Unmarshal(a.sample("/tmp"), &m); err != nil || m["hook_event_name"] != a.event {
			t.Errorf("%s: %v %v", id, err, m)
		}
	}
}

func TestDiff(t *testing.T) {
	a := "{\n  \"a\": 1,\n  \"b\": 2,\n  \"c\": 3,\n  \"d\": 4,\n  \"e\": 5\n}\n"
	b := "{\n  \"a\": 1,\n  \"b\": 2,\n  \"c\": 30,\n  \"d\": 4,\n  \"e\": 5\n}\n"
	want := "    \"b\": 2,\n+   \"c\": 30,\n-   \"c\": 3,\n    \"d\": 4,\n"
	if got := Diff([]byte(a), []byte(b)); got != want {
		t.Fatalf("got\n%s", got)
	}
	if got := Diff(nil, []byte("{}\n")); got != "+ {}\n" {
		t.Fatalf("new file: %q", got)
	}
	if got := Diff([]byte("{}\n"), nil); got != "- {}\n" {
		t.Fatalf("removed file: %q", got)
	}
	// Distant changes are separated.
	x := "1\n2\n3\n4\n5\n6\n7\n"
	y := "0\n2\n3\n4\n5\n6\n8\n"
	if got := Diff([]byte(x), []byte(y)); !strings.Contains(got, "  ...\n") {
		t.Fatalf("got\n%s", got)
	}
}

func TestEmptyOf(t *testing.T) {
	v, _ := jsonedit.Parse([]byte(`{"version":1}`))
	if !emptyOf(v.(*jsonedit.Object), Agents["cursor"].fresh()) {
		t.Fatal("version only is empty for Cursor")
	}
	v, _ = jsonedit.Parse([]byte(`{"version":2}`))
	if emptyOf(v.(*jsonedit.Object), Agents["cursor"].fresh()) {
		t.Fatal("another version is not")
	}
}

func TestOffAndInstalledReadComments(t *testing.T) {
	dir := t.TempDir()
	user := filepath.Join(dir, "user.json")
	proj := filepath.Join(dir, "proj.json")
	write(t, user, "{\n  // mine\n  \"hooks\": {\"BeforeTool\": [{\"matcher\": \"^mcp_\", \"hooks\": [{\"type\": \"command\", \"name\": \"opfence\", \"command\": \"opfence hook gemini\"}]}]}\n}\n")
	write(t, proj, `{"hooksConfig": {"enabled": false}}`)
	g := Agents["gemini"]
	if !g.Installed(filepath.Join(dir, "missing.json"), user) {
		t.Fatal("a hook in a file with comments was not found")
	}
	off := g.Off(user, proj, filepath.Join(dir, "missing.json"))
	if len(off) != 1 || !strings.HasPrefix(off[0], proj+": ") {
		t.Fatalf("off %q", off)
	}
}
