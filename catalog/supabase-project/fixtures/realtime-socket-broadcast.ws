# description: Broadcast a cursor position (serializer 2.0.0 sends it as a binary frame)
GET /realtime/v1/websocket?apikey=opf_supabase-project_EXAMPLE&vsn=2.0.0 HTTP/1.1
Host: abcdefghijklmnopqrst.supabase.co
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> text
["1","1","realtime:room-1","phx_join",{"config":{"broadcast":{"ack":false,"self":false},"presence":{"key":"","enabled":false},"postgres_changes":[],"private":false},"access_token":"opf_supabase-project_EXAMPLE"}]
>>> binary
# kind 3; lengths of the join ref, ref, topic, event and metadata; JSON payload
"\x03\x01\x01\x0f\x0a\x00\x0112realtime:room-1cursor-pos"
"{\"x\": 120, \"y\": 44}"
