# description: SQL stored on the connection, then run by its id
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
{"type":"request","request_id":1,"request":{"type":"store_sql","sql_id":7,"sql":"DELETE FROM orders"}}
>>> text
{"type":"request","request_id":2,"request":{"type":"execute","stream_id":0,"stmt":{"sql_id":7,"want_rows":false}}}
