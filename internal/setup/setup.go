// Package setup adds Opfence's MCP hook to a coding agent's own settings
// (opfence setup), so the agent asks Opfence about each MCP tool call even
// when it is not started by opfence run (docs/ARCHITECTURE.md §8.9).
//
// Settings files belong to the user, so an edit changes only Opfence's
// entry: every other key keeps its value and place, an older Opfence entry
// is replaced rather than joined by a second, and a file Opfence cannot
// rewrite faithfully (Gemini CLI's settings with comments) is left alone.
package setup

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/rakeshnitb23/opfence/internal/jsonedit"
	"github.com/rakeshnitb23/opfence/internal/launch"
)

// Agent is one agent opfence setup knows.
type Agent struct {
	// ID is the name on the command line and in "opfence hook <ID>".
	ID string
	// Name is the agent's name in messages.
	Name string
	// userFile is the settings file in the user's home; projectFile the
	// one in a project, relative to it.
	userFile    func(home string, getenv func(string) string) string
	projectFile string
	// event is the hook event Opfence's entry is under.
	event string
	// entry is Opfence's entry for the event.
	entry func(command string) *jsonedit.Object
	// comments says the agent reads its settings with comments allowed.
	comments bool
	// fresh is the content of a file that holds nothing but Opfence's
	// entry's surroundings (Cursor's hooks.json needs a version).
	fresh func() *jsonedit.Object
}

// Agents are the agents opfence setup knows, by ID.
var Agents = map[string]*Agent{
	"claude-code": {
		ID: "claude-code", Name: "Claude Code",
		// Claude Code keeps its user settings in CLAUDE_CONFIG_DIR when set.
		userFile: func(home string, getenv func(string) string) string {
			if d := getenv("CLAUDE_CONFIG_DIR"); d != "" {
				return filepath.Join(d, "settings.json")
			}
			return filepath.Join(home, ".claude", "settings.json")
		},
		projectFile: filepath.Join(".claude", "settings.json"),
		event:       "PreToolUse",
		entry: func(command string) *jsonedit.Object {
			return obj("matcher", "^mcp__", "hooks", []any{obj(
				"type", "command", "command", command, "timeout", json.Number("30"),
				// A hook that fails or times out must block, not let the call through.
				"onFailure", "block")})
		},
		fresh: func() *jsonedit.Object { return &jsonedit.Object{} },
	},
	"cursor": {
		ID: "cursor", Name: "Cursor",
		// Cursor reads user hooks from ~/.cursor/hooks.json, whatever
		// CURSOR_CONFIG_DIR says (cursor-agent 2026.10.22).
		userFile: func(home string, _ func(string) string) string {
			return filepath.Join(home, ".cursor", "hooks.json")
		},
		projectFile: filepath.Join(".cursor", "hooks.json"),
		event:       "beforeMCPExecution",
		entry: func(command string) *jsonedit.Object {
			// failClosed makes a crash, a timeout or empty output block the
			// call instead of letting it through.
			return obj("command", command, "timeout", json.Number("30"), "failClosed", true)
		},
		fresh: func() *jsonedit.Object { return obj("version", json.Number("1")) },
	},
	"gemini": {
		ID: "gemini", Name: "Gemini CLI",
		userFile: func(home string, getenv func(string) string) string {
			if d := getenv("GEMINI_CLI_HOME"); d != "" {
				home = d
			}
			return filepath.Join(home, ".gemini", "settings.json")
		},
		projectFile: filepath.Join(".gemini", "settings.json"),
		event:       "BeforeTool",
		entry: func(command string) *jsonedit.Object {
			return launch.GeminiHookDefinition(launch.GeminiHookName, command)
		},
		comments: true,
		fresh:    func() *jsonedit.Object { return &jsonedit.Object{} },
	},
}

func obj(kv ...any) *jsonedit.Object {
	o := &jsonedit.Object{}
	for i := 0; i+1 < len(kv); i += 2 {
		o.Members = append(o.Members, jsonedit.Member{Key: kv[i].(string), Value: kv[i+1]})
	}
	return o
}

