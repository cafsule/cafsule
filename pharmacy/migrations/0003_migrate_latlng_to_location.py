from django.db import migrations, models


def migrate_latlng_to_location(apps, schema_editor):
    """Copy existing latitude/longitude into the temporary text field.

    Store as plain text "<lng> <lat>" so this migration runs on SQLite.
    """
    PharmacyBrand = apps.get_model('pharmacy', 'PharmacyBrand')

    for obj in PharmacyBrand.objects.all().iterator():
        lat = getattr(obj, 'latitude', None)
        lng = getattr(obj, 'longitude', None)
        if lat is None or lng is None:
            continue
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            continue
        obj.location_tmp = f"{lng_f} {lat_f}"
        obj.save(update_fields=['location_tmp'])


class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0002_remove_pharmacybrand_location_pharmacybrand_latitude_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='pharmacybrand',
            name='location_tmp',
            field=models.TextField(null=True, blank=True),
        ),
        migrations.RunPython(migrate_latlng_to_location, migrations.RunPython.noop),
    ]
