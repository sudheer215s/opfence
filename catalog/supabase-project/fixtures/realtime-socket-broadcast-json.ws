# description: Broadcast over serializer 1.0.0, which sends it as JSON
GET /realtime/v1/websocket?apikey=opf_supabase-project_EXAMPLE&vsn=1.0.0 HTTP/1.1
Host: abcdefghijklmnopqrst.supabase.co
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> text
{"topic":"realtime:room-1","event":"phx_join","payload":{"config":{"broadcast":{"self":false}},"access_token":"opf_supabase-project_EXAMPLE"},"ref":"1","join_ref":"1"}
>>> text
{"topic":"realtime:room-1","event":"broadcast","payload":{"type":"broadcast","event":"refresh","payload":{"table":"orders"}},"ref":"2","join_ref":"1"}
