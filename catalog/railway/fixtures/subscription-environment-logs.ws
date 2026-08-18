# description: Follow logs of Railway environment over the subscription socket
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
{"id":"1","type":"subscribe","payload":{"query":"subscription EnvironmentLogs($environmentId: String!, $filter: String) { environmentLogs(environmentId: $environmentId, filter: $filter) { message severity timestamp tags { serviceId deploymentId } } }","variables":{"environmentId":"6c2b1f0e-8d4a-4e3b-9f1c-2a7d5e8b0c34","filter":""},"operationName":"EnvironmentLogs"}}
