# description: Follow build logs of Railway deployment over the subscription socket
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
{"id":"1","type":"subscribe","payload":{"query":"subscription BuildLogs($deploymentId: String!, $limit: Int) { buildLogs(deploymentId: $deploymentId, limit: $limit) { message severity timestamp } }","variables":{"deploymentId":"d0f5c6e2-1b7a-4c1e-9a3e-5f2b8c7d6e41","limit":500},"operationName":"BuildLogs"}}
