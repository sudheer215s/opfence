# Writes neon-sql's socket fixtures: Postgres frontend messages as node-postgres
# (through @neondatabase/serverless) sends them, as Go string literals.
# Run from the repo root: python3 -I pgfix.py catalog/neon-sql/fixtures
# (socket-connect.http there is written by hand; FunctionCall and TLS inside
# the socket are tested in internal/decode instead).
import struct, sys, os
out = sys.argv[1]
HOST = "ep-cool-darkness-123456.us-east-2.aws.neon.tech"
def cstr(s): return s.encode() + b"\0"
def startup(user="neondb_owner", db="neondb"):
    params = b"".join(cstr(k)+cstr(v) for k,v in [("user",user),("database",db),("client_encoding","UTF8")]) + b"\0"
    return struct.pack(">II", 8+len(params), 3<<16) + params
def msg(t, body): return t + struct.pack(">I", 4+len(body)) + body
def password(p="npg_EXAMPLE"): return msg(b"p", cstr(p))
def query(sql): return msg(b"Q", cstr(sql))
def parse(sql, name=""): return msg(b"P", cstr(name)+cstr(sql)+struct.pack(">H",0))
def bind(): return msg(b"B", cstr("")+cstr("")+struct.pack(">HHH",0,0,0))
def describe(): return msg(b"D", b"P"+cstr(""))
def execute(): return msg(b"E", cstr("")+struct.pack(">I",0))
def sync(): return msg(b"S", b"")
def cancel(): return struct.pack(">IIII", 16, 80877102, 4242, 99887766)
def sslreq(): return struct.pack(">II", 8, 80877103)
def fcall(): return msg(b"F", struct.pack(">IHHI",1234,0,0,0)+struct.pack(">H",0))
def lit(b):
    s = '"'
    for c in b:
        ch = chr(c)
        if ch == '"' : s += '\\"'
        elif ch == '\\': s += '\\\\'
        elif 32 <= c < 127: s += ch
        else: s += '\\x%02x' % c
    return s + '"'
HEAD = f"""GET /v2 HTTP/1.1
Host: {HOST}
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

"""
def write(name, desc, messages):
    with open(os.path.join(out, name), "w") as f:
        f.write(f"# description: {desc}\n" + HEAD)
        for comment, parts in messages:
            f.write(">>> binary\n")
            f.write(f"# {comment}\n")
            for p in parts:
                f.write(lit(p) + "\n")
connect = ("startup and password, pipelined (pipelineConnect: password)", [startup(), password()])
write("socket-query-read.ws", "Pool.query('SELECT * FROM users WHERE id = 1')", [connect, ("simple query", [query("SELECT * FROM users WHERE id = 1")])])
write("socket-query-drop.ws", "A migration run with Pool drops a table", [connect, ("simple query", [query("DROP TABLE users")])])
write("socket-query-delete.ws", "Pool.query('DELETE FROM sessions WHERE expires_at < $1', [now])", [connect, ("extended query: Parse, Bind, Describe, Execute, Sync", [parse("DELETE FROM sessions WHERE expires_at < $1"), bind(), describe(), execute(), sync()])])
write("socket-query-every-row.ws", "A DELETE with no WHERE, through the extended protocol", [connect, ("extended query", [parse("DELETE FROM orders"), bind(), describe(), execute(), sync()])])
write("socket-transaction.ws", "A transaction whose statements arrive one by one; the last drops a column", [connect, ("BEGIN", [query("BEGIN")]), ("UPDATE", [parse("UPDATE accounts SET plan = $1 WHERE id = $2"), bind(), describe(), execute(), sync()]), ("ALTER", [query("ALTER TABLE accounts DROP COLUMN legacy_plan")])])
write("socket-query-split.ws", "One query split across two socket messages", [connect, ("the first half of a Query", [query("TRUNCATE audit_log")[:9]]), ("the rest", [query("TRUNCATE audit_log")[9:]])])
write("socket-cancel.ws", "Cancel a running query", [("CancelRequest", [cancel()])])
