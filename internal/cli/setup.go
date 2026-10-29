package cli

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"

	"github.com/spf13/cobra"

	"github.com/rakeshnitb23/opfence/internal/jsonedit"
	"github.com/rakeshnitb23/opfence/internal/launch"
	"github.com/rakeshnitb23/opfence/internal/policy"
	"github.com/rakeshnitb23/opfence/internal/setup"
)

func newSetupCmd(g *globalOptions) *cobra.Command {
	var project, undo, dryRun bool
	var hookCmd string
	cmd := &cobra.Command{
		Use:   "setup AGENT",
		Short: "Add Opfence's MCP hook to an agent's settings (claude-code, cursor, gemini)",
		Long: `Adds a hook to the agent's own settings that asks Opfence about each MCP tool
call, with its arguments, also when the agent is not started by opfence run:

  claude-code   ~/.claude/settings.json (or $CLAUDE_CONFIG_DIR), PreToolUse
  cursor        ~/.cursor/hooks.json, beforeMCPExecution
  gemini        ~/.gemini/settings.json (or $GEMINI_CLI_HOME), BeforeTool

Everything else in the file keeps its value and place, and an earlier
Opfence hook is replaced. The hook runs this opfence binary with your user
config's path, so a project's settings cannot point it at another config.
After writing, setup runs the hook on a sample call to prove it decides, and
puts the file back if it does not. --project writes the project's file
instead (.claude/settings.json, .cursor/hooks.json, .gemini/settings.json),
with a plain "opfence" command for teammates. --undo removes Opfence's hook.`,
		Args:      cobra.ExactArgs(1),
		ValidArgs: []string{"claude-code", "cursor", "gemini"},
		RunE: func(cmd *cobra.Command, args []string) error {
			a := setup.Agents[args[0]]
			if a == nil {
				return fmt.Errorf("unknown agent %q (want %s)", args[0], setup.SortedIDs())
			}
			w := cmd.OutOrStdout()
			home, err := os.UserHomeDir()
			if err != nil {
				return err
			}
			projectDir := ""
			if project {
				if projectDir, err = os.Getwd(); err != nil {
					return err
				}
			}
			file := a.File(home, projectDir, os.Getenv)
			var change setup.Change
			command := hookCmd
			if undo {
				change, err = a.Remove(file)
			} else {
				if command == "" {
					command, err = setupHookCommand(g, a.ID, project)
					if err != nil {
						return err
					}
				}
				change, err = a.Install(file, command)
			}
			if errors.Is(err, setup.ErrComments) {
				return setupByHand(w, a, file, command, undo)
			}
			if err != nil {
				return err
			}
			if dryRun {
				if !change.Changed() {
					fmt.Fprintf(w, "%s would not change.\n", file)
					return nil
				}
				fmt.Fprintf(w, "Would change %s:\n%s", file, setup.Diff(change.Before, change.After))
				return nil
			}
			if err := setup.Apply(change); err != nil {
				return err
			}
			if undo {
				switch {
				case !change.Changed():
					fmt.Fprintf(w, "%s has no Opfence hook.\n", file)
				case change.After == nil:
					fmt.Fprintf(w, "Removed Opfence's hook from %s, and the file, which held nothing else.\n", file)
				default:
					fmt.Fprintf(w, "Removed Opfence's hook from %s.\n", file)
				}
				return nil
			}
			if change.Changed() {
				fmt.Fprintf(w, "Added %s to %s.\n", a.Description(), file)
			} else {
				fmt.Fprintf(w, "%s already has Opfence's hook.\n", file)
			}
			if runtime.GOOS != "windows" {
				decision, verr := a.Verify(cmd.Context(), command, os.TempDir())
				if verr != nil {
					if rerr := setup.Revert(change); rerr != nil {
						return fmt.Errorf("%v; putting %s back also failed: %v", verr, file, rerr)
					}
					if change.Changed() {
						return fmt.Errorf("%v; %s is back as it was", verr, file)
					}
					return verr
				}
				fmt.Fprintf(w, "Checked: the hook decides %s: %s.\n", setup.CheckCall, decision)
			}
			for _, n := range change.Notes {
				fmt.Fprintf(w, "Note: %s.\n", n)
			}
			setupNextSteps(w, a.ID, project)
			return nil
		},
	}
	cmd.Flags().BoolVar(&project, "project", false, "write the project's settings in the current folder instead of yours")
	cmd.Flags().BoolVar(&undo, "undo", false, "remove Opfence's hook")
	cmd.Flags().BoolVar(&dryRun, "dry-run", false, "show the change without writing it")
	cmd.Flags().StringVar(&hookCmd, "hook-command", "", "command the agent runs for the hook (default: this opfence binary)")
	return cmd
}

// setupHookCommand is the hook's shell command. A user's hook runs this
// binary by its path on PATH when that is the same file (so it survives an
// upgrade that moves the real file, as Homebrew's do), with the catalog and
// policy flags given to setup and the user config's absolute path. A
// project's hook runs "opfence hook <agent>", for whoever opens the project.
func setupHookCommand(g *globalOptions, agent string, project bool) (string, error) {
	if project {
		return launch.AgentHookCommand("opfence", nil, agent), nil
	}
	cfg := g.userConfig
	if cfg == "" {
		cfg = policy.UserConfigPath()
	}
	if cfg != "" {
		abs, err := filepath.Abs(cfg)
		if err != nil {
			return "", err
		}
		cfg = abs
	}
	return launch.AgentHookCommand(stableExecutable(), g.hookArgs(cfg), agent), nil
}

// stableExecutable is this binary's path, preferring the one PATH finds.
func stableExecutable() string {
	exe, err := os.Executable()
	if err != nil {
		return "opfence"
	}
	if p, err := exec.LookPath("opfence"); err == nil {
		if abs, err := filepath.Abs(p); err == nil {
			a, err1 := os.Stat(abs)
			b, err2 := os.Stat(exe)
			if err1 == nil && err2 == nil && os.SameFile(a, b) {
				return abs
			}
		}
	}
	return exe
}

// setupByHand explains what to add to (or remove from) a settings file
// setup will not rewrite.
func setupByHand(w io.Writer, a *setup.Agent, file, command string, undo bool) error {
	if undo {
		fmt.Fprintf(w, "%s has comments, which rewriting it would lose. Remove the hook whose command runs \"opfence hook %s\" from its \"hooks\" by hand.\n", file, a.ID)
		return failError{"settings not changed"}
	}
	entry, err := jsonedit.Marshal(launch.GeminiHookDefinition(launch.GeminiHookName, command))
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "%s has comments, which rewriting it would lose. Add this entry to the \"BeforeTool\" list under \"hooks\" by hand:\n\n%s", file, entry)
	return failError{"settings not changed"}
}

func setupNextSteps(w io.Writer, agent string, project bool) {
	switch agent {
	case "claude-code":
		fmt.Fprintln(w, "MCP tool calls are decided now. For everything else Claude Code does (its own requests, the CLIs it runs), start it with: opfence run -- claude")
	case "cursor":
		fmt.Fprintln(w, "Cursor's editor asks where Opfence asks; its CLI (cursor-agent) enforces a deny but runs a call Opfence would ask about, so for the requests those calls make, start it with: opfence run --srt -- cursor-agent")
	case "gemini":
		fmt.Fprintln(w, "Gemini CLI 0.36.0 or later asks where Opfence asks. For everything else Gemini does, start it with: opfence run --srt -- gemini")
	}
	if project {
		fmt.Fprintln(w, "Everyone who opens this project needs opfence on their PATH, or the agent blocks its MCP tool calls.")
	}
}
