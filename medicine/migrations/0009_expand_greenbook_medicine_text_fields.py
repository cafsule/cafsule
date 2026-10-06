from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicine', '0008_medicine_source_product_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='medicine',
            name='generic_name',
            field=models.CharField(
                db_index=True,
                help_text='Generic/active ingredient name (e.g., Paracetamol)',
                max_length=400,
            ),
        ),
        migrations.AlterField(
            model_name='medicine',
            name='strength',
            field=models.CharField(
                db_index=True,
                help_text='Strength (e.g., 500mg, 250mg/5ml)',
                max_length=200,
            ),
        ),
    ]