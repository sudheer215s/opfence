package launch

import (
	"encoding/json"
	"path/filepath"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/jsonedit"
)

// GeminiHookName is the name of Opfence's Gemini CLI hook. Gemini disables
// a hook whose name is listed in hooksConfig.disabled.
const GeminiHookName = "opfence"

// GeminiHookDefinition is a BeforeTool entry that runs command for every
// MCP tool. Gemini names MCP tools mcp_<server>_<tool>; its timeout is in
// milliseconds.
func GeminiHookDefinition(name, command string) *jsonedit.Object {
	return &jsonedit.Object{Members: []jsonedit.Member{
		{Key: "matcher", Value: "^mcp_"},
		{Key: "hooks", Value: []any{&jsonedit.Object{Members: []jsonedit.Member{
			{Key: "type", Value: "command"},
			{Key: "name", Value: name},
			{Key: "command", Value: command},
			{Key: "timeout", Value: json.Number("30000")},
			{Key: "description", Value: "Opfence decides MCP tool calls"},
		}}}},
	}}
}

// GeminiSettingsFiles are the settings files Gemini CLI reads hooks from:
// the system settings (which Gemini 0.66.0 loads only when root owns the
// file and every folder above it, so opfence run cannot supply its own),
// the user's and the project's (getSystemSettingsPath and loadSettings in
// packages/cli/src/config/settings.ts).
func GeminiSettingsFiles(goos, home, project string, getenv func(string) string) []string {
	system := getenv("GEMINI_CLI_SYSTEM_SETTINGS_PATH")
	if system == "" {
		switch goos {
		case "darwin":
			system = "/Library/Application Support/GeminiCli/settings.json"
		case "windows":
			system = `C:\ProgramData\gemini-cli\settings.json`
		default:
			system = "/etc/gemini-cli/settings.json"
		}
	}
	if d := getenv("GEMINI_CLI_HOME"); d != "" {
		home = d
	}
	return []string{system, filepath.Join(home, ".gemini", "settings.json"), filepath.Join(project, ".gemini", "settings.json")}
}

// GeminiHeadless reports whether Gemini CLI started with args runs with
// nobody to ask, as its isHeadlessMode and interactive setting decide:
// -p/--prompt, standard input or output not a terminal, or CI or
// GITHUB_ACTIONS set to true; -i/--prompt-interactive and --acp keep it
// interactive.
func GeminiHeadless(args []string, terminal bool, getenv func(string) string) bool {
	headless := !terminal
	if getenv("GEMINI_CLI_INTEGRATION_TEST") != "true" && (getenv("CI") == "true" || getenv("GITHUB_ACTIONS") == "true") {
		headless = true
	}
	for _, a := range args {
		if a == "--" {
			break
		}
		name, _, _ := strings.Cut(a, "=")
		switch name {
		case "-p", "--prompt":
			headless = true
		case "-i", "--prompt-interactive", "--acp", "--experimental-acp":
			return false
		}
	}
	return headless
}
