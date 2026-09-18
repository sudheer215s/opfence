package decode

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"testing"
)

func phoenixSession(vsn string) *phoenixWS {
	h := upgrade("/realtime/v1/websocket?apikey=k&vsn=" + vsn)
	h.Query = url.Values{"apikey": {"k"}, "vsn": {vsn}}
	return NewWSSession(WSPhoenix, "", h, Hints{}).(*phoenixWS)
}

func pushBinary(joinRef, ref, topic, event, meta string, enc byte, payload string) []byte {
	b := []byte{3, byte(len(joinRef)), byte(len(ref)), byte(len(topic)), byte(len(event)), byte(len(meta)), enc}
	return append(append(b, joinRef+ref+topic+event+meta...), payload...)
}

func TestPhoenixSession(t *testing.T) {
	s := phoenixSession("2.0.0")
	join := `["1","1","realtime:orders","phx_join",{"config":{"postgres_changes":[{"event":"*","schema":"public","table":"orders"}]},"access_token":"tok_123"}]`
	st := s.Client(text(join))
	if len(st.Ops) != 1 || st.Ops[0].Method != PhoenixJoin || st.Ops[0].Args["topic"] != "realtime:orders" || len(st.Swap) != 1 || st.Swap[0] != "tok_123" {
		t.Fatalf("join: %+v", st)
	}
	if cfg, _ := st.Ops[0].Args["config"].(map[string]any); cfg["postgres_changes"] == nil {
		t.Fatalf("config %v", st.Ops[0].Args)
	}
	for _, m := range []string{`[null,"2","phoenix","heartbeat",{}]`, `["1","3","realtime:orders","phx_leave",{}]`} {
		if st := s.Client(text(m)); st.Decides() {
			t.Errorf("%s: %+v", m, st)
		}
	}
	if st := s.Client(text(`["1","4","realtime:orders","access_token",{"access_token":"tok_456"}]`)); st.Decides() || len(st.Swap) != 1 || st.Swap[0] != "tok_456" {
		t.Fatalf("access_token: %+v", st)
	}
	st = s.Client(WSMessage{Binary: true, Data: pushBinary("1", "5", "realtime:room", "cursor", "", 1, `{"x":1}`)})
	if len(st.Ops) != 1 || st.Ops[0].Method != PhoenixBroadcast || st.Ops[0].Args["event"] != "cursor" || st.Ops[0].Args["topic"] != "realtime:room" {
		t.Fatalf("binary broadcast: %+v", st)
	}
	replies, closeSocket := s.Blocked(st, "Blocked by Opfence: no.")
	var reply []json.RawMessage
	if closeSocket || json.Unmarshal(replies[0].Data, &reply) != nil || len(reply) != 5 || string(reply[1]) != `"5"` || string(reply[2]) != `"realtime:room"` ||
		string(reply[3]) != `"phx_reply"` || !strings.Contains(string(reply[4]), `"status":"error"`) || !strings.Contains(string(reply[4]), "Blocked by Opfence: no.") {
		t.Fatalf("reply %s", replies[0].Data)
	}
	st = s.Client(text(`["1","6","realtime:room","presence",{"type":"presence","event":"track","payload":{"u":1}}]`))
	if len(st.Ops) != 1 || st.Ops[0].Method != PhoenixPresence || st.Ops[0].Args["event"] != "track" {
		t.Fatalf("presence: %+v", st)
	}

	// Serializer 1.0.0.
	v1 := phoenixSession("1.0.0")
	st = v1.Client(text(`{"topic":"realtime:x","event":"broadcast","payload":{"type":"broadcast","event":"e","payload":{}},"ref":"2","join_ref":"1"}`))
	if len(st.Ops) != 1 || st.Ops[0].Method != PhoenixBroadcast {
		t.Fatalf("v1: %+v", st)
	}
	replies, _ = v1.Blocked(st, "no")
	var obj map[string]any
	if json.Unmarshal(replies[0].Data, &obj) != nil || obj["event"] != "phx_reply" || obj["ref"] != "2" || obj["topic"] != "realtime:x" {
		t.Fatalf("v1 reply %s", replies[0].Data)
	}
}

