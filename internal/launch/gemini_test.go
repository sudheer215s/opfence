package launch

import (
	"testing"
)

func TestGeminiSettingsFiles(t *testing.T) {
	env := func(m map[string]string) func(string) string { return func(k string) string { return m[k] } }
	got := GeminiSettingsFiles("linux", "/h", "/p", env(nil))
	if got[0] != "/etc/gemini-cli/settings.json" || got[1] != "/h/.gemini/settings.json" || got[2] != "/p/.gemini/settings.json" {
		t.Fatalf("%q", got)
	}
	got = GeminiSettingsFiles("darwin", "/h", "/p", env(map[string]string{"GEMINI_CLI_HOME": "/g", "GEMINI_CLI_SYSTEM_SETTINGS_PATH": "/s.json"}))
	if got[0] != "/s.json" || got[1] != "/g/.gemini/settings.json" {
		t.Fatalf("%q", got)
	}
	if GeminiSettingsFiles("darwin", "/h", "/p", env(nil))[0] != "/Library/Application Support/GeminiCli/settings.json" {
		t.Fatal("macOS system settings")
	}
}

func TestGeminiHeadless(t *testing.T) {
	none := func(string) string { return "" }
	ci := func(k string) string {
		if k == "CI" {
			return "true"
		}
		return ""
	}
	for _, tc := range []struct {
		args     []string
		terminal bool
		getenv   func(string) string
		want     bool
	}{
		{nil, true, none, false},
		{[]string{"fix the tests"}, true, none, false},
		{[]string{"-p", "fix"}, true, none, true},
		{[]string{"--prompt=fix"}, true, none, true},
		{[]string{"-m", "x", "--prompt", "fix"}, true, none, true},
		{nil, false, none, true},
		{nil, true, ci, true},
		{[]string{"-i", "fix"}, false, ci, false},
		{[]string{"--acp"}, false, none, false},
		{[]string{"--", "-p"}, true, none, false},
	} {
		if got := GeminiHeadless(tc.args, tc.terminal, tc.getenv); got != tc.want {
			t.Errorf("%q terminal=%v: got %v", tc.args, tc.terminal, got)
		}
	}
}

func TestGeminiStateDirHonoursHome(t *testing.T) {
	g := AgentFor("gemini")
	if d := g.StateDir("/h", func(k string) string {
		if k == "GEMINI_CLI_HOME" {
			return "/g"
		}
		return ""
	}); d != "/g/.gemini" {
		t.Fatal(d)
	}
	if !g.IsGemini() || g.IsCursor() || !AgentFor("cursor-agent").IsCursor() {
		t.Fatal("presets")
	}
}
