from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(
        max_length=250,
        trim_whitespace=True,
    )

    destination = serializers.CharField(
        max_length=250,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        if attrs["start"].lower() == attrs["destination"].lower():
            raise serializers.ValidationError(
                "Start and destination cannot be the same."
            )

        return attrs
