"""Event names published by the notifications module (payloads carry ids only).

Real-time gateways (WebSockets, SSE) subscribe to ``notifications.notification.created``
to push badge updates; the payload never includes the rendered text.
"""

NOTIFICATION_CREATED = "notifications.notification.created"
