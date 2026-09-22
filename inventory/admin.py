from django.contrib import admin
from .models import (
    PharmacyInventoryItem, InventoryBatch, CustomerReturn,
    InventoryHold, StockReconciliation
)


class InventoryBatchInline(admin.TabularInline):
    model = InventoryBatch
    extra = 1
    readonly_fields = ('id', 'created_at', 'updated_at')
    fields = ('batch_number', 'quantity', 'expiry_date', 'cost_per_unit', 'created_at')


@admin.register(PharmacyInventoryItem)
class PharmacyInventoryItemAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'pharmacy', 'selling_price', 'status', 'is_published', 'created_at')
    list_filter = ('status', 'is_published', 'pharmacy', 'created_at')
    search_fields = ('pharmacy__brand_name', 'medicine__generic_name', 'medicine__brand_name')
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'created_by', 'published_by',
        'published_at', 'unpublished_by', 'unpublished_at', 'is_published',
        'total_quantity'
    )
    inlines = [InventoryBatchInline]
    fieldsets = (
        ('Inventory', {
            'fields': ('id', 'pharmacy', 'medicine')
        }),
        ('Pricing & Status', {
            'fields': ('selling_price', 'status')
        }),
        ('Publication', {
            'fields': (
                'is_published', 'published_at', 'published_by',
                'unpublished_at', 'unpublished_by'
            )
        }),
        ('Stock Summary', {
            'fields': ('total_quantity',),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(InventoryBatch)
class InventoryBatchAdmin(admin.ModelAdmin):
    list_display = ('inventory_item', 'batch_number', 'quantity', 'expiry_date', 'is_expired')
    list_filter = ('expiry_date', 'inventory_item__pharmacy', 'created_at')
    search_fields = ('batch_number', 'inventory_item__medicine__generic_name')
    readonly_fields = ('id', 'created_at', 'updated_at', 'days_until_expiry')
    fieldsets = (
        ('Batch Info', {
            'fields': ('id', 'inventory_item', 'batch_number')
        }),
        ('Stock', {
            'fields': ('quantity', 'expiry_date', 'days_until_expiry')
        }),
        ('Cost', {
            'fields': ('cost_per_unit',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(CustomerReturn)
class CustomerReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'pharmacy', 'sale', 'quantity_returned', 'condition', 'status', 'created_at')
    list_filter = ('status', 'condition', 'pharmacy', 'created_at')
    search_fields = ('sale__sale_number', 'id')
    readonly_fields = (
        'id', 'pharmacy', 'sale', 'sale_item', 'inventory_item', 'batch',
        'initiated_by', 'reviewed_at', 'created_at'
    )
    fieldsets = (
        ('Sale Info', {
            'fields': ('id', 'pharmacy', 'sale', 'sale_item', 'inventory_item', 'batch')
        }),
        ('Return Details', {
            'fields': ('quantity_returned', 'condition', 'reason', 'notes')
        }),
        ('Status & Approval', {
            'fields': ('status', 'initiated_by', 'reviewed_by', 'reviewed_at')
        }),
        ('Audit', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(InventoryHold)
class InventoryHoldAdmin(admin.ModelAdmin):
    list_display = ('id', 'pharmacy', 'batch', 'quantity', 'reason', 'status', 'created_at')
    list_filter = ('status', 'pharmacy', 'created_at')
    search_fields = ('id', 'batch__batch_number', 'reason')
    readonly_fields = (
        'id', 'batch', 'pharmacy', 'inventory_item',
        'initiated_by', 'resolved_at', 'created_at'
    )
    fieldsets = (
        ('Hold Info', {
            'fields': ('id', 'batch', 'pharmacy', 'inventory_item')
        }),
        ('Details', {
            'fields': ('quantity', 'reason', 'notes', 'reference_type', 'reference_id')
        }),
        ('Status & Resolution', {
            'fields': ('status', 'resolution', 'initiated_by', 'resolved_by', 'resolved_at')
        }),
        ('Audit', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


@admin.register(StockReconciliation)
class StockReconciliationAdmin(admin.ModelAdmin):
    list_display = ('id', 'pharmacy', 'batch', 'expected_quantity', 'counted_quantity', 'status', 'created_at')
    list_filter = ('status', 'discrepancy_type', 'pharmacy', 'created_at')
    search_fields = ('id', 'batch__batch_number')
    readonly_fields = (
        'id', 'pharmacy', 'inventory_item', 'batch',
        'expected_quantity', 'expected_quantity_captured_at',
        'difference', 'discrepancy_type', 'counted_by', 'approved_by',
        'reconciled_by', 'created_at', 'counted_at', 'approved_at',
        'reconciled_at', 'resulting_movement_id'
    )
    fieldsets = (
        ('Reconciliation Info', {
            'fields': ('id', 'pharmacy', 'inventory_item', 'batch')
        }),
        ('Expected Qty (Captured at Start)', {
            'fields': ('expected_quantity', 'expected_quantity_captured_at')
        }),
        ('Physical Count', {
            'fields': ('counted_quantity', 'counted_at', 'counted_by', 'difference', 'discrepancy_type')
        }),
        ('Discrepancy Analysis', {
            'fields': ('reason_for_discrepancy', 'notes')
        }),
        ('Approval', {
            'fields': ('approved_by', 'approved_at', 'approval_notes')
        }),
        ('Reconciliation', {
            'fields': ('reconciled_by', 'reconciled_at', 'resulting_movement_id', 'status')
        }),
        ('Audit', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