func TestPhoenixSessionFailsClosed(t *testing.T) {
	for name, c := range map[string]struct {
		s *phoenixWS
		m WSMessage
	}{
		"not json":            {phoenixSession("2.0.0"), text(`hi`)},
		"short array":         {phoenixSession("2.0.0"), text(`["1","1","t","phx_join"]`)},
		"object under v2":     {phoenixSession("2.0.0"), text(`{"topic":"t","event":"phx_join","payload":{},"ref":"1"}`)},
		"array under v1":      {phoenixSession("1.0.0"), text(`["1","1","t","phx_join",{}]`)},
		"payload not object":  {phoenixSession("2.0.0"), text(`["1","1","t","broadcast","x"]`)},
		"duplicate key":       {phoenixSession("2.0.0"), text(`["1","1","t","broadcast",{"event":"a","event":"b"}]`)},
		"unknown event":       {phoenixSession("2.0.0"), text(`["1","1","t","postgres_changes",{}]`)},
		"binary under v1":     {phoenixSession("1.0.0"), WSMessage{Binary: true, Data: pushBinary("1", "1", "t", "e", "", 1, `{}`)}},
		"binary short":        {phoenixSession("2.0.0"), WSMessage{Binary: true, Data: []byte{3, 9, 9}}},
		"binary other kind":   {phoenixSession("2.0.0"), WSMessage{Binary: true, Data: pushBinary("1", "1", "t", "e", "", 1, `{}`)[1:]}},
		"binary bad encoding": {phoenixSession("2.0.0"), WSMessage{Binary: true, Data: pushBinary("1", "1", "t", "e", "", 7, `{}`)}},
		"binary bad json":     {phoenixSession("2.0.0"), WSMessage{Binary: true, Data: pushBinary("1", "1", "t", "e", "", 1, `{`)}},
	} {
		st := c.s.Client(c.m)
		if len(st.Ops) != 1 || st.Ops[0].Error == "" {
			t.Errorf("%s: %+v", name, st)
		}
	}
	// An event with no ref cannot be answered: the socket closes.
	s := phoenixSession("2.0.0")
	st := s.Client(text(`[null,null,"t","broadcast",{"event":"e"}]`))
	if _, closeSocket := s.Blocked(st, "no"); !closeSocket {
		t.Fatal("blocked without a ref, socket left open")
	}
}

func hranaSession() *hranaWS {
	return NewWSSession(WSHrana, "hrana2", upgrade("/"), Hints{}).(*hranaWS)
}

func hranaSQL(t *testing.T, st WSStep) []string {
	t.Helper()
	if len(st.Ops) != 1 || st.Ops[0].Method != HranaRequest {
		t.Fatalf("%+v", st)
	}
	texts, unread, ok := LibSQLStatements(st.Ops[0].Args["request"])
	if !ok {
		t.Fatalf("not a pipeline: %v", st.Ops[0].Args)
	}
	if unread {
		texts = append(texts, "(unread)")
	}
	return texts
}

