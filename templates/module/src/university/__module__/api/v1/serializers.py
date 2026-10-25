from rest_framework import serializers

from university.__module__.models import Item
from university.core.api.serializers import StrictModelSerializer


class ItemSerializer(StrictModelSerializer):
    class Meta:
        model = Item
        fields = ("id", "title", "created_at")
        read_only_fields = ("id", "created_at")


class ItemCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
