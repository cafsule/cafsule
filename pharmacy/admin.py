from django.contrib import admin
from django import forms

from .models import PharmacyBrand, PharmacyBrandImage, PharmacyMembership, PharmacyVerificationDocument, PharmacyVerificationHistory


class PharmacyBrandForm(forms.ModelForm):
    class Meta:
        model = PharmacyBrand
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        # Sanitize initial values for UUID FK fields to avoid ValidationError
        initial = kwargs.get("initial") or {}
        import uuid as _uuid
        for key in ("owner", "verified_by"):
            val = initial.get(key)
            if val:
                try:
                    _uuid.UUID(str(val))
                except Exception:
                    initial.pop(key, None)
        kwargs["initial"] = initial
        super().__init__(*args, **kwargs)


@admin.register(PharmacyBrand)
class PharmacyBrandAdmin(admin.ModelAdmin):
    list_display = [
        'brand_name',
        'legal_name',
        'owner',
        'verification_status',
        'city',
        'state',
        'cac_registration_number',
        'pcn_license_number',
        'nafdac_registration_number',
        'verified_by',
        'verified_at',
        'created_at',
    ]
    list_filter = ['verification_status', 'state', 'city', 'pharmacy_type', 'created_at']
    search_fields = [
        'brand_name',
        'legal_name',
        'business_email',
        'cac_registration_number',
        'pcn_premises_registration_number',
        'pcn_license_number',
        'nafdac_registration_number',
        'owner__email',
    ]
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at', 'updated_at', 'verified_at']
    raw_id_fields = ('owner', 'verified_by')
    form = PharmacyBrandForm

    def get_changeform_initial_data(self, request):
        """Sanitize initial GET params: ignore non-UUID values for UUID PK fields.

        This prevents ValidationError when the admin receives integer IDs
        (e.g., ?owner=2) while the `User` PK is a UUID.
        """
        initial = super().get_changeform_initial_data(request)
        import uuid as _uuid

        for key in ('owner', 'verified_by'):
            val = request.GET.get(key)
            if val:
                try:
                    _uuid.UUID(val)
                except Exception:
                    # Drop invalid UUID initial value
                    initial.pop(key, None)
        return initial


@admin.register(PharmacyBrandImage)
class PharmacyBrandImageAdmin(admin.ModelAdmin):
    list_display = ['brand', 'image_type', 'is_primary', 'uploaded_at']
    list_filter = ['image_type', 'is_primary', 'uploaded_at']
    search_fields = ['brand__brand_name', 'brand__legal_name', 'caption']


@admin.register(PharmacyMembership)
class PharmacyMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'pharmacy', 'role', 'status', 'approved_by', 'created_at')
    list_filter = ('status', 'role')
    search_fields = ('user__email', 'pharmacy__brand_name')
    readonly_fields = ('approved_at', 'created_at', 'updated_at')


@admin.register(PharmacyVerificationDocument)
class PharmacyVerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ('brand', 'document_type', 'review_status', 'uploaded_at')
    list_filter = ('document_type', 'review_status')
    search_fields = ('brand__brand_name', 'brand__legal_name')
    raw_id_fields = ('brand',)


@admin.register(PharmacyVerificationHistory)
class PharmacyVerificationHistoryAdmin(admin.ModelAdmin):
    list_display = ('pharmacy_brand', 'action', 'previous_status', 'new_status', 'performed_by', 'created_at')
    list_filter = ('action', 'previous_status', 'new_status')
    search_fields = ('pharmacy_brand__brand_name', 'performed_by__email', 'reason')
    readonly_fields = ('pharmacy_brand', 'previous_status', 'new_status', 'action', 'performed_by', 'reason', 'notes', 'created_at')
