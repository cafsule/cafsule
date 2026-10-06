from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('medicine', '0007_global_medicine_identity_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='medicine',
            name='source_product_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text='Product identifier from the originating public catalog.',
                max_length=255,
            ),
        ),
        migrations.AddConstraint(
            model_name='medicine',
            constraint=models.UniqueConstraint(
                condition=models.Q(('source_product_id__gt', '')),
                fields=('source', 'source_product_id'),
                name='unique_medicine_source_product_id',
            ),
        ),
    ]