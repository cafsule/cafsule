from decimal import Decimal
from datetime import date, datetime, time

from django.db import models
from django.db.models import Count, F, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import CustomerReturn, InventoryBatch, PharmacyInventoryItem
from pharmacy.models import PharmacyBrand
from sales.models import Sale, SaleItem, StockMovement

from .permissions import IsReportingAllowed
from .utils import BUSINESS_TIMEZONE, get_default_report_window, resolve_user_pharmacy


class BaseReportView(APIView):
    permission_classes = [IsAuthenticated, IsReportingAllowed]

    def get_pharmacy_queryset(self, model):
        user = self.request.user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return model.objects.all()

        pharmacy = resolve_user_pharmacy(self.request)
        if not pharmacy:
            return model.objects.none()
        if model is PharmacyBrand:
            return model.objects.filter(pk=pharmacy.pk)
        if hasattr(model, 'pharmacy'):
            return model.objects.filter(pharmacy=pharmacy)
        return model.objects.filter(pharmacy_id=pharmacy.id)

    def get_sales_queryset(self):
        return self.get_pharmacy_queryset(Sale).select_related('pharmacy', 'sold_by', 'created_by', 'voided_by')

    def get_inventory_queryset(self):
        return self.get_pharmacy_queryset(PharmacyInventoryItem).select_related('pharmacy', 'medicine')

    def get_stock_movement_queryset(self):
        return self.get_pharmacy_queryset(StockMovement).select_related('pharmacy', 'inventory_item', 'batch', 'sale', 'sale_item', 'performed_by')

    def parse_dates(self):
        q = self.request.query_params
        date_from = q.get('date_from')
        date_to = q.get('date_to')
        if date_from or date_to:
            try:
                start_date = date.fromisoformat(date_from) if date_from else None
                end_date = date.fromisoformat(date_to) if date_to else None
            except ValueError as exc:
                raise ValidationError('date_from and date_to must use YYYY-MM-DD format') from exc
            if start_date and end_date and start_date > end_date:
                raise ValidationError('date_from must be on or before date_to')
            start = datetime.combine(start_date, time.min, tzinfo=BUSINESS_TIMEZONE) if start_date else None
            end = datetime.combine(end_date, time.max, tzinfo=BUSINESS_TIMEZONE) if end_date else None
            return start, end

        start, end = get_default_report_window(self.request)
        return start, end

    def get_period_sales(self):
        return self.get_bounded_queryset(
            self.get_sales_queryset().filter(status='COMPLETED'), 'completed_at'
        )

    def get_bounded_queryset(self, queryset, date_field='completed_at'):
        start, end = self.parse_dates()
        if start:
            queryset = queryset.filter(**{f'{date_field}__gte': start})
        if end:
            queryset = queryset.filter(**{f'{date_field}__lte': end})
        return queryset


class DashboardSummaryView(BaseReportView):
    def get(self, request, *args, **kwargs):
        sales_qs = self.get_sales_queryset().filter(status='COMPLETED')
        sales_qs = self.get_bounded_queryset(sales_qs, 'completed_at')

        revenue_agg = sales_qs.aggregate(
            revenue=Sum('total'),
            transactions=Count('id'),
        )
        items_sold = SaleItem.objects.filter(sale__in=sales_qs).aggregate(total_items=Sum('quantity'))

        inventory_qs = self.get_inventory_queryset()
        low_stock_count = inventory_qs.annotate(
            available=Sum('batches__quantity', filter=models.Q(batches__expiry_date__gt=timezone.now().date()))
        ).filter(available__lte=models.F('reorder_level')).count()

        expiring_soon = InventoryBatch.objects.filter(
            inventory_item__pharmacy__in=self.get_pharmacy_queryset(PharmacyBrand),
            expiry_date__gte=timezone.now().date(),
            expiry_date__lte=timezone.now().date() + timezone.timedelta(days=30),
        ).count()

        start, end = self.parse_dates()
        data = {
            'period': {
                'from': start.isoformat() if start else None,
                'to': end.isoformat() if end else None,
            },
            'sales': {
                'revenue': str(revenue_agg['revenue'] or Decimal('0.00')),
                'transactions': revenue_agg['transactions'] or 0,
                'units_sold': items_sold['total_items'] or 0,
            },
            'inventory': {
                'low_stock_count': low_stock_count,
                'expiring_soon_count': expiring_soon,
            },
        }
        return Response(data, status=status.HTTP_200_OK)


