"""
Medicine/Product Catalog Models

This module contains pharmacy-specific medicine/product definitions.
Each pharmacy manages their own medicines independently.
"""

import uuid
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class Medicine(models.Model):
    """
    Pharmacy-specific medicine/product definition.
    
    Each pharmacy maintains their own medicine catalog.
    This represents the medicine product details that a pharmacy carries.
    
    Example:
        Pharmacy: Cafsule Pharmacy Lagos
        Medicine: Paracetamol 500mg Tablet
    """
    
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
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Pharmacy ownership
    pharmacy = models.ForeignKey(
        'pharmacy.PharmacyBrand',
        on_delete=models.CASCADE,
        related_name='medicines',
        null=True,  # Temporarily nullable for migration
        blank=True,
        help_text="The pharmacy that owns/manages this medicine"
    )
    
    # Generic/active ingredient
    generic_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Generic/active ingredient name (e.g., Paracetamol)"
    )
    
    # Brand name (if applicable)
    brand_name = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Brand name (e.g., Panadol). Can be blank for generic-only."
    )
    
    # Strength
    strength = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Strength (e.g., 500mg, 250mg/5ml)"
    )
    
    # Dosage form
    dosage_form = models.CharField(
        max_length=30,
        choices=DOSAGE_FORM_CHOICES,
        db_index=True
    )
    
    # Route of administration
    route = models.CharField(
        max_length=30,
        choices=ROUTE_CHOICES,
        default='ORAL',
        db_index=True
    )
    
    # Manufacturer
    manufacturer = models.CharField(
        max_length=255,
        blank=True,
        help_text="Manufacturer name"
    )
    
    # Pack information
    pack_size = models.PositiveIntegerField(
        default=1,
        help_text="Quantity per pack (e.g., 10 tablets per strip)"
    )
    
    pack_size_unit = models.CharField(
        max_length=30,
        choices=PACK_SIZE_UNIT_CHOICES,
        default='UNIT'
    )
    
    # Description
    description = models.TextField(
        blank=True,
        help_text="Additional information about this medicine"
    )
    
    # Regulatory/reference information
    nafdac_registration = models.CharField(
        max_length=255,
        blank=True,
        help_text="NAFDAC registration number if applicable"
    )
    
    # Audit fields
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
        ordering = ['pharmacy', 'generic_name', 'brand_name', 'strength']
        indexes = [
            models.Index(fields=['pharmacy', 'generic_name', 'strength', 'dosage_form']),
            models.Index(fields=['pharmacy', 'brand_name']),
            models.Index(fields=['pharmacy', 'created_at']),
        ]
        unique_together = [
            ('pharmacy', 'generic_name', 'brand_name', 'strength', 'dosage_form'),
        ]
    
    def __str__(self):
        brand_part = f" ({self.brand_name})" if self.brand_name else ""
        return f"{self.generic_name} {self.strength}{brand_part} - {self.get_dosage_form_display()}"
    
    def get_display_name(self):
        """Get user-friendly name for this medicine"""
        name = self.generic_name
        if self.brand_name:
            name = f"{name} / {self.brand_name}"
        name += f" {self.strength} {self.get_dosage_form_display()}"
        return name
