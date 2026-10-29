package main

import (
	"os"
	"regexp"
	"slices"
	"strings"
	"testing"
)

func readFile(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestSetRelease(t *testing.T) {
	formula := readFile(t, "../../Formula/opfence.rb")
	if urlLine.MatchString(formula) {
		t.Fatal("the committed formula already has a release; this test expects a head-only one")
	}
	sum := strings.Repeat("ab", 32)
	got, err := setRelease(formula, archiveURL("sudheer215s/opfence", "v0.1.0"), sum)
	if err != nil {
		t.Fatal(err)
	}
	want := "  homepage \"https://github.com/sudheer215s/opfence\"\n" +
		"  url \"https://github.com/sudheer215s/opfence/archive/refs/tags/v0.1.0.tar.gz\"\n" +
		"  sha256 \"" + sum + "\"\n" +
		"  license \"Apache-2.0\"\n"
	if !strings.Contains(got, want) {
		t.Fatalf("got\n%s", got)
	}
	// A later release replaces the url and hash, nothing else.
	sum2 := strings.Repeat("cd", 32)
	again, err := setRelease(got, archiveURL("sudheer215s/opfence", "v0.2.0"), sum2)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Count(again, "  url \"") != 1 || !strings.Contains(again, "v0.2.0.tar.gz") || !strings.Contains(again, sum2) || strings.Contains(again, sum) {
		t.Fatalf("got\n%s", again)
	}
	if strings.Replace(again, "v0.2.0", "v0.1.0", 1) != strings.Replace(got, sum, sum2, 1) {
		t.Fatal("more than the url and hash changed")
	}
	if _, err := setRelease("class X < Formula\nend\n", "u", sum); err == nil {
		t.Fatal("a formula without a homepage was accepted")
	}
}

func TestTagAndHash(t *testing.T) {
	for tag, ok := range map[string]bool{"v0.1.0": true, "v1.2.3-rc.1": true, "0.1.0": false, "v0.1": false, "v0.1.0\n": false, "": false} {
		if tagRe.MatchString(tag) != ok {
			t.Errorf("tag %q", tag)
		}
	}
	if !shaRe.MatchString(strings.Repeat("0", 64)) || shaRe.MatchString(strings.Repeat("0", 63)) {
		t.Error("sha256 pattern")
	}
}

// TestFormulaMatchesRelease checks the formula builds what GoReleaser
// builds: the same package, version variables and static linking.
func TestFormulaMatchesRelease(t *testing.T) {
	formula := readFile(t, "../../Formula/opfence.rb")
	goreleaser := readFile(t, "../../.goreleaser.yaml")
	vars := regexp.MustCompile(`-X (github\.com/[^=\s]+)=`)
	collect := func(s string) []string {
		var out []string
		for _, m := range vars.FindAllStringSubmatch(s, -1) {
			out = append(out, m[1])
		}
		slices.Sort(out)
		return out
	}
	if f, g := collect(formula), collect(goreleaser); len(f) == 0 || !slices.Equal(f, g) {
		t.Fatalf("version variables: formula %q, GoReleaser %q", f, g)
	}
	for _, want := range []string{`"./cmd/opfence"`, `ENV["CGO_ENABLED"] = "0"`, `std_go_args(ldflags:)`, `depends_on "go" => :build`, `license "Apache-2.0"`} {
		if !strings.Contains(formula, want) {
			t.Errorf("formula lacks %s", want)
		}
	}
	if !strings.Contains(goreleaser, "main: ./cmd/opfence") || !strings.Contains(goreleaser, "CGO_ENABLED=0") {
		t.Error(".goreleaser.yaml changed what it builds; update the formula too")
	}
	if !strings.HasPrefix(strings.TrimSpace(readFile(t, "../../LICENSE")), "Apache License\n") {
		t.Error("the license changed; update the formula's")
	}
}
