import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicine', '0005_medicine_unique_global_medicine_identity'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='medicine',
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('generic_name')),
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('brand_name')),
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('strength')),
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('dosage_form')),
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('route')),
                django.db.models.functions.text.Lower(django.db.models.functions.text.Trim('manufacturer')),
                name='unique_global_medicine_identity',
            ),
        ),
    ]