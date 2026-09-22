from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('pharmacy', '0002_create_pharmacymembership'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pharmacybrand',
            name='owner',
            field=models.OneToOneField(limit_choices_to={'role': 'PHARMACY_OWNER'}, on_delete=django.db.models.deletion.PROTECT, related_name='owned_pharmacy_brand', to='auth_app.user'),
        ),
    ]
