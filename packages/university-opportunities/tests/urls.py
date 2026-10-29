from django.urls import include, path

urlpatterns = [path("", include("university.core.urls"))]
