# description: A sequence of statements run as a script
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
{"type":"request","request_id":1,"request":{"type":"sequence","stream_id":0,"sql":"CREATE TABLE t2 AS SELECT * FROM t; DROP TABLE t;"}}