class DailyOperationsSummaryView(BaseReportView):
    """Aggregated private operational summary for a business date/range."""

    def get(self, request, *args, **kwargs):
        sales = self.get_period_sales()
        paid_sales = sales.filter(payment_status='PAID')
        payment_totals = paid_sales.values('payment_method').annotate(amount=Sum('amount_paid'))
        payment_map = {row['payment_method']: row['amount'] or Decimal('0.00') for row in payment_totals}
        digital_methods = ('POS', 'BANK_TRANSFER', 'MOBILE_MONEY')

        sale_totals = sales.aggregate(
            count=Count('id'), gross=Sum('total'), units=Sum('items__quantity')
        )
        returns = self.get_bounded_queryset(
            self.get_pharmacy_queryset(CustomerReturn).filter(status='COMPLETED'), 'created_at'
        ).aggregate(quantity=Sum('quantity_returned'))

        movements = self.get_bounded_queryset(self.get_stock_movement_queryset(), 'created_at')
        movement_rows = movements.values('movement_type').annotate(quantity=Sum('quantity_change'))
        activity = {row['movement_type']: row['quantity'] or 0 for row in movement_rows}

        return Response({
            'period': {'from': self.parse_dates()[0].isoformat(), 'to': self.parse_dates()[1].isoformat()},
            'sales': {
                'completed_sales': sale_totals['count'] or 0,
                'gross_sales': str(sale_totals['gross'] or Decimal('0.00')),
                'net_sales': str(sale_totals['gross'] or Decimal('0.00')),
                'items_sold': sale_totals['units'] or 0,
                'cash_received': str(payment_map.get('CASH', Decimal('0.00'))),
                'digital_received': str(sum((payment_map.get(method, Decimal('0.00')) for method in digital_methods), Decimal('0.00'))),
                'payment_methods': {method: str(amount) for method, amount in payment_map.items()},
            },
            'returns': {'units_returned': returns['quantity'] or 0, 'refund_amount': None},
            'inventory_activity': activity,
            'cash_reconciliation': None,
        })


class PaymentMethodSummaryView(BaseReportView):
    def get(self, request, *args, **kwargs):
        sales_qs = self.get_sales_queryset().filter(status='COMPLETED', payment_status='PAID')
        sales_qs = self.get_bounded_queryset(sales_qs, 'completed_at')
        results = sales_qs.values('payment_method').annotate(
            transaction_count=Count('id'),
            total_amount=Sum('total'),
        ).order_by('payment_method')

        payload = []
        for row in results:
            payload.append({
                'payment_method': row['payment_method'],
                'transaction_count': row['transaction_count'],
                'total_amount': str(row['total_amount'] or Decimal('0.00')),
            })

        return Response({'results': payload}, status=status.HTTP_200_OK)


class DailySalesReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        sales_qs = self.get_sales_queryset().filter(status='COMPLETED')
        start, end = self.parse_dates()
        if start:
            sales_qs = sales_qs.filter(completed_at__gte=start)
        if end:
            sales_qs = sales_qs.filter(completed_at__lte=end)

        daily = sales_qs.annotate(
            day=models.functions.TruncDate('completed_at', tzinfo=BUSINESS_TIMEZONE)
        ).values('day').annotate(
            transactions=Count('id'),
            units_sold=Sum('items__quantity'),
            revenue=Sum('total'),
        ).order_by('day')

        results = []
        for row in daily:
            results.append({
                'date': row['day'].isoformat() if row['day'] else None,
                'transactions': row['transactions'],
                'units_sold': row['units_sold'] or 0,
                'revenue': str(row['revenue'] or Decimal('0.00')),
            })

        return Response({'results': results}, status=status.HTTP_200_OK)


class ProductSalesReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        sales_qs = self.get_sales_queryset().filter(status='COMPLETED')
        start, end = self.parse_dates()
        if start:
            sales_qs = sales_qs.filter(completed_at__gte=start)
        if end:
            sales_qs = sales_qs.filter(completed_at__lte=end)

        items = SaleItem.objects.filter(sale__in=sales_qs).select_related('inventory_item__medicine').values(
            'inventory_item__medicine__generic_name',
            'inventory_item__medicine__brand_name',
            'inventory_item__medicine__strength',
        ).annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum(F('line_total')),
            transaction_count=Count('sale_id', distinct=True),
        ).order_by('-quantity_sold')

        payload = []
        for row in items:
            name = row['inventory_item__medicine__generic_name']
            if row['inventory_item__medicine__brand_name']:
                name = f"{name} / {row['inventory_item__medicine__brand_name']}"
            payload.append({
                'medicine': name,
                'quantity_sold': row['quantity_sold'],
                'revenue': str(row['revenue'] or Decimal('0.00')),
                'transaction_count': row['transaction_count'],
            })

        return Response({'results': payload}, status=status.HTTP_200_OK)


class InventorySummaryView(BaseReportView):
    def get(self, request, *args, **kwargs):
        inventory_qs = self.get_inventory_queryset()
        total_inventory_items = inventory_qs.count()
        total_units_in_stock = 0
        for item in inventory_qs.prefetch_related('batches'):
            total_units_in_stock += sum(
                batch.quantity for batch in item.batches.all() if batch.expiry_date > timezone.now().date()
            )

        expired_batches = InventoryBatch.objects.filter(
            inventory_item__pharmacy__in=self.get_pharmacy_queryset(PharmacyBrand),
            expiry_date__lte=timezone.now().date(),
        ).count()

        expiring_soon = InventoryBatch.objects.filter(
            inventory_item__pharmacy__in=self.get_pharmacy_queryset(PharmacyBrand),
            expiry_date__gte=timezone.now().date(),
            expiry_date__lte=timezone.now().date() + timezone.timedelta(days=30),
        ).count()

        payload = {
            'inventory': {
                'total_inventory_items': total_inventory_items,
                'total_units_in_stock': total_units_in_stock,
                'low_stock_count': 0,
                'out_of_stock_count': 0,
                'expiring_soon_count': expiring_soon,
                'expired_batches': expired_batches,
            }
        }
        return Response(payload, status=status.HTTP_200_OK)


