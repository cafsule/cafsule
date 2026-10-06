from django.db import migrations


def _normalize(value):
    return (value or '').strip().lower()


def populate_global_catalog_metadata(apps, schema_editor):
    Medicine = apps.get_model('medicine', 'Medicine')
    InventoryItem = apps.get_model('inventory', 'PharmacyInventoryItem')
    canonical_by_key = {}

    for medicine in Medicine.objects.order_by('created_at').iterator():
        key = (
            _normalize(medicine.generic_name),
            _normalize(medicine.brand_name),
            _normalize(medicine.strength),
            _normalize(medicine.dosage_form),
            _normalize(medicine.route or 'ORAL'),
            _normalize(medicine.manufacturer),
        )

        existing_pk = canonical_by_key.get(key)
        if existing_pk is None:
            canonical_by_key[key] = medicine.pk
            medicine.created_by_pharmacy_id = medicine.pharmacy_id or medicine.created_by_pharmacy_id
            medicine.source = 'PHARMACY' if medicine.pharmacy_id or medicine.created_by_pharmacy_id else 'ADMIN'
            medicine.verification_status = 'UNVERIFIED'
            medicine.save(update_fields=['created_by_pharmacy', 'source', 'verification_status'])
            continue

        canonical = Medicine.objects.get(pk=existing_pk)
        InventoryItem.objects.filter(medicine_id=medicine.pk).update(medicine_id=canonical.pk)

        if canonical.created_by_pharmacy_id is None:
            canonical.created_by_pharmacy_id = medicine.pharmacy_id or medicine.created_by_pharmacy_id
        if canonical.created_by_id is None and medicine.created_by_id:
            canonical.created_by_id = medicine.created_by_id
        if medicine.pharmacy_id or medicine.created_by_pharmacy_id:
            canonical.source = 'PHARMACY'
        canonical.verification_status = canonical.verification_status or 'UNVERIFIED'
        canonical.save(update_fields=['created_by_pharmacy', 'created_by', 'source', 'verification_status'])
        medicine.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('medicine', '0004_alter_medicine_options_and_more'),
    ]

    operations = [
        migrations.RunPython(populate_global_catalog_metadata, migrations.RunPython.noop),
    ]