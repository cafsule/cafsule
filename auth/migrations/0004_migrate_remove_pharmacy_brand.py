# Generated migration to migrate existing User.pharmacy_brand values into PharmacyMembership
from django.db import migrations, models
import django.db.models.deletion


def forwards(apps, schema_editor):
    User = apps.get_model('auth_app', 'User')
    PharmacyBrand = apps.get_model('pharmacy', 'PharmacyBrand')
    PharmacyMembership = apps.get_model('pharmacy', 'PharmacyMembership')

    MEMBERSHIP_ROLES = {
        'PHARMACY_MANAGER': 'PHARMACY_MANAGER',
        'PHARMACIST': 'PHARMACIST',
        'PHARMACY_STAFF': 'PHARMACY_STAFF',
    }

    for user in User.objects.all():
        # Support both older CharField and newer FK-backed column
        brand_id = getattr(user, 'pharmacy_brand_id', None)
        if not brand_id:
            # Try string field fallback
            raw_val = getattr(user, 'pharmacy_brand', None)
            brand_id = raw_val
        if not brand_id:
            continue
        try:
            brand = PharmacyBrand.objects.filter(id=brand_id).first()
        except Exception:
            brand = None
        if not brand:
            continue
        # Owners are already linked via PharmacyBrand.owner; skip creating membership
        if user.role == 'PHARMACY_OWNER':
            continue
        role = MEMBERSHIP_ROLES.get(user.role, 'PHARMACY_STAFF')
        status = 'APPROVED' if getattr(user, 'is_approved', False) else 'PENDING'
        approved_by = getattr(user, 'approved_by', None)
        # Avoid duplicating existing memberships
        existing = PharmacyMembership.objects.filter(user=user, pharmacy=brand).first()
        if existing:
            continue
        PharmacyMembership.objects.create(
            user=user,
            pharmacy=brand,
            role=role,
            status=status,
            approved_by=approved_by if approved_by else None,
            approved_at=getattr(user, 'approved_at', None) if getattr(user, 'is_approved', False) else None,
        )


def backwards(apps, schema_editor):
    # No-op: we can't safely restore the original pharmacy_brand values from memberships
    return


class Migration(migrations.Migration):

    dependencies = [
        ('auth_app', '0003_alter_user_pharmacy_brand'),
        ('pharmacy', '0002_create_pharmacymembership'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='user',
            name='pharmacy_brand',
        ),
    ]
