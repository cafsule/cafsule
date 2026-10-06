from django.contrib import admin
from django.utils import timezone

from .models import Feedback
from .services import send_feedback_notification


@admin.action(description='Retry email delivery for selected feedback')
def retry_feedback_email(modeladmin, request, queryset):
    for feedback in queryset.filter(email_sent=False):
        try:
            send_feedback_notification(feedback)
        except Exception as exc:
            feedback.email_error = str(exc)[:500]
            feedback.save(update_fields=('email_error',))
        else:
            feedback.email_sent = True
            feedback.email_sent_at = timezone.now()
            feedback.email_error = ''
            feedback.save(update_fields=('email_sent', 'email_sent_at', 'email_error'))


@admin.register(Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ('subject', 'feedback_type', 'user', 'email_sent', 'created_at')
    list_filter = ('feedback_type', 'email_sent', 'created_at')
    search_fields = ('subject', 'message', 'user__email')
    readonly_fields = ('user', 'feedback_type', 'subject', 'message', 'rating', 'created_at', 'email_sent', 'email_sent_at', 'email_error')
    actions = (retry_feedback_email,)