# description: Follow your Railway notification deliveries over the subscription socket
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
{"id":"1","type":"subscribe","payload":{"query":"subscription NotificationDeliveryUpdated { notificationDeliveryUpdated { __typename } }","variables":{},"operationName":"NotificationDeliveryUpdated"}}
