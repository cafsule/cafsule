import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Feedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('feedback_type', models.CharField(choices=[('BUG_REPORT', 'Bug report'), ('FEATURE_REQUEST', 'Feature request'), ('GENERAL_FEEDBACK', 'General feedback'), ('UI_UX_FEEDBACK', 'UI/UX feedback'), ('PHARMACY_WORKFLOW_ISSUE', 'Pharmacy workflow issue'), ('MEDICINE_DATA_ISSUE', 'Medicine data issue'), ('OTHER', 'Other')], max_length=40)),
                ('subject', models.CharField(max_length=180)),
                ('message', models.TextField(max_length=5000)),
                ('rating', models.PositiveSmallIntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(5)])),
                ('email_sent', models.BooleanField(default=False)),
                ('email_sent_at', models.DateTimeField(blank=True, null=True)),
                ('email_error', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='feedback_submissions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]