from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Feedback(models.Model):
    FEEDBACK_TYPES = (
        ('BUG_REPORT', 'Bug report'),
        ('FEATURE_REQUEST', 'Feature request'),
        ('GENERAL_FEEDBACK', 'General feedback'),
        ('UI_UX_FEEDBACK', 'UI/UX feedback'),
        ('PHARMACY_WORKFLOW_ISSUE', 'Pharmacy workflow issue'),
        ('MEDICINE_DATA_ISSUE', 'Medicine data issue'),
        ('OTHER', 'Other'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='feedback_submissions',
    )
    feedback_type = models.CharField(max_length=40, choices=FEEDBACK_TYPES)
    subject = models.CharField(max_length=180)
    message = models.TextField(max_length=5000)
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    email_sent = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    email_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.get_feedback_type_display()}: {self.subject}'