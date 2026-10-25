from django.urls import path

from university.__module__.api.v1 import views

app_name = "__module__"

urlpatterns = [
    path("items/", views.ItemListCreateView.as_view(), name="item-list"),
    path("items/<uuid:item_id>/", views.ItemDetailView.as_view(), name="item-detail"),
]
