"""
Django Admin configuration for Sales models.
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import Sale, SaleItem, SaleItemBatchAllocation, Customer, StockMovement


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Admin for Customer model"""
    
    list_display = (
        'get_display_name', 'customer_type', 'phone_number', 'email',
        'pharmacy', 'created_at'
    )
    list_filter = ('customer_type', 'pharmacy', 'created_at')
    search_fields = ('first_name', 'last_name', 'phone_number', 'email')
    readonly_fields = ('id', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('id', 'first_name', 'last_name', 'phone_number', 'email')
        }),
        ('Customer Type', {
            'fields': ('customer_type',)
        }),
        ('Pharmacy', {
            'fields': ('pharmacy',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class SaleItemInline(admin.TabularInline):
    """Inline admin for SaleItems within a Sale (read-only)"""
    
    model = SaleItem
    readonly_fields = (
        'id', 'inventory_item', 'quantity', 'unit_price',
        'line_discount', 'line_total', 'created_at'
    )
    fields = (
        'inventory_item', 'quantity', 'unit_price',
        'line_discount', 'line_total'
    )
    can_delete = False
    extra = 0
    
    def has_add_permission(self, request, obj=None):
        """Items must be added via API using the add_item action"""
        return False


class SaleItemBatchAllocationInline(admin.TabularInline):
    """Inline admin for batch allocations within a SaleItem"""
    
    model = SaleItemBatchAllocation
    readonly_fields = ('id', 'batch', 'quantity', 'created_at')
    fields = ('batch', 'quantity')
    can_delete = False
    extra = 0


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    """Admin for SaleItem model (read-only viewing)"""
    
    list_display = (
        'id', 'get_sale_receipt', 'get_medicine_name', 'quantity',
        'unit_price', 'line_total', 'created_at'
    )
    list_filter = ('created_at', 'inventory_item__pharmacy')
    readonly_fields = (
        'id', 'sale', 'inventory_item', 'quantity', 'unit_price',
        'line_discount', 'line_total', 'created_at'
    )
    inlines = [SaleItemBatchAllocationInline]
    can_delete = False
    
    fieldsets = (
        ('Sale Reference', {
            'fields': ('id', 'sale')
        }),
        ('Product', {
            'fields': ('inventory_item',)
        }),
        ('Quantity & Pricing', {
            'fields': ('quantity', 'unit_price', 'line_discount', 'line_total')
        }),
        ('Audit', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def get_sale_receipt(self, obj):
        return obj.sale.receipt_number
    get_sale_receipt.short_description = 'Receipt'
    
    def get_medicine_name(self, obj):
        return obj.inventory_item.medicine.get_display_name()
    get_medicine_name.short_description = 'Medicine'
    
    def has_add_permission(self, request):
        """Items must be added via API using the add_item action"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Never allow deletion - immutable records"""
        return False


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    """Admin for Sale model"""
    
    list_display = (
        'receipt_number', 'pharmacy', 'get_customer_display', 'get_status_badge',
        'total', 'payment_status', 'created_at', 'completed_at'
    )
    list_filter = ('status', 'payment_status', 'pharmacy', 'created_at')
    search_fields = ('receipt_number', 'pharmacy__brand_name')
    readonly_fields = (
        'id', 'receipt_number', 'pharmacy', 'created_at', 'created_by',
        'completed_at', 'sold_by', 'voided_at', 'voided_by'
    )
    inlines = [SaleItemInline]
    
    fieldsets = (
        ('Sale Identification', {
            'fields': ('id', 'receipt_number', 'pharmacy')
        }),
        ('Customer', {
            'fields': ('customer',)
        }),
        ('Status', {
            'fields': ('status',),
            'description': 'Sale status: DRAFT (not yet completed), COMPLETED (stock consumed), VOIDED (reversed)'
        }),
        ('Financial', {
            'fields': ('subtotal', 'discount', 'tax', 'total')
        }),
        ('Payment', {
            'fields': ('payment_status', 'payment_method', 'amount_paid')
        }),
        ('Notes', {
            'fields': ('notes',)
        }),
        ('Creation', {
            'fields': ('created_at', 'created_by'),
            'classes': ('collapse',)
        }),
        ('Completion', {
            'fields': ('completed_at', 'sold_by'),
            'classes': ('collapse',)
        }),
        ('Void', {
            'fields': ('voided_at', 'voided_by', 'void_reason'),
            'classes': ('collapse',)
        }),
    )
    
    def get_customer_display(self, obj):
        if obj.customer:
            return obj.customer.get_display_name()
        return "Walk-in"
    get_customer_display.short_description = 'Customer'
    
    def get_status_badge(self, obj):
        """Colored status badge"""
        colors = {
            'DRAFT': '#FFA500',      # Orange
            'COMPLETED': '#00AA00',  # Green
            'VOIDED': '#FF0000',     # Red
        }
        color = colors.get(obj.status, '#CCCCCC')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display()
        )
    get_status_badge.short_description = 'Status'
    
    def has_add_permission(self, request):
        """Only allow adding through API"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Never allow deletion - sales are immutable records"""
        return False


@admin.register(SaleItemBatchAllocation)
class SaleItemBatchAllocationAdmin(admin.ModelAdmin):
    """Admin for batch allocations"""
    
    list_display = (
        'get_sale_receipt', 'get_batch_number', 'quantity', 'created_at'
    )
    list_filter = ('created_at', 'batch__inventory_item__pharmacy')
    readonly_fields = (
        'id', 'sale_item', 'batch', 'quantity', 'created_at'
    )
    
    fieldsets = (
        ('Allocation', {
            'fields': ('id', 'sale_item', 'batch', 'quantity')
        }),
        ('Audit', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def get_sale_receipt(self, obj):
        return obj.sale_item.sale.receipt_number
    get_sale_receipt.short_description = 'Receipt'
    
    def get_batch_number(self, obj):
        return obj.batch.batch_number
    get_batch_number.short_description = 'Batch Number'
    
    def has_add_permission(self, request):
        """Only created during sale completion"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Never allow deletion - immutable ledger"""
        return False


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Admin for stock movements (immutable ledger)"""
    
    list_display = (
        'id', 'get_type_badge', 'pharmacy', 'get_medicine_name',
        'get_batch_number', 'quantity_change', 'get_sale_receipt',
        'performed_by', 'created_at'
    )
    list_filter = ('movement_type', 'pharmacy', 'created_at')
    search_fields = ('sale__receipt_number', 'batch__batch_number')
    readonly_fields = (
        'id', 'movement_type', 'pharmacy', 'inventory_item', 'batch',
        'quantity_change', 'sale', 'sale_item', 'performed_by', 'notes',
        'created_at'
    )
    
    fieldsets = (
        ('Movement Identification', {
            'fields': ('id', 'movement_type')
        }),
        ('Stock Details', {
            'fields': ('pharmacy', 'inventory_item', 'batch', 'quantity_change')
        }),
        ('References', {
            'fields': ('sale', 'sale_item'),
            'description': 'Links to the sale that caused this movement'
        }),
        ('Audit', {
            'fields': ('performed_by', 'notes', 'created_at')
        }),
    )
    
    def get_type_badge(self, obj):
        """Colored movement type badge"""
        colors = {
            'SALE': '#FF0000',       # Red (decrease)
            'VOID': '#FFA500',       # Orange (reversal)
            'RECEIVE': '#00AA00',    # Green (increase)
            'ADJUSTMENT': '#0000FF', # Blue (manual)
        }
        color = colors.get(obj.movement_type, '#CCCCCC')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; '
            'border-radius: 3px;">{}</span>',
            color,
            obj.get_movement_type_display()
        )
    get_type_badge.short_description = 'Type'
    
    def get_medicine_name(self, obj):
        return obj.inventory_item.medicine.get_display_name()
    get_medicine_name.short_description = 'Medicine'
    
    def get_batch_number(self, obj):
        return obj.batch.batch_number
    get_batch_number.short_description = 'Batch'
    
    def get_sale_receipt(self, obj):
        if obj.sale:
            return obj.sale.receipt_number
        return '-'
    get_sale_receipt.short_description = 'Receipt'
    
    def has_add_permission(self, request):
        """Created automatically, not manually"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Never allow deletion - immutable audit ledger"""
        return False
