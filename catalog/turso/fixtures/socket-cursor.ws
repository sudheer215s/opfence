# description: A cursor over a batch (Hrana 3) that updates rows
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
{"type":"request","request_id":1,"request":{"type":"open_cursor","stream_id":0,"cursor_id":0,"batch":{"steps":[{"stmt":{"sql":"UPDATE users SET plan = ? WHERE id = ?","args":[{"type":"text","value":"pro"},{"type":"integer","value":"3"}],"want_rows":false}}]}}}