// File is the settings file for the user (project empty) or a project.
func (a *Agent) File(home, project string, getenv func(string) string) string {
	if project != "" {
		return filepath.Join(project, a.projectFile)
	}
	return a.userFile(home, getenv)
}

// ours matches the command of a hook Opfence installed for agent: the
// opfence program (any path, quoted or not) running "hook <agent>".
func ours(agent, command string) bool {
	re := regexp.MustCompile(`(^|[/\\'"])opfence(\.exe)?['"]?\s(.*\s)?hook\s+` + regexp.QuoteMeta(agent) + `(\s|$)`)
	return re.MatchString(command)
}

// Change is what Install or Remove did to a settings file.
type Change struct {
	File string
	// Before and After are the file's contents; Before is nil for a file
	// that did not exist and After nil for one removed.
	Before, After []byte
	// Notes are things the user should know: settings that keep the hook
	// from running.
	Notes []string
}

// Changed reports whether the file's contents change.
func (c Change) Changed() bool {
	return !bytes.Equal(c.Before, c.After) || (c.Before == nil) != (c.After == nil)
}

// ErrComments is returned for a Gemini CLI settings file with comments,
// which a rewrite would lose.
var ErrComments = errors.New("the file has comments, which rewriting it would lose")

// read loads a settings file to change it: nil content for a missing or
// blank file, and ErrComments for comments the agent allows, which a
// rewrite would lose.
func (a *Agent) read(file string) ([]byte, *jsonedit.Object, error) {
	return a.load(file, false)
}

// load reads a settings file; with readOnly, comments the agent allows are
// skipped instead of refused.
func (a *Agent) load(file string, readOnly bool) ([]byte, *jsonedit.Object, error) {
	data, err := os.ReadFile(file)
	if errors.Is(err, fs.ErrNotExist) {
		return nil, a.fresh(), nil
	}
	if err != nil {
		return nil, nil, err
	}
	if jsonedit.IsBlank(data) {
		return data, a.fresh(), nil
	}
	parse := data
	if a.comments {
		stripped, found := jsonedit.StripComments(data)
		if found && !readOnly {
			return data, nil, ErrComments
		}
		parse = stripped
	}
	v, err := jsonedit.Parse(parse)
	if err != nil {
		return data, nil, fmt.Errorf("%s is not valid JSON: %w", file, err)
	}
	root, ok := v.(*jsonedit.Object)
	if !ok {
		return data, nil, fmt.Errorf("%s is not a JSON object", file)
	}
	return data, root, nil
}

// handlers returns the hook handlers of one entry of the event's list: the
// entry itself for Cursor, whose entries are handlers, and its hooks list
// for the others.
func (a *Agent) handlers(entry any) ([]any, bool) {
	o, ok := entry.(*jsonedit.Object)
	if !ok {
		return nil, false
	}
	if a.ID == "cursor" {
		return []any{o}, true
	}
	hs, _ := o.Get("hooks")
	list, ok := hs.([]any)
	return list, ok
}

func command(h any) string {
	o, ok := h.(*jsonedit.Object)
	if !ok {
		return ""
	}
	c, _ := o.Get("command")
	s, _ := c.(string)
	return s
}

// eventList returns the root's hooks object and the event's list in it.
func (a *Agent) eventList(root *jsonedit.Object, create bool) (*jsonedit.Object, []any, error) {
	hv, ok := root.Get("hooks")
	if !ok || hv == nil {
		if !create {
			return nil, nil, nil
		}
		hv = &jsonedit.Object{}
		root.Set("hooks", hv)
	}
	hooks, ok := hv.(*jsonedit.Object)
	if !ok {
		return nil, nil, errors.New(`"hooks" is not an object`)
	}
	ev, ok := hooks.Get(a.event)
	if !ok || ev == nil {
		return hooks, nil, nil
	}
	list, ok := ev.([]any)
	if !ok {
		return nil, nil, fmt.Errorf(`"hooks.%s" is not a list`, a.event)
	}
	return hooks, list, nil
}

