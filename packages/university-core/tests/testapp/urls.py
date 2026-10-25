from django.urls import path

from tests.testapp import views

app_name = "testapp"

urlpatterns = [
    path("orders/", views.OrderView.as_view(), name="orders"),
    path("widgets/", views.WidgetView.as_view(), name="widgets"),
    path("public/", views.PublicView.as_view(), name="public"),
    path("boom/", views.BoomView.as_view(), name="boom"),
    path("webhook/", views.TestWebhookView.as_view(), name="webhook"),
]
