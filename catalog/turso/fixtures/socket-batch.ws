# description: client.batch() with an insert and a limited delete
GET / HTTP/1.1
Host: app-db-acme.aws-us-east-1.turso.io
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Protocol: hrana2, hrana1

>>> text
{"type":"hello","jwt":"opf_turso_EXAMPLE"}
>>> text
{"type":"request","request_id":0,"request":{"type":"open_stream","stream_id":0}}
>>> text
{"type":"request","request_id":1,"request":{"type":"batch","stream_id":0,"batch":{"steps":[{"stmt":{"sql":"BEGIN","want_rows":false}},{"stmt":{"sql":"INSERT INTO events (kind) VALUES (?)","args":[{"type":"text","value":"login"}],"want_rows":false},"condition":{"type":"ok","step":0}},{"stmt":{"sql":"DELETE FROM sessions WHERE id = ?","args":[{"type":"text","value":"s1"}],"want_rows":false},"condition":{"type":"ok","step":1}},{"stmt":{"sql":"COMMIT","want_rows":false},"condition":{"type":"ok","step":2}}]}}}
