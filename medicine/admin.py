from django.contrib import admin
from .models import Medicine


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ('generic_name', 'brand_name', 'strength', 'dosage_form', 'route', 'pharmacy', 'created_at')
    list_filter = ('pharmacy', 'dosage_form', 'route', 'created_at')
    search_fields = ('generic_name', 'brand_name', 'strength', 'pharmacy__brand_name')
    readonly_fields = ('id', 'created_at', 'updated_at', 'created_by')
    fieldsets = (
        ('Pharmacy', {
            'fields': ('pharmacy',)
        }),
        ('Identification', {
            'fields': ('id', 'generic_name', 'brand_name', 'strength')
        }),
        ('Administration', {
            'fields': ('dosage_form', 'route', 'manufacturer')
        }),
        ('Packaging', {
            'fields': ('pack_size', 'pack_size_unit')
        }),
        ('Regulatory', {
            'fields': ('nafdac_registration',)
        }),
        ('Details', {
            'fields': ('description',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