// withoutOurs returns the event's list with Opfence's handlers removed,
// dropping entries left with no handlers; whether any was removed; and
// where in the returned list the first one was, so a new entry can take its
// place. A handler running exactly also counts as Opfence's too.
func (a *Agent) withoutOurs(list []any, also string) ([]any, bool, int) {
	out := []any{}
	at := -1
	for _, e := range list {
		hs, ok := a.handlers(e)
		if !ok {
			out = append(out, e)
			continue
		}
		var keep []any
		for _, h := range hs {
			if c := command(h); !ours(a.ID, c) && (also == "" || c != also) {
				keep = append(keep, h)
			}
		}
		if len(keep) < len(hs) && at < 0 {
			at = len(out)
		}
		switch {
		case len(keep) == len(hs):
			out = append(out, e)
		case len(keep) > 0:
			// Another handler shares the entry: keep it with its matcher.
			e.(*jsonedit.Object).Set("hooks", keep)
			out = append(out, e)
		}
	}
	return out, at >= 0, at
}

// Install returns the change that adds Opfence's hook running command to
// the settings file: the new entry takes the place of an earlier Opfence
// hook, or goes at the end of the event's list. The file is not written.
func (a *Agent) Install(file, command string) (Change, error) {
	before, root, err := a.read(file)
	if err != nil {
		return Change{File: file, Before: before}, err
	}
	hooks, list, err := a.eventList(root, true)
	if err != nil {
		return Change{File: file, Before: before}, fmt.Errorf("%s: %w", file, err)
	}
	list, found, at := a.withoutOurs(list, command)
	if !found {
		at = len(list)
	}
	list = append(list[:at], append([]any{a.entry(command)}, list[at:]...)...)
	hooks.Set(a.event, list)
	if a.ID == "cursor" {
		// Cursor ignores a hooks.json without a version.
		if _, ok := root.Get("version"); !ok {
			root.Members = append([]jsonedit.Member{{Key: "version", Value: json.Number("1")}}, root.Members...)
		}
	}
	after, err := jsonedit.Marshal(root)
	if err != nil {
		return Change{File: file, Before: before}, err
	}
	if before != nil && sameJSON(before, after, a.comments) {
		after = before // only the formatting would change
	}
	return Change{File: file, Before: before, After: after, Notes: a.notes(root)}, nil
}

// Remove returns the change that takes Opfence's hooks out of the settings
// file. Lists and objects left empty go too, and a file left with nothing
// in it is removed (After nil).
func (a *Agent) Remove(file string) (Change, error) {
	before, root, err := a.read(file)
	if err != nil {
		return Change{File: file, Before: before}, err
	}
	if before == nil {
		return Change{File: file}, nil
	}
	hooks, list, err := a.eventList(root, false)
	if err != nil {
		return Change{File: file, Before: before}, fmt.Errorf("%s: %w", file, err)
	}
	list, removed, _ := a.withoutOurs(list, "")
	if !removed {
		return Change{File: file, Before: before, After: before}, nil
	}
	if len(list) == 0 {
		hooks.Delete(a.event)
	} else {
		hooks.Set(a.event, list)
	}
	if hooks.Len() == 0 {
		root.Delete("hooks")
	}
	if emptyOf(root, a.fresh()) {
		return Change{File: file, Before: before}, nil
	}
	after, err := jsonedit.Marshal(root)
	if err != nil {
		return Change{File: file, Before: before}, err
	}
	return Change{File: file, Before: before, After: after}, nil
}

// emptyOf reports whether root holds no more than a fresh file would.
func emptyOf(root, fresh *jsonedit.Object) bool {
	for _, m := range root.Members {
		v, ok := fresh.Get(m.Key)
		if !ok || !equal(v, m.Value) {
			return false
		}
	}
	return true
}

func equal(a, b any) bool {
	x, err1 := jsonedit.Marshal(a)
	y, err2 := jsonedit.Marshal(b)
	return err1 == nil && err2 == nil && bytes.Equal(x, y)
}

