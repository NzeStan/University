"""Events published by messaging. Ids only: message text never leaves this module in an event.

``recipient_ids`` lists the participants to tell (active, not muted, not the sender); a request is
announced separately so the recipient can choose to accept it.
"""

#: {"message_id", "conversation_id", "sender_id", "recipient_ids"}
MESSAGE_SENT = "messaging.message.sent"
#: {"conversation_id", "sender_id", "recipient_id"}: someone new wants to message you.
REQUEST_RECEIVED = "messaging.request.received"
