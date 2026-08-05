# description: A transaction whose statements arrive one by one; the last drops a column
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
# BEGIN
"Q\x00\x00\x00\x0aBEGIN\x00"
>>> binary
# UPDATE
"P\x00\x00\x003\x00UPDATE accounts SET plan = $1 WHERE id = $2\x00\x00\x00"
"B\x00\x00\x00\x0c\x00\x00\x00\x00\x00\x00\x00\x00"
"D\x00\x00\x00\x06P\x00"
"E\x00\x00\x00\x09\x00\x00\x00\x00\x00"
"S\x00\x00\x00\x04"
>>> binary
# ALTER
"Q\x00\x00\x001ALTER TABLE accounts DROP COLUMN legacy_plan\x00"
