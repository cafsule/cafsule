from django.contrib import admin

from .models import Purchase, PurchaseItem, PurchaseReceipt, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'pharmacy', 'status', 'phone', 'created_at')
    list_filter = ('status', 'pharmacy')
    search_fields = ('name', 'contact_person', 'email', 'phone')


class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0
    readonly_fields = ('received_quantity', 'subtotal')


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'pharmacy', 'supplier', 'status', 'total', 'created_at')
    list_filter = ('status', 'pharmacy')
    inlines = (PurchaseItemInline,)


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(admin.ModelAdmin):
    list_display = ('purchase_item', 'quantity', 'batch_number', 'received_by', 'received_at')
    list_filter = ('received_at',)
