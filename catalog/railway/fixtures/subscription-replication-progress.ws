# description: Follow replication of Railway volume instance over the subscription socket
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
{"id":"1","type":"subscribe","payload":{"query":"subscription ReplicationProgress($volumeInstanceId: String!) { replicationProgress(volumeInstanceId: $volumeInstanceId) { percentComplete estimatedTimeRemainingMs error } }","variables":{"volumeInstanceId":"5e4d3c2b-1a09-4f8e-8d7c-6b5a49382716"},"operationName":"ReplicationProgress"}}
