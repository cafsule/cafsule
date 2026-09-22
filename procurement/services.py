from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from inventory.models import InventoryBatch, PharmacyInventoryItem
from pharmacy.models import PharmacyBrand, PharmacyMembership
from sales.models import StockMovement

from .models import Purchase, PurchaseItem, PurchaseReceipt, Supplier


WRITE_ROLES = {'PHARMACY_OWNER', 'PHARMACY_MANAGER'}
PLATFORM_ROLES = {'SUPER_ADMIN', 'PLATFORM_ADMIN'}


def user_pharmacy_ids(user):
    if user.role in PLATFORM_ROLES:
        return None
    if user.role == 'PHARMACY_OWNER':
        return [user.owned_pharmacy_brand.id] if hasattr(user, 'owned_pharmacy_brand') else []
    return list(PharmacyMembership.objects.filter(user=user, status='APPROVED').values_list('pharmacy_id', flat=True))


def resolve_pharmacy(user, pharmacy_id=None):
    if user.role in PLATFORM_ROLES:
        if not pharmacy_id:
            raise ValueError('pharmacy_id is required for platform administration')
        return PharmacyBrand.objects.get(pk=pharmacy_id)
    ids = user_pharmacy_ids(user)
    if not ids:
        raise PermissionError('You do not have an approved pharmacy membership')
    if pharmacy_id and str(pharmacy_id) not in {str(value) for value in ids}:
        raise PermissionError('You are not authorized for this pharmacy')
    return PharmacyBrand.objects.get(pk=ids[0])


def scoped_supplier_queryset(user):
    ids = user_pharmacy_ids(user)
    queryset = Supplier.objects.select_related('pharmacy')
    return queryset if ids is None else queryset.filter(pharmacy_id__in=ids)


def scoped_purchase_queryset(user):
    ids = user_pharmacy_ids(user)
    queryset = Purchase.objects.select_related('pharmacy', 'supplier', 'created_by').prefetch_related('items__medicine', 'items__receipts')
    return queryset if ids is None else queryset.filter(pharmacy_id__in=ids)


class PurchaseService:
    @staticmethod
    @transaction.atomic
    def create_purchase(*, user, pharmacy, supplier, items, notes=''):
        if pharmacy.verification_status != 'VERIFIED':
            raise ValueError('Purchases require a VERIFIED pharmacy')
        if supplier.pharmacy_id != pharmacy.id or supplier.status != 'ACTIVE':
            raise ValueError('Supplier is not available for this pharmacy')
        purchase = Purchase.objects.create(
            pharmacy=pharmacy, supplier=supplier, notes=notes, created_by=user,
        )
        for item in items:
            medicine = item['medicine']
            inventory_item = PharmacyInventoryItem.objects.filter(
                pharmacy=pharmacy, medicine=medicine,
            ).first()
            if not inventory_item:
                raise ValueError('Each medicine must already have a pharmacy inventory item')
            PurchaseItem.objects.create(
                purchase=purchase,
                medicine=medicine,
                inventory_item=inventory_item,
                quantity_ordered=item['quantity_ordered'],
                unit_cost=item['unit_cost'],
            )
        PurchaseService.recalculate(purchase)
        return purchase

    @staticmethod
    def recalculate(purchase):
        subtotal = sum((item.subtotal for item in purchase.items.all()), Decimal('0.00'))
        purchase.subtotal = subtotal
        purchase.total = subtotal
        purchase.save(update_fields=('subtotal', 'total', 'updated_at'))

    @staticmethod
    @transaction.atomic
    def submit(purchase, user):
        purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
        if purchase.status != 'DRAFT':
            raise ValueError('Only draft purchases can be submitted')
        if not purchase.items.exists():
            raise ValueError('A purchase must contain at least one item')
        purchase.status = 'SUBMITTED'
        purchase.submitted_at = timezone.now()
        purchase.save(update_fields=('status', 'submitted_at', 'updated_at'))
        return purchase

    @staticmethod
    @transaction.atomic
    def receive(*, purchase, purchase_item, user, quantity, batch_number, expiry_date, cost_per_unit, notes=''):
        purchase = Purchase.objects.select_for_update().get(pk=purchase.pk)
        item = PurchaseItem.objects.select_for_update().get(pk=purchase_item.pk)
        if item.purchase_id != purchase.id:
            raise ValueError('Purchase item does not belong to this purchase')
        if purchase.status not in ('SUBMITTED', 'PARTIALLY_RECEIVED'):
            raise ValueError('Purchase is not open for receiving')
        if quantity <= 0:
            raise ValueError('Receive quantity must be greater than zero')
        if quantity > item.remaining_quantity:
            raise ValueError(f'Receive quantity exceeds remaining quantity ({item.remaining_quantity})')
        if expiry_date <= timezone.now().date():
            raise ValueError('Expiry date must be in the future')

        inventory_item = PharmacyInventoryItem.objects.select_for_update().get(pk=item.inventory_item_id)

        batch = InventoryBatch.objects.select_for_update(of=('self',)).filter(
            inventory_item_id=item.inventory_item_id, batch_number=batch_number,
        ).first()
        if batch:
            if batch.expiry_date != expiry_date or batch.cost_per_unit != cost_per_unit:
                raise ValueError('Existing batch expiry date and cost cannot change')
            batch.quantity += quantity
            batch.save(update_fields=('quantity', 'updated_at'))
        else:
            batch = InventoryBatch.objects.create(
                inventory_item=inventory_item,
                batch_number=batch_number,
                quantity=quantity,
                expiry_date=expiry_date,
                cost_per_unit=cost_per_unit,
            )

        item.received_quantity += quantity
        item.save(update_fields=('received_quantity',))
        receipt = PurchaseReceipt.objects.create(
            purchase_item=item,
            batch=batch,
            quantity=quantity,
            batch_number=batch_number,
            expiry_date=expiry_date,
            cost_per_unit=cost_per_unit,
            received_by=user,
            notes=notes,
        )
        StockMovement.objects.create(
            movement_type='RECEIVE',
            pharmacy=purchase.pharmacy,
            inventory_item=inventory_item,
            batch=batch,
            quantity_change=quantity,
            reference_type='PURCHASE',
            reference_id=purchase.id,
            performed_by=user,
            notes=f'Purchase {purchase.id}: receipt {receipt.id}' + (f' - {notes}' if notes else ''),
        )
        if all(received == ordered for received, ordered in purchase.items.values_list('received_quantity', 'quantity_ordered')):
            purchase.status = 'RECEIVED'
        else:
            purchase.status = 'PARTIALLY_RECEIVED'
        purchase.save(update_fields=('status', 'updated_at'))
        return receipt
