# description: Cancel a running query
GET /v2 HTTP/1.1
Host: ep-cool-darkness-123456.us-east-2.aws.neon.tech
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> binary
# CancelRequest
"\x00\x00\x00\x10\x04\xd2\x16.\x00\x00\x10\x92\x05\xf4*\x96"
