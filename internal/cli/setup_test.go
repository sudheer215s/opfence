package cli

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// fakeHook writes a script named opfence that answers the setup check as
// the agent's hook would, or fails, and returns the command running it.
func fakeHook(t *testing.T, dir, agent, output string, fail bool) string {
	t.Helper()
	script := filepath.Join(dir, "opfence")
	body := "#!/bin/sh\ncat >/dev/null\nprintf '%s' '" + output + "'\n"
	if fail {
		body = "#!/bin/sh\necho 'catalog broken' >&2\nexit 2\n"
	}
	if err := os.WriteFile(script, []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	return script + " hook " + agent
}

func TestSetupCommand(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the check runs the hook with sh")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	file := filepath.Join(home, ".claude", "settings.json")
	if err := os.MkdirAll(filepath.Dir(file), 0o755); err != nil {
		t.Fatal(err)
	}
	orig := "{\n  \"model\": \"opus\"\n}\n"
	if err := os.WriteFile(file, []byte(orig), 0o600); err != nil {
		t.Fatal(err)
	}
	good := fakeHook(t, t.TempDir(), "claude-code", `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"ask"}}`, false)

	code, out, errb := run(t, "setup", "claude-code", "--hook-command", good, "--dry-run")
	if code != exitOK || !strings.Contains(out, "Would change "+file) || !strings.Contains(out, "+ ") {
		t.Fatalf("dry run: %d %q %q", code, out, errb)
	}
	if data, _ := os.ReadFile(file); string(data) != orig {
		t.Fatal("dry run wrote the file")
	}

	code, out, errb = run(t, "setup", "claude-code", "--hook-command", good)
	if code != exitOK || !strings.Contains(out, "Added a PreToolUse hook") || !strings.Contains(out, "Checked: the hook decides a DROP TABLE through Supabase's execute_sql: ask.") {
		t.Fatalf("setup: %d %q %q", code, out, errb)
	}
	data, _ := os.ReadFile(file)
	if !strings.Contains(string(data), `"model": "opus"`) || !strings.Contains(string(data), good) {
		t.Fatalf("file:\n%s", data)
	}

	code, out, _ = run(t, "setup", "claude-code", "--hook-command", good)
	if code != exitOK || !strings.Contains(out, "already has Opfence's hook") {
		t.Fatalf("second setup: %d %q", code, out)
	}

	code, out, _ = run(t, "setup", "claude-code", "--undo")
	if code != exitOK || !strings.Contains(out, "Removed Opfence's hook") {
		t.Fatalf("undo: %d %q", code, out)
	}
	if data, _ := os.ReadFile(file); string(data) != orig {
		t.Fatalf("undo left:\n%s", data)
	}
	code, out, _ = run(t, "setup", "claude-code", "--undo")
	if code != exitOK || !strings.Contains(out, "has no Opfence hook") {
		t.Fatalf("second undo: %d %q", code, out)
	}
}

func TestSetupFailedCheckRestores(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the check runs the hook with sh")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	bad := fakeHook(t, t.TempDir(), "cursor", "", true)
	code, _, errb := run(t, "setup", "cursor", "--hook-command", bad)
	if code == exitOK || !strings.Contains(errb, "catalog broken") || !strings.Contains(errb, "is back as it was") {
		t.Fatalf("got %d %q", code, errb)
	}
	if _, err := os.Stat(filepath.Join(home, ".cursor", "hooks.json")); !os.IsNotExist(err) {
		t.Fatalf("the file was left behind: %v", err)
	}
	// A hook that prints nothing the agent can read fails the check too.
	quiet := fakeHook(t, t.TempDir(), "cursor", "{}", false)
	if code, _, errb := run(t, "setup", "cursor", "--hook-command", quiet); code == exitOK || !strings.Contains(errb, "did not decide") {
		t.Fatalf("got %d %q", code, errb)
	}
}

func TestSetupProjectAndErrors(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the check runs the hook with sh")
	}
	t.Setenv("HOME", t.TempDir())
	t.Setenv("GEMINI_CLI_HOME", "")
	proj := t.TempDir()
	wd, _ := os.Getwd()
	if err := os.Chdir(proj); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(wd)
	good := fakeHook(t, t.TempDir(), "gemini", "", false) // Gemini's hook prints nothing for an allowed call
	code, out, errb := run(t, "setup", "gemini", "--project", "--hook-command", good)
	if code != exitOK || !strings.Contains(out, "decides a DROP TABLE through Supabase's execute_sql: allow") || !strings.Contains(out, "Everyone who opens this project needs opfence") {
		t.Fatalf("project setup: %d %q %q", code, out, errb)
	}
	if _, err := os.Stat(filepath.Join(proj, ".gemini", "settings.json")); err != nil {
		t.Fatal(err)
	}
	// A Gemini settings file with comments is left alone, with the entry to
	// add by hand.
	if err := os.WriteFile(filepath.Join(proj, ".gemini", "settings.json"), []byte("{\n  // mine\n}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	code, out, _ = run(t, "setup", "gemini", "--project", "--hook-command", good)
	if code != exitFail || !strings.Contains(out, "has comments") || !strings.Contains(out, `"matcher": "^mcp_"`) {
		t.Fatalf("comments: %d %q", code, out)
	}
	if code, _, errb := run(t, "setup", "codex"); code == exitOK || !strings.Contains(errb, "unknown agent") {
		t.Fatalf("unknown agent: %d %q", code, errb)
	}
}

func TestSetupHookCommand(t *testing.T) {
	g := &globalOptions{userConfig: "rel/config.yaml"}
	c, err := setupHookCommand(g, "cursor", false)
	if err != nil {
		t.Fatal(err)
	}
	abs, _ := filepath.Abs("rel/config.yaml")
	if !strings.Contains(c, "--user-config "+abs) || !strings.HasSuffix(c, " hook cursor") {
		t.Fatalf("user command %q", c)
	}
	if c, _ := setupHookCommand(g, "gemini", true); c != "opfence hook gemini" {
		t.Fatalf("project command %q", c)
	}
}

func TestInSrtSession(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("sets XDG_CACHE_HOME")
	}
	cache := t.TempDir()
	t.Setenv("XDG_CACHE_HOME", cache)
	env := func(id string) func(string) string {
		return func(k string) string {
			if k == envSession {
				return id
			}
			return ""
		}
	}
	dir := filepath.Join(cache, "opfence")
	if err := os.MkdirAll(filepath.Join(dir, "srt-0123456789ac.json"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "srt-0123456789ab.json"), []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	for id, want := range map[string]bool{
		"0123456789ab":   true,
		"0123456789ac":   false, // a folder, not the session's file
		"0123456789ff":   false, // no such session
		"":               false,
		"../../etc/pass": false,
		"0123456789AB":   false,
	} {
		if got := inSrtSession(env(id)); got != want {
			t.Errorf("%q: got %v", id, got)
		}
	}
}
