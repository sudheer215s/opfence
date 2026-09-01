# description: Join a channel with serializer 1.0.0
GET /realtime/v1/websocket?apikey=opf_supabase-project_EXAMPLE&vsn=1.0.0 HTTP/1.1
Host: abcdefghijklmnopqrst.supabase.co
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
>>> text
{"topic":"realtime:room-1","event":"phx_join","payload":{"config":{"broadcast":{"self":true},"presence":{"key":"u1"}},"access_token":"opf_supabase-project_EXAMPLE"},"ref":"1","join_ref":"1"}
