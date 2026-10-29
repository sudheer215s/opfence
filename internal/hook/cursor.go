package hook

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"

	"github.com/rakeshnitb23/opfence/internal/classes"
)

// CursorInput is the part of Cursor's beforeMCPExecution hook input Opfence
// reads: the server's key in its mcp.json, the tool's own name, and its
// arguments as a JSON string. The working folder is the first workspace
// root.
type CursorInput struct {
	HookEventName  string   `json:"hook_event_name"`
	ServerName     string   `json:"mcp_server_name"`
	ToolName       string   `json:"tool_name"`
	ToolInput      string   `json:"tool_input"`
	WorkspaceRoots []string `json:"workspace_roots"`
}

type cursorOutput struct {
	Permission   string `json:"permission,omitempty"`
	UserMessage  string `json:"user_message,omitempty"`
	AgentMessage string `json:"agent_message,omitempty"`
}

// Cursor handles one Cursor beforeMCPExecution call. Cursor runs the hook
// with failClosed, which blocks the call on empty output, so the hook always
// writes JSON: {} (no permission, Cursor's own approval) for calls it knows
// nothing about, and otherwise Opfence's allow, ask or deny. Confirm is ask,
// since a hook cannot make Cursor ask for a typed name. Any error is
// returned; the caller must exit 2, which Cursor takes as a deny.
func Cursor(in io.Reader, out io.Writer, engineFor EngineFor) error {
	data, err := io.ReadAll(io.LimitReader(in, MaxInput+1))
	if err != nil {
		return fmt.Errorf("reading hook input: %w", err)
	}
	if len(data) > MaxInput {
		return errors.New("hook input is larger than 4 MiB")
	}
	var input CursorInput
	if err := json.Unmarshal(data, &input); err != nil {
		return fmt.Errorf("hook input is not valid JSON: %w", err)
	}
	o, err := cursorDecide(input, engineFor)
	if err != nil {
		return err
	}
	enc := json.NewEncoder(out)
	enc.SetEscapeHTML(false)
	return enc.Encode(o)
}

func cursorDecide(input CursorInput, engineFor EngineFor) (cursorOutput, error) {
	if input.HookEventName != "beforeMCPExecution" || input.ServerName == "" || input.ToolName == "" {
		return cursorOutput{}, nil
	}
	cwd := ""
	if len(input.WorkspaceRoots) > 0 {
		cwd = input.WorkspaceRoots[0]
	}
	eng, err := engineFor(cwd)
	if err != nil {
		return cursorOutput{}, err
	}
	if id, ok := eng.Policy.Servers[input.ServerName]; ok && eng.Catalog.Provider(id) == nil {
		return cursorOutput{}, fmt.Errorf("servers: %s maps to %q, which is not a catalog provider", input.ServerName, id)
	}
	prov := ProviderForServer(eng.Catalog, eng.Policy.Servers, input.ServerName)
	if prov == nil {
		return cursorOutput{}, nil
	}
	args := map[string]any{}
	if input.ToolInput != "" {
		dec := json.NewDecoder(bytes.NewReader([]byte(input.ToolInput)))
		dec.UseNumber()
		var v any
		if err := dec.Decode(&v); err != nil {
			return cursorOutput{}, fmt.Errorf("tool_input is not valid JSON: %w", err)
		}
		m, ok := v.(map[string]any)
		if !ok && v != nil {
			return cursorOutput{}, errors.New("tool_input is not a JSON object")
		}
		if m != nil {
			args = m
		}
	}
	eng.Catalog.ToolRulesOnly(prov) // a tool call needs only the provider's MCP rules
	if err := eng.Catalog.LoadRules(prov); err != nil {
		return cursorOutput{}, err
	}
	ev := eng.EvaluateTool(prov, input.ToolName, args).Evaluations[0]
	_, reason := claudeDecision(ev)
	switch ev.Decision {
	case classes.Allow:
		return cursorOutput{Permission: "allow"}, nil
	case classes.Ask, classes.Confirm:
		return cursorOutput{Permission: "ask", UserMessage: reason, AgentMessage: reason}, nil
	default:
		return cursorOutput{Permission: "deny", UserMessage: reason, AgentMessage: reason}, nil
	}
}
