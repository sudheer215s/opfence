# description: One query split across two socket messages
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
# the first half of a Query
"Q\x00\x00\x00\x17TRUN"
>>> binary
# the rest
"CATE audit_log\x00"
