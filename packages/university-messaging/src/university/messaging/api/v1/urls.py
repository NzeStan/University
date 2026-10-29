from __future__ import annotations

from django.urls import path

from university.messaging.api.v1 import views

app_name = "messaging"

urlpatterns = [
    path("conversations/", views.ConversationListCreateView.as_view(), name="conversation-list"),
    path("conversations/<uuid:conversation_id>/", views.ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<uuid:conversation_id>/accept/", views.AcceptView.as_view(), name="conversation-accept"),
    path("conversations/<uuid:conversation_id>/decline/", views.DeclineView.as_view(), name="conversation-decline"),
    path("conversations/<uuid:conversation_id>/read/", views.ReadView.as_view(), name="conversation-read"),
    path("conversations/<uuid:conversation_id>/leave/", views.LeaveView.as_view(), name="conversation-leave"),
    path("conversations/<uuid:conversation_id>/participants/", views.ParticipantsView.as_view(), name="participants"),
    path("conversations/<uuid:conversation_id>/messages/", views.MessageListCreateView.as_view(), name="messages"),
    path("messages/<uuid:message_id>/", views.MessageDetailView.as_view(), name="message-detail"),
    path("unread/", views.UnreadView.as_view(), name="unread"),
    path("settings/", views.SettingsView.as_view(), name="settings"),
]