func TestHranaSession(t *testing.T) {
	s := hranaSession()
	if st := s.Client(text(`{"type":"hello","jwt":"tok_abc"}`)); st.Decides() || len(st.Swap) != 1 || st.Swap[0] != "tok_abc" {
		t.Fatalf("hello: %+v", st)
	}
	for _, r := range []string{"open_stream", "close_stream", "describe", "get_autocommit", "close_cursor", "fetch_cursor"} {
		if st := s.Client(text(`{"type":"request","request_id":1,"request":{"type":"` + r + `","stream_id":0}}`)); st.Decides() {
			t.Errorf("%s: %+v", r, st)
		}
	}
	got := hranaSQL(t, s.Client(text(`{"type":"request","request_id":2,"request":{"type":"execute","stream_id":0,"stmt":{"sql":"DROP TABLE t"}}}`)))
	if strings.Join(got, "|") != "DROP TABLE t" {
		t.Fatalf("%q", got)
	}
	// Stored SQL counts once forwarded, and a later request runs it.
	store := s.Client(text(`{"type":"request","request_id":3,"request":{"type":"store_sql","sql_id":5,"sql":"DELETE FROM t"}}`))
	if store.Decides() {
		t.Fatalf("store: %+v", store)
	}
	run := `{"type":"request","request_id":4,"request":{"type":"batch","stream_id":0,"batch":{"steps":[{"stmt":{"sql_id":5}},{"stmt":{"sql":"SELECT 1"}}]}}}`
	if got := hranaSQL(t, s.Client(text(run))); strings.Join(got, "|") != "SELECT 1|(unread)" {
		t.Fatalf("before forwarding: %q", got)
	}
	s.Forwarded(store)
	if got := hranaSQL(t, s.Client(text(run))); strings.Join(got, "|") != "DELETE FROM t|SELECT 1" {
		t.Fatalf("after: %q", got)
	}
	if got := hranaSQL(t, s.Client(text(`{"type":"request","request_id":5,"request":{"type":"sequence","stream_id":0,"sql_id":5}}`))); strings.Join(got, "|") != "DELETE FROM t" {
		t.Fatalf("sequence: %q", got)
	}
	// sql and sql_id together: the id stays, so the request is unread.
	if got := hranaSQL(t, s.Client(text(`{"type":"request","request_id":6,"request":{"type":"execute","stream_id":0,"stmt":{"sql":"SELECT 1","sql_id":5}}}`))); strings.Join(got, "|") != "SELECT 1|(unread)" {
		t.Fatalf("both: %q", got)
	}
	s.Forwarded(s.Client(text(`{"type":"request","request_id":7,"request":{"type":"close_sql","sql_id":5}}`)))
	if got := hranaSQL(t, s.Client(text(run))); strings.Join(got, "|") != "SELECT 1|(unread)" {
		t.Fatalf("after close_sql: %q", got)
	}
	cur := hranaSQL(t, s.Client(text(`{"type":"request","request_id":8,"request":{"type":"open_cursor","stream_id":0,"cursor_id":1,"batch":{"steps":[{"stmt":{"sql":"UPDATE t SET a = 1 WHERE id = 2"}}]}}}`)))
	if strings.Join(cur, "|") != "UPDATE t SET a = 1 WHERE id = 2" {
		t.Fatalf("cursor: %q", cur)
	}
	st := s.Client(text(`{"type":"request","request_id":9,"request":{"type":"execute","stream_id":0,"stmt":{"sql":"DROP TABLE t"}}}`))
	replies, closeSocket := s.Blocked(st, "Blocked by Opfence: no.")
	if closeSocket || string(replies[0].Data) != `{"error":{"code":"OPFENCE_BLOCKED","message":"Blocked by Opfence: no."},"request_id":9,"type":"response_error"}` {
		t.Fatalf("%v %s", closeSocket, replies[0].Data)
	}
}

func TestHranaSessionFailsClosed(t *testing.T) {
	s := hranaSession()
	for _, m := range []WSMessage{
		{Binary: true, Data: []byte{8, 1}},
		text(`nope`), text(`{"type":"mystery"}`), text(`{"type":"request","request_id":1}`),
		text(`{"type":"request","request":{"type":"execute"}}`),
		text(`{"type":"request","request_id":1,"request":{"type":"mystery"}}`),
		text(`{"type":"request","request_id":1,"request":{"type":"store_sql","sql_id":1}}`),
		text(`{"type":"hello","jwt":"a","jwt":"b"}`),
	} {
		if st := s.Client(m); len(st.Ops) != 1 || st.Ops[0].Error == "" {
			t.Errorf("%s: %+v", m.Data, st)
		}
	}
	st := s.Client(text(`{"type":"mystery"}`))
	if _, closeSocket := s.Blocked(st, "no"); !closeSocket {
		t.Fatal("a message without an id left the socket open")
	}
}

// A connection keeps a bounded amount of stored SQL; what it does not keep
// is unread when it runs.
func TestHranaStoredSQLIsBounded(t *testing.T) {
	s := hranaSession()
	big := strings.Repeat("x", maxHranaStored/2+1)
	for id := range 3 {
		st := s.Client(text(fmt.Sprintf(`{"type":"request","request_id":%d,"request":{"type":"store_sql","sql_id":%d,"sql":"SELECT '%s'"}}`, id, id, big)))
		s.Forwarded(st)
	}
	if len(s.stored) != 1 || s.size > maxHranaStored {
		t.Fatalf("%d stored, %d bytes", len(s.stored), s.size)
	}
	if got := hranaSQL(t, s.Client(text(`{"type":"request","request_id":9,"request":{"type":"execute","stream_id":0,"stmt":{"sql_id":1}}}`))); got[len(got)-1] != "(unread)" {
		t.Fatalf("%q", got[0][:20])
	}
	// Closing frees its room.
	s.Forwarded(s.Client(text(`{"type":"request","request_id":10,"request":{"type":"close_sql","sql_id":0}}`)))
	if len(s.stored) != 0 || s.size != 0 {
		t.Fatalf("%d stored, %d bytes", len(s.stored), s.size)
	}
}
