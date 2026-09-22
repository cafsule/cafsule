# Generated manual migration for PharmacyMembership
from django.db import migrations, models
import django.db.models.deletion
import uuid

class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='PharmacyMembership',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)),
                ('role', models.CharField(max_length=30, choices=[('PHARMACY_MANAGER', 'Pharmacy Manager'), ('PHARMACIST', 'Pharmacist'), ('PHARMACY_STAFF', 'Pharmacy Staff')])),
                ('status', models.CharField(max_length=20, choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('SUSPENDED', 'Suspended')], default='PENDING')),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_pharmacy_memberships', to='auth_app.user')),
                ('pharmacy', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='pharmacy.pharmacybrand')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pharmacy_memberships', to='auth_app.user')),
            ],
            options={
                'db_table': 'pharmacy_membership',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='pharmacymembership',
            constraint=models.UniqueConstraint(fields=['user', 'pharmacy'], name='unique_user_pharmacy_membership'),
        ),
    ]
