from __future__ import annotations

from django.urls import path

from university.notifications.api.v1 import views

app_name = "notifications"

N = "notifications/<uuid:notification_id>/"

urlpatterns = [
    path("notifications/", views.NotificationListView.as_view(), name="notification-list"),
    path("notifications/counts/", views.NotificationCountsView.as_view(), name="notification-counts"),
    path("notifications/read-all/", views.ReadAllView.as_view(), name="notification-read-all"),
    path("notifications/seen/", views.SeenView.as_view(), name="notification-seen"),
    path("notifications/categories/", views.CategoryListView.as_view(), name="notification-categories"),
    path("notifications/devices/", views.DeviceListView.as_view(), name="device-list"),
    path("notifications/devices/unregister/", views.DeviceUnregisterView.as_view(), name="device-unregister"),
    path("notifications/devices/<uuid:device_id>/", views.DeviceDetailView.as_view(), name="device-detail"),
    path(N, views.NotificationDetailView.as_view(), name="notification-detail"),
    path(f"{N}read/", views.MarkReadView.as_view(), name="notification-read"),
    path(f"{N}unread/", views.MarkUnreadView.as_view(), name="notification-unread"),
]
