package setup

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os/exec"
	"strings"
	"time"
)

// checkArgs are the arguments of the call Verify asks about: a DROP TABLE
// through Supabase's MCP server, which the catalog decides in every
// environment.
const checkArgs = `{"project_id":"opfence-setup-check","query":"drop table users"}`

// CheckCall describes Verify's call for messages.
const CheckCall = "a DROP TABLE through Supabase's execute_sql"

// sample is the hook input the agent would send for the check call.
func (a *Agent) sample(cwd string) []byte {
	var in any
	switch a.ID {
	case "claude-code":
		in = map[string]any{"hook_event_name": "PreToolUse", "tool_name": "mcp__supabase__execute_sql",
			"tool_input": json.RawMessage(checkArgs), "cwd": cwd}
	case "cursor":
		in = map[string]any{"hook_event_name": "beforeMCPExecution", "mcp_server_name": "supabase",
			"tool_name": "execute_sql", "tool_input": checkArgs, "workspace_roots": []string{cwd}}
	case "gemini":
		in = map[string]any{"hook_event_name": "BeforeTool", "tool_name": "mcp_supabase_execute_sql",
			"tool_input": json.RawMessage(checkArgs), "cwd": cwd,
			"mcp_context": map[string]any{"server_name": "supabase", "tool_name": "execute_sql", "command": "npx"}}
	}
	b, _ := json.Marshal(in)
	return b
}

// Verify runs command as the agent would, with the shell, on the check
// call, from folder cwd, and returns Opfence's decision: allow, ask or deny.
func (a *Agent) Verify(ctx context.Context, command, cwd string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, "sh", "-c", command)
	c.Dir = cwd
	c.Stdin = bytes.NewReader(a.sample(cwd))
	var stdout, stderr bytes.Buffer
	c.Stdout, c.Stderr = &stdout, &stderr
	if err := c.Run(); err != nil {
		msg := strings.TrimSpace(stderr.String())
		if msg == "" {
			msg = err.Error()
		}
		return "", fmt.Errorf("the hook command failed: %s", msg)
	}
	out := bytes.TrimSpace(stdout.Bytes())
	if a.ID == "gemini" && len(out) == 0 {
		return "allow", nil // Gemini's hook prints nothing for an allowed call
	}
	var o struct {
		HookSpecificOutput struct {
			PermissionDecision string `json:"permissionDecision"`
		} `json:"hookSpecificOutput"`
		Permission string `json:"permission"`
		Decision   string `json:"decision"`
	}
	if err := json.Unmarshal(out, &o); err != nil {
		return "", fmt.Errorf("the hook printed %q, not the agent's JSON", out)
	}
	d := map[string]string{
		"claude-code": o.HookSpecificOutput.PermissionDecision,
		"cursor":      o.Permission,
		"gemini":      o.Decision,
	}[a.ID]
	switch d {
	case "allow", "ask", "deny":
		return d, nil
	}
	return "", errors.New("the hook did not decide the check call; is the Supabase MCP server mapped to another provider in your config?")
}

// Diff lists the lines that differ between two files, prefixed with - and
// +, in order, with a line of context around each change.
func Diff(a, b []byte) string {
	x := strings.Split(strings.TrimSuffix(string(a), "\n"), "\n")
	y := strings.Split(strings.TrimSuffix(string(b), "\n"), "\n")
	if len(a) == 0 {
		x = nil
	}
	if len(b) == 0 {
		y = nil
	}
	// Longest common subsequence, by dynamic programming: settings files
	// are short.
	n, m := len(x), len(y)
	lcs := make([][]int, n+1)
	for i := range lcs {
		lcs[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if x[i] == y[j] {
				lcs[i][j] = lcs[i+1][j+1] + 1
			} else {
				lcs[i][j] = max(lcs[i+1][j], lcs[i][j+1])
			}
		}
	}
	type line struct {
		op   byte
		text string
	}
	var lines []line
	i, j := 0, 0
	for i < n || j < m {
		switch {
		case i < n && j < m && x[i] == y[j]:
			lines = append(lines, line{' ', x[i]})
			i++
			j++
		case j < m && (i == n || lcs[i][j+1] >= lcs[i+1][j]):
			lines = append(lines, line{'+', y[j]})
			j++
		default:
			lines = append(lines, line{'-', x[i]})
			i++
		}
	}
	var sb strings.Builder
	last := -2
	for k, l := range lines {
		show := l.op != ' '
		for d := -1; d <= 1 && !show; d += 2 {
			if k+d >= 0 && k+d < len(lines) && lines[k+d].op != ' ' {
				show = true
			}
		}
		if !show {
			continue
		}
		if last >= 0 && k > last+1 {
			sb.WriteString("  ...\n")
		}
		sb.WriteString(string(l.op) + " " + l.text + "\n")
		last = k
	}
	return sb.String()
}
