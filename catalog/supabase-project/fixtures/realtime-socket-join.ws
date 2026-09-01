# description: Subscribe to changes of the orders table
GET /realtime/v1/websocket?apikey=opf_supabase-project_EXAMPLE&vsn=2.0.0 HTTP/1.1
Host: abcdefghijklmnopqrst.supabase.co
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==

>>> text
["1","1","realtime:orders-feed","phx_join",{"config":{"broadcast":{"ack":false,"self":false},"presence":{"key":"","enabled":false},"postgres_changes":[{"event":"*","schema":"public","table":"orders"}],"private":false},"access_token":"opf_supabase-project_EXAMPLE"}]