// sameJSON reports whether two settings files hold the same JSON, so that
// re-running setup does not rewrite a file only to reformat it.
func sameJSON(a, b []byte, comments bool) bool {
	if comments {
		a, _ = jsonedit.StripComments(a)
	}
	va, err1 := jsonedit.Parse(a)
	vb, err2 := jsonedit.Parse(b)
	return err1 == nil && err2 == nil && equal(va, vb)
}

// notes reports settings in the file that keep any hook from running.
func (a *Agent) notes(root *jsonedit.Object) []string {
	var out []string
	switch a.ID {
	case "claude-code":
		if v, _ := root.Get("disableAllHooks"); v == true {
			out = append(out, `"disableAllHooks": true turns off every hook, Opfence's included`)
		}
	case "gemini":
		hc, _ := root.Get("hooksConfig")
		if o, ok := hc.(*jsonedit.Object); ok {
			if v, _ := o.Get("enabled"); v == false {
				out = append(out, `"hooksConfig.enabled": false turns off every hook, Opfence's included`)
			}
			d, _ := o.Get("disabled")
			if list, ok := d.([]any); ok {
				for _, n := range list {
					if n == launch.GeminiHookName {
						out = append(out, `"hooksConfig.disabled" lists "opfence", which turns Opfence's hook off`)
					}
				}
			}
		}
	}
	return out
}

// Apply writes a change: atomically, through a symbolic link to the file
// it points at, keeping the file's permissions. A change with After nil
// removes the file.
func Apply(c Change) error {
	if !c.Changed() {
		return nil
	}
	target := c.File
	if t, err := filepath.EvalSymlinks(c.File); err == nil {
		target = t
	}
	if c.After == nil {
		if err := os.Remove(target); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return err
		}
		return nil
	}
	mode := fs.FileMode(0o644)
	if st, err := os.Stat(target); err == nil {
		mode = st.Mode().Perm()
	}
	dir := filepath.Dir(target)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, "."+filepath.Base(target)+".opfence-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(c.After); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), target)
}

// Revert undoes Apply: the file gets its earlier contents back, or is
// removed if it did not exist.
func Revert(c Change) error {
	return Apply(Change{File: c.File, Before: c.After, After: c.Before})
}

// Installed reports whether any of files has Opfence's hook for the agent.
// Missing or unreadable files count as not having it.
func (a *Agent) Installed(files ...string) bool {
	for _, f := range files {
		_, root, err := a.load(f, true)
		if err != nil || root == nil {
			continue
		}
		_, list, err := a.eventList(root, false)
		if err != nil {
			continue
		}
		if _, found, _ := a.withoutOurs(list, ""); found {
			return true
		}
	}
	return false
}

// Off returns a note for each of files whose settings turn every hook, or
// Opfence's, off. Missing or unreadable files are skipped.
func (a *Agent) Off(files ...string) []string {
	var out []string
	for _, f := range files {
		_, root, err := a.load(f, true)
		if err != nil || root == nil {
			continue
		}
		for _, n := range a.notes(root) {
			out = append(out, f+": "+n)
		}
	}
	return out
}

// CursorHookFiles are the files Cursor's CLI reads hooks from, besides
// Claude Code's settings: the system-wide file, the user's and the
// project's (cursor-agent 2026.10.22).
func CursorHookFiles(goos, home, project string) []string {
	system := "/etc/cursor/hooks.json"
	switch goos {
	case "darwin":
		system = "/Library/Application Support/Cursor/hooks.json"
	case "windows":
		system = `C:\ProgramData\Cursor\hooks.json`
	}
	return []string{system, filepath.Join(home, ".cursor", "hooks.json"), filepath.Join(project, ".cursor", "hooks.json")}
}

// Description says in a few words what the hook entry does, for messages.
func (a *Agent) Description() string {
	return fmt.Sprintf("a %s hook that asks Opfence about each MCP tool call", a.event)
}

// SortedIDs lists the agents' IDs for help text.
func SortedIDs() string {
	return strings.Join([]string{"claude-code", "cursor", "gemini"}, ", ")
}