class InventoryCurrentStockView(BaseReportView):
    def get(self, request, *args, **kwargs):
        items = self.get_inventory_queryset().select_related('medicine').prefetch_related('batches').all()
        payload = []
        for item in items:
            batches = list(item.batches.all())
            valid_batches = [batch for batch in batches if batch.expiry_date > timezone.now().date()]
            total_quantity = sum(batch.quantity for batch in valid_batches)
            payload.append({
                'inventory_item': item.id,
                'medicine': item.medicine.generic_name,
                'current_quantity': total_quantity,
                'reorder_level': item.reorder_level,
                'low_stock': total_quantity <= item.reorder_level,
                'sellable_availability': 'AVAILABLE' if total_quantity > 0 else 'OUT_OF_STOCK',
                'selling_price': str(item.selling_price),
                'status': item.status,
                'batches': [
                    {'batch': batch.batch_number, 'quantity': batch.quantity, 'expiry_date': batch.expiry_date.isoformat()}
                    for batch in batches
                ],
            })
        return Response({'results': payload}, status=status.HTTP_200_OK)


class LowStockReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        items = self.get_inventory_queryset().prefetch_related('batches')
        results = []
        today = timezone.now().date()
        for item in items:
            quantity = sum(batch.quantity for batch in item.batches.all() if batch.expiry_date > today)
            if quantity <= item.reorder_level:
                results.append({'inventory_item': item.id, 'medicine': item.medicine.get_display_name(),
                                'current_quantity': quantity, 'reorder_level': item.reorder_level})
        return Response({'results': results})


class ExpiryReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        try:
            warning_days = int(request.query_params.get('warning_days', 30))
        except ValueError as exc:
            raise ValidationError('warning_days must be an integer') from exc
        if warning_days < 0:
            raise ValidationError('warning_days cannot be negative')
        today = timezone.now().date()
        batches = InventoryBatch.objects.filter(
            inventory_item__in=self.get_inventory_queryset(),
        ).select_related('inventory_item__medicine').order_by('expiry_date')
        results = []
        for batch in batches:
            if batch.expiry_date <= today + timezone.timedelta(days=warning_days):
                results.append({'medicine': batch.inventory_item.medicine.get_display_name(),
                                'batch': batch.batch_number, 'quantity': batch.quantity,
                                'expiry_date': batch.expiry_date.isoformat(),
                                'expired': batch.expiry_date <= today})
        return Response({'results': results})


class TopSellingMedicinesReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        items = SaleItem.objects.filter(sale__in=self.get_period_sales()).values(
            'inventory_item__medicine_id', 'inventory_item__medicine__generic_name',
            'inventory_item__medicine__brand_name', 'inventory_item__medicine__strength',
        ).annotate(quantity_sold=Sum('quantity'), revenue=Sum('line_total'), sales=Count('sale_id', distinct=True))
        order = request.query_params.get('order_by', 'quantity')
        items = items.order_by('-revenue' if order == 'revenue' else '-quantity_sold')
        limit = min(max(int(request.query_params.get('limit', 10)), 1), 100)
        return Response({'results': [
            {'medicine_id': row['inventory_item__medicine_id'],
             'medicine': row['inventory_item__medicine__generic_name'],
             'brand_name': row['inventory_item__medicine__brand_name'],
             'strength': row['inventory_item__medicine__strength'],
             'quantity_sold': row['quantity_sold'], 'revenue': str(row['revenue'] or Decimal('0.00')),
             'completed_sales': row['sales']}
            for row in items[:limit]
        ]})


class InventoryMovementReportView(BaseReportView):
    def get(self, request, *args, **kwargs):
        qs = self.get_stock_movement_queryset()
        movement_type = self.request.query_params.get('movement_type')
        if movement_type:
            qs = qs.filter(movement_type=movement_type)
        if self.request.query_params.get('batch'):
            qs = qs.filter(batch_id=self.request.query_params['batch'])
        if self.request.query_params.get('medicine'):
            qs = qs.filter(inventory_item__medicine_id=self.request.query_params['medicine'])

        start, end = self.parse_dates()
        if start:
            qs = qs.filter(created_at__gte=start)
        if end:
            qs = qs.filter(created_at__lte=end)

        payload = []
        for row in qs.order_by('-created_at')[:100]:
            payload.append({
                'movement_type': row.movement_type,
                'quantity_change': row.quantity_change,
                'batch': row.batch.batch_number,
                'medicine': row.inventory_item.medicine.generic_name,
                'created_at': row.created_at.isoformat(),
                'performed_by': getattr(row.performed_by, 'email', None),
            })

        return Response({'results': payload}, status=status.HTTP_200_OK)
