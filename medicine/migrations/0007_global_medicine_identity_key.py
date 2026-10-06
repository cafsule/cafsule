import hashlib
import json
import re

from django.db import migrations, models


def _collapse_whitespace(value):
    return ' '.join((value or '').split())


def _identity_key(medicine):
    strength = _collapse_whitespace(medicine.strength)
    strength = re.sub(r'(?<=\d)\s+(?=[A-Za-z%]|\u00b5|\u03bc)', '', strength)
    strength = re.sub(r'\s*/\s*', '/', strength)
    identity = (
        _collapse_whitespace(medicine.generic_name).casefold(),
        _collapse_whitespace(medicine.brand_name).casefold(),
        strength.casefold(),
        _collapse_whitespace(medicine.dosage_form).upper().casefold(),
        _collapse_whitespace(medicine.route or 'ORAL').upper().casefold(),
        _collapse_whitespace(medicine.manufacturer).casefold(),
        int(medicine.pack_size or 1),
        _collapse_whitespace(medicine.pack_size_unit or 'UNIT').upper().casefold(),
    )
    encoded = json.dumps(identity, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def populate_identity_keys(apps, schema_editor):
    Medicine = apps.get_model('medicine', 'Medicine')
    alias = schema_editor.connection.alias
    records = list(Medicine.objects.using(alias).order_by('pk').iterator())

    provenance_conflicts = [
        str(medicine.pk)
        for medicine in records
        if medicine.pharmacy_id != medicine.created_by_pharmacy_id
    ]
    if provenance_conflicts:
        raise RuntimeError(
            'Cannot remove legacy Medicine.pharmacy: pharmacy and '
            'created_by_pharmacy differ or only one is set for medicine IDs '
            + ', '.join(provenance_conflicts)
        )

    keys_to_ids = {}
    for medicine in records:
        key = _identity_key(medicine)
        keys_to_ids.setdefault(key, []).append(str(medicine.pk))
    conflicts = [ids for ids in keys_to_ids.values() if len(ids) > 1]
    if conflicts:
        details = '; '.join(', '.join(ids) for ids in conflicts)
        raise RuntimeError(
            'Cannot add unique global medicine identity constraint; '
            'conflicting Medicine IDs: ' + details
        )

    for medicine in records:
        Medicine.objects.using(alias).filter(pk=medicine.pk).update(
            identity_key=_identity_key(medicine)
        )


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ('medicine', '0006_medicine_unique_global_medicine_identity'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicine',
            name='identity_key',
            field=models.CharField(blank=True, editable=False, max_length=64, null=True),
        ),
        migrations.RunPython(populate_identity_keys, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='medicine',
            name='unique_global_medicine_identity',
        ),
        migrations.RemoveField(
            model_name='medicine',
            name='pharmacy',
        ),
        migrations.AlterField(
            model_name='medicine',
            name='identity_key',
            field=models.CharField(editable=False, max_length=64),
        ),
        migrations.AddConstraint(
            model_name='medicine',
            constraint=models.UniqueConstraint(
                fields=('identity_key',),
                name='unique_medicine_identity_key',
            ),
        ),
    ]