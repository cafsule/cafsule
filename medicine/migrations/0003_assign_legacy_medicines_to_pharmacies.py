from django.db import migrations


def assign_legacy_medicines(apps, schema_editor):
    Medicine = apps.get_model('medicine', 'Medicine')
    PharmacyBrand = apps.get_model('pharmacy', 'PharmacyBrand')
    InventoryItem = apps.get_model('inventory', 'PharmacyInventoryItem')

    assigned = 0
    unresolved = 0

    for medicine in Medicine.objects.filter(pharmacy__isnull=True).iterator():
        pharmacy_ids = set(
            InventoryItem.objects.filter(medicine_id=medicine.pk)
            .values_list('pharmacy_id', flat=True)
            .distinct()
        )

        if not pharmacy_ids and medicine.created_by_id:
            pharmacy_ids = set(
                PharmacyBrand.objects.filter(owner_id=medicine.created_by_id)
                .values_list('pk', flat=True)
            )

        if len(pharmacy_ids) != 1:
            unresolved += 1
            continue

        pharmacy_id = next(iter(pharmacy_ids))
        duplicate_exists = Medicine.objects.filter(
            pharmacy_id=pharmacy_id,
            generic_name=medicine.generic_name,
            brand_name=medicine.brand_name,
            strength=medicine.strength,
            dosage_form=medicine.dosage_form,
        ).exclude(pk=medicine.pk).exists()

        if duplicate_exists:
            unresolved += 1
            continue

        Medicine.objects.filter(pk=medicine.pk).update(pharmacy_id=pharmacy_id)
        assigned += 1

    print(
        f'Legacy medicine assignment complete: {assigned} assigned, '
        f'{unresolved} unresolved.'
    )


def reverse_assignment(apps, schema_editor):
    # Do not clear ownership from medicines created after this migration.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('medicine', '0002_make_medicines_pharmacy_specific'),
        ('pharmacy', '0015_alter_pharmacybrand_brand_name'),
    ]

    operations = [
        migrations.RunPython(assign_legacy_medicines, reverse_assignment),
    ]