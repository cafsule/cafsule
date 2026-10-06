"""Global medicine catalog model.

The medicine catalog is platform-wide. Pharmacy inventory items reference a
medicine from this catalog.
"""

import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Medicine(models.Model):
    """Global catalog of medicines shared across the Cafsule platform."""

    DOSAGE_FORM_CHOICES = (
        ('TABLET', 'Tablet'),
        ('CAPSULE', 'Capsule'),
        ('SYRUP', 'Syrup'),
        ('INJECTION', 'Injection'),
        ('CREAM', 'Cream'),
        ('OINTMENT', 'Ointment'),
        ('LOTION', 'Lotion'),
        ('SUSPENSION', 'Suspension'),
        ('SOLUTION', 'Solution'),
        ('POWDER', 'Powder'),
        ('PATCH', 'Patch'),
        ('OTHER', 'Other'),
    )
    ROUTE_CHOICES = (
        ('ORAL', 'Oral'),
        ('INTRAVENOUS', 'Intravenous'),
        ('INTRAMUSCULAR', 'Intramuscular'),
        ('SUBCUTANEOUS', 'Subcutaneous'),
        ('TOPICAL', 'Topical'),
        ('RECTAL', 'Rectal'),
        ('INHALED', 'Inhaled'),
        ('INTRANASAL', 'Intranasal'),
        ('OTHER', 'Other'),
    )
    PACK_SIZE_UNIT_CHOICES = (
        ('UNIT', 'Unit'),
        ('STRIP', 'Strip'),
        ('PACK', 'Pack'),
        ('BOTTLE', 'Bottle'),
        ('VIAL', 'Vial'),
        ('TUBE', 'Tube'),
        ('JAR', 'Jar'),
        ('ML', 'Milliliter'),
        ('L', 'Liter'),
        ('G', 'Gram'),
        ('KG', 'Kilogram'),
        ('MG', 'Milligram'),
    )
    SOURCE_CHOICES = (
        ('ADMIN', 'Admin'),
        ('PUBLIC_DATABASE', 'Public Database'),
        ('PHARMACY', 'Pharmacy'),
    )
    VERIFICATION_STATUS_CHOICES = (
        ('UNVERIFIED', 'Unverified'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity_key = models.CharField(max_length=64, editable=False)

    created_by_pharmacy = models.ForeignKey(
        'pharmacy.PharmacyBrand',
        on_delete=models.SET_NULL,
        related_name='created_catalog_medicines',
        null=True,
        blank=True,
        help_text='Pharmacy that originally submitted this global medicine record.'
    )

    source = models.CharField(
        max_length=30,
        choices=SOURCE_CHOICES,
        default='ADMIN',
        db_index=True,
        help_text='Origin of the medicine record: admin, public database, or pharmacy submission.'
    )

    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='UNVERIFIED',
        db_index=True,
        help_text='Verification state for the global catalog record.'
    )

    generic_name = models.CharField(
        max_length=400,
        db_index=True,
        help_text='Generic/active ingredient name (e.g., Paracetamol)'
    )

    brand_name = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text='Brand name (e.g., Panadol). Can be blank for generic-only.'
    )

    strength = models.CharField(
        max_length=200,
        db_index=True,
        help_text='Strength (e.g., 500mg, 250mg/5ml)'
    )

    dosage_form = models.CharField(
        max_length=30,
        choices=DOSAGE_FORM_CHOICES,
        db_index=True
    )

    route = models.CharField(
        max_length=30,
        choices=ROUTE_CHOICES,
        default='ORAL',
        db_index=True
    )

    manufacturer = models.CharField(
        max_length=255,
        blank=True,
        help_text='Manufacturer name'
    )

    pack_size = models.PositiveIntegerField(
        default=1,
        help_text='Quantity per pack (e.g., 10 tablets per strip)'
    )

    pack_size_unit = models.CharField(
        max_length=30,
        choices=PACK_SIZE_UNIT_CHOICES,
        default='UNIT'
    )

    description = models.TextField(
        blank=True,
        help_text='Additional information about this medicine'
    )

    nafdac_registration = models.CharField(
        max_length=255,
        blank=True,
        help_text='NAFDAC registration number if applicable'
    )

    source_product_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text='Product identifier from the originating public catalog.'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_medicines'
    )

    class Meta:
        db_table = 'medicine'
        ordering = ['generic_name', 'brand_name', 'strength']
        indexes = [
            models.Index(fields=['generic_name', 'strength', 'dosage_form']),
            models.Index(fields=['brand_name']),
            models.Index(fields=['source', 'verification_status']),
            models.Index(fields=['created_by', 'created_at'])
        ]
        constraints = [
            models.UniqueConstraint(
                fields=('identity_key',),
                name='unique_medicine_identity_key',
            ),
            models.UniqueConstraint(
                fields=('source', 'source_product_id'),
                condition=models.Q(source_product_id__gt=''),
                name='unique_medicine_source_product_id',
            ),
        ]

    def __str__(self):
        brand_part = f" ({self.brand_name})" if self.brand_name else ""
        return f"{self.generic_name} {self.strength}{brand_part} - {self.get_dosage_form_display()}"

    def get_display_name(self):
        name = self.generic_name
        if self.brand_name:
            name = f"{name} / {self.brand_name}"
        name += f" {self.strength} {self.get_dosage_form_display()}"
        return name

    def save(self, *args, **kwargs):
        from .services import medicine_identity_key, normalize_medicine_fields

        identity_fields = normalize_medicine_fields({
            'generic_name': self.generic_name,
            'brand_name': self.brand_name,
            'strength': self.strength,
            'dosage_form': self.dosage_form,
            'route': self.route,
            'manufacturer': self.manufacturer,
            'pack_size': self.pack_size,
            'pack_size_unit': self.pack_size_unit,
        })
        for field, value in identity_fields.items():
            setattr(self, field, value)
        self.identity_key = medicine_identity_key(identity_fields)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and set(identity_fields).intersection(update_fields):
            kwargs['update_fields'] = set(update_fields) | {'identity_key'}
        super().save(*args, **kwargs)

    @classmethod
    def match_existing(cls, **fields):
        from .services import medicine_identity_key, normalize_medicine_fields

        normalized = normalize_medicine_fields(fields)
        return cls.objects.filter(
            identity_key=medicine_identity_key(normalized)
        ).first()

    @classmethod
    def get_or_create_global(cls, *, created_by=None, created_by_pharmacy=None, source=None, **fields):
        if source is None:
            source = (
                'ADMIN'
                if created_by and created_by.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}
                else 'PHARMACY'
            )
        from .services import create_or_get_global_medicine

        return create_or_get_global_medicine(
            fields=fields,
            source=source,
            created_by=created_by,
            created_by_pharmacy=created_by_pharmacy,
        )
