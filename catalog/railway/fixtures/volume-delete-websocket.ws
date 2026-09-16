# description: The PocketOS call sent over the subscription socket instead of HTTP
GET /graphql/v2 HTTP/1.1
Host: backboard.railway.com
Authorization: Bearer opf_railway_EXAMPLE
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Protocol: graphql-transport-ws

>>> text
{"type":"connection_init"}
>>> text
{"id":"2","type":"subscribe","payload":{"query":"mutation VolumeDelete($volumeId: String!) { volumeDelete(volumeId: $volumeId) }","variables":{"volumeId":"vol-pg-data"}}}
