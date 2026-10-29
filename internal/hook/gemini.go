package hook

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/catalog"
	"github.com/rakeshnitb23/opfence/internal/classes"
)

// GeminiInput is the part of Gemini CLI's BeforeTool hook input Opfence
// reads (packages/core/src/hooks/types.ts, BeforeToolInput).
type GeminiInput struct {
	HookEventName string         `json:"hook_event_name"`
	ToolName      string         `json:"tool_name"`
	ToolInput     map[string]any `json:"tool_input"`
	Cwd           string         `json:"cwd"`
	MCPContext    *struct {
		ServerName string `json:"server_name"`
		ToolName   string `json:"tool_name"`
		Command    string `json:"command"`
		URL        string `json:"url"`
		TCP        string `json:"tcp"`
	} `json:"mcp_context"`
}

// EnvGeminiHeadless is set by opfence run when Gemini CLI runs with nobody
// to ask. It can only make the hook stricter, so the environment, which a
// project's .env file can add to, may carry it.
const EnvGeminiHeadless = "OPFENCE_GEMINI_HEADLESS"

// GeminiFlags are what the hook knows about the session it runs in.
type GeminiFlags struct {
	// Proxied says the hook runs in an opfence run session, whose proxy
	// decides the requests of servers Gemini reaches over the network; the
	// hook leaves those to it, so nothing is asked twice. The caller must
	// establish it from something a project cannot set (see the CLI).
	Proxied bool
	// Headless says Gemini runs without a person to ask (gemini -p, or no
	// terminal). Gemini CLI 0.66.0 then waits forever on a hook's ask
	// instead of denying the call as it does its own, so the hook denies.
	// EnvGeminiHeadless, and CI or GITHUB_ACTIONS set to true (as for
	// Gemini), mean the same.
	Headless bool
	// Getenv reads the hook's environment; nil means none.
	Getenv func(string) string
}

func (f GeminiFlags) headless() bool {
	if f.Headless {
		return true
	}
	if f.Getenv == nil {
		return false
	}
	if f.Getenv(EnvGeminiHeadless) == "1" {
		return true
	}
	if f.Getenv("GEMINI_CLI_INTEGRATION_TEST") == "true" {
		return false
	}
	return f.Getenv("CI") == "true" || f.Getenv("GITHUB_ACTIONS") == "true"
}

type geminiOutput struct {
	Decision      string `json:"decision"`
	Reason        string `json:"reason,omitempty"`
	SystemMessage string `json:"systemMessage,omitempty"`
}

// Gemini handles one Gemini CLI BeforeTool call for an MCP tool:
//
//   - deny: decision deny, whose reason Gemini returns to the model as the
//     tool's error.
//   - ask and confirm: decision ask, which makes Gemini show its own
//     confirmation even in YOLO mode or for a trusted server (Gemini CLI
//     0.36.0 and later); a deny when nobody can be asked (see GeminiFlags).
//   - allow: no output, which leaves the call to Gemini's own approval.
//
// Calls it knows nothing about get no output. Any error is returned; the
// caller must exit 2, which Gemini takes as a block with the error as the
// reason.
func Gemini(in io.Reader, out io.Writer, engineFor EngineFor, o GeminiFlags) error {
	data, err := io.ReadAll(io.LimitReader(in, MaxInput+1))
	if err != nil {
		return fmt.Errorf("reading hook input: %w", err)
	}
	if len(data) > MaxInput {
		return errors.New("hook input is larger than 4 MiB")
	}
	var input GeminiInput
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	if err := dec.Decode(&input); err != nil {
		return fmt.Errorf("hook input is not valid JSON: %w", err)
	}
	if input.HookEventName != "BeforeTool" {
		return nil
	}
	ctx := input.MCPContext
	if ctx != nil && o.Proxied && (ctx.URL != "" || ctx.TCP != "") {
		return nil
	}
	eng, err := engineFor(input.Cwd)
	if err != nil {
		return err
	}
	var prov *catalog.Provider
	var tool string
	switch {
	case ctx != nil && ctx.ServerName != "" && ctx.ToolName != "":
		if id, ok := eng.Policy.Servers[ctx.ServerName]; ok && eng.Catalog.Provider(id) == nil {
			return fmt.Errorf("servers: %s maps to %q, which is not a catalog provider", ctx.ServerName, id)
		}
		prov, tool = ProviderForServer(eng.Catalog, eng.Policy.Servers, ctx.ServerName), ctx.ToolName
	case strings.HasPrefix(input.ToolName, "mcp_"):
		// Gemini leaves mcp_context out when it cannot find the server's
		// configuration; the name is then all there is.
		prov, tool = geminiToolByName(eng.Catalog, eng.Policy.Servers, input.ToolName)
	}
	if prov == nil {
		return nil
	}
	eng.Catalog.ToolRulesOnly(prov) // a tool call needs only the provider's MCP rules
	if err := eng.Catalog.LoadRules(prov); err != nil {
		return err
	}
	ev := eng.EvaluateTool(prov, tool, input.ToolInput).Evaluations[0]
	_, reason := claudeDecision(ev)
	var res geminiOutput
	switch {
	case ev.Decision == classes.Allow:
		return nil
	case (ev.Decision == classes.Ask || ev.Decision == classes.Confirm) && !o.headless():
		res = geminiOutput{Decision: "ask", SystemMessage: reason}
	case ev.Decision == classes.Ask || ev.Decision == classes.Confirm:
		reason = "Gemini CLI is running with nobody to ask (non-interactive), so Opfence denies what it would ask about. " + reason
		res = geminiOutput{Decision: "deny", Reason: reason, SystemMessage: reason}
	default:
		res = geminiOutput{Decision: "deny", Reason: reason, SystemMessage: reason}
	}
	enc := json.NewEncoder(out)
	enc.SetEscapeHTML(false)
	return enc.Encode(res)
}

// geminiInvalid is what Gemini replaces in a server or tool name to make a
// function name (generateValidName in packages/core/src/tools/mcp-tool.ts).
var geminiInvalid = regexp.MustCompile(`[^a-zA-Z0-9_\-.:]`)

// geminiToolByName finds the provider and tool for Gemini's function name
// mcp_<server>_<tool>. Server names may hold underscores, so every name
// Opfence knows is tried as the server, the longest first. A name Gemini
// shortened (with "...") is not split.
func geminiToolByName(c *catalog.Catalog, aliases map[string]string, name string) (*catalog.Provider, string) {
	if strings.Contains(name, "...") {
		return nil, ""
	}
	var names []string
	for n := range aliases {
		names = append(names, n)
	}
	for _, p := range c.Providers {
		if p.MCP != nil {
			names = append(names, p.MCP.Names...)
		}
	}
	best, tool := "", ""
	for _, n := range names {
		prefix := "mcp_" + geminiInvalid.ReplaceAllString(n, "_") + "_"
		if rest, ok := strings.CutPrefix(name, prefix); ok && rest != "" && len(n) > len(best) {
			best, tool = n, rest
		}
	}
	if best == "" {
		return nil, ""
	}
	return ProviderForServer(c, aliases, best), tool
}
