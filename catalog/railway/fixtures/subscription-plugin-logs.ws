# description: Follow logs of Railway plugin over the subscription socket
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
{"id":"1","type":"subscribe","payload":{"query":"subscription PluginLogs($pluginId: String!, $environmentId: String!) { pluginLogs(pluginId: $pluginId, environmentId: $environmentId) { message timestamp } }","variables":{"pluginId":"a1b2c3d4-0000-4000-8000-000000000001","environmentId":"6c2b1f0e-8d4a-4e3b-9f1c-2a7d5e8b0c34"},"operationName":"PluginLogs"}}
