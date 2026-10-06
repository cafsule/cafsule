import logging

from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.response import Response

from .serializers import FeedbackSerializer
from .services import send_feedback_notification

logger = logging.getLogger(__name__)


class FeedbackCreateView(generics.CreateAPIView):
    serializer_class = FeedbackSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save(user=request.user)

        try:
            send_feedback_notification(feedback)
        except Exception as exc:
            logger.error('Feedback email delivery failed for feedback id=%s: %s', feedback.pk, exc)
            feedback.email_error = str(exc)[:500]
            feedback.save(update_fields=('email_error',))
            return Response(
                {'detail': 'Your feedback was saved, but email delivery failed. Please try again later.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        feedback.email_sent = True
        feedback.email_sent_at = timezone.now()
        feedback.email_error = ''
        feedback.save(update_fields=('email_sent', 'email_sent_at', 'email_error'))
        return Response(serializer.data, status=status.HTTP_201_CREATED)