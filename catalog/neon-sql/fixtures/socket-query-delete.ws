# description: Pool.query('DELETE FROM sessions WHERE expires_at < $1', [now])
GET /v2 HTTP/1.1
Host: ep-cool-darkness-123456.us-east-2.aws.neon.tech
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> binary
# startup and password, pipelined (pipelineConnect: password)
"\x00\x00\x00@\x00\x03\x00\x00user\x00neondb_owner\x00database\x00neondb\x00client_encoding\x00UTF8\x00\x00"
"p\x00\x00\x00\x10npg_EXAMPLE\x00"
>>> binary
# extended query: Parse, Bind, Describe, Execute, Sync
"P\x00\x00\x002\x00DELETE FROM sessions WHERE expires_at < $1\x00\x00\x00"
"B\x00\x00\x00\x0c\x00\x00\x00\x00\x00\x00\x00\x00"
"D\x00\x00\x00\x06P\x00"
"E\x00\x00\x00\x09\x00\x00\x00\x00\x00"
"S\x00\x00\x00\x04"
