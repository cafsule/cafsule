from django.contrib import admin
from .models import Medicine


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ('generic_name', 'brand_name', 'strength', 'dosage_form', 'route', 'source', 'created_at')
    list_filter = ('source', 'dosage_form', 'route', 'created_at')
    search_fields = ('generic_name', 'brand_name', 'strength', 'created_by_pharmacy__brand_name')
    readonly_fields = ('id', 'identity_key', 'created_at', 'updated_at', 'created_by', 'created_by_pharmacy', 'source')
    fieldsets = (
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
            'fields': ('source', 'verification_status', 'created_by', 'created_by_pharmacy', 'created_at', 'updated_at', 'identity_key'),
            'classes': ('collapse',)
        }),
    )

