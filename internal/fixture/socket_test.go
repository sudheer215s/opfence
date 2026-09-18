package fixture

import (
	"strings"
	"testing"
)

const head = "# description: x\nGET /graphql/v2 HTTP/1.1\nHost: backboard.railway.com\nUpgrade: websocket\nConnection: Upgrade\n\n"

func TestParseSocket(t *testing.T) {
	s, err := ParseSocket([]byte(head + ">>> text\n{\"a\":\n 1}\n\n>>> binary\n# a comment\n\"Q\\x00\\x00\\x00\\x0d\" \"SELECT 1\\x00\"\n\"X\"\n>>> text\n#{\"no\"}\nlast\n"))
	if err != nil {
		t.Fatal(err)
	}
	if s.Upgrade.Method != "GET" || s.Upgrade.Host != "backboard.railway.com" || s.Upgrade.Path != "/graphql/v2" || len(s.Messages) != 3 {
		t.Fatalf("%+v", s)
	}
	if m := s.Messages[0]; m.Binary || string(m.Data) != "{\"a\":\n 1}" {
		t.Fatalf("text %q", m.Data)
	}
	if m := s.Messages[1]; !m.Binary || string(m.Data) != "Q\x00\x00\x00\x0dSELECT 1\x00X" {
		t.Fatalf("binary %q", m.Data)
	}
	if string(s.Messages[2].Data) != "last" {
		t.Fatalf("%q", s.Messages[2].Data)
	}
	if !IsSocket([]byte(head+">>> text\n{}")) || IsSocket([]byte(head)) {
		t.Fatal("IsSocket")
	}
	for in, want := range map[string]string{
		head:                            "no messages",
		head + ">>> json\n{}":           "must be text or binary",
		head + ">>> binary\nQ\\x00":     "not a Go string literal",
		head + ">>> binary\n\"Q\" junk": "not a Go string literal",
	} {
		if _, err := ParseSocket([]byte(in)); err == nil || !strings.Contains(err.Error(), want) {
			t.Errorf("%q: %v, want %q", in, err, want)
		}
	}
}
