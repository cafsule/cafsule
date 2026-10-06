from rest_framework import serializers

from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ('id', 'feedback_type', 'subject', 'message', 'rating', 'created_at')
        read_only_fields = ('id', 'created_at')

    def validate_subject(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError('Subject must be at least 3 characters long.')
        return value

    def validate_message(self, value):
        value = value.strip()
        if len(value) < 10:
            raise serializers.ValidationError('Please provide at least 10 characters of detail.')
        return value