# description: Track a user in a channel
GET /realtime/v1/websocket?apikey=opf_supabase-project_EXAMPLE&vsn=2.0.0 HTTP/1.1
Host: abcdefghijklmnopqrst.supabase.co
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> text
["1","1","realtime:room-1","phx_join",{"config":{"broadcast":{"ack":false,"self":false},"presence":{"key":"","enabled":false},"postgres_changes":[],"private":false},"access_token":"opf_supabase-project_EXAMPLE"}]
>>> text
["1","4","realtime:room-1","presence",{"type":"presence","event":"track","payload":{"user":"agent","online_at":"2026-10-25T09:00:00Z"}}]
