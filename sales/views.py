"""
ViewSets and Views for Sales API.

Endpoints:
- GET/POST /sales/ - List and create sales
- GET/PATCH /sales/{id}/ - Get and update sales
- POST /sales/{id}/complete/ - Complete a sale
- POST /sales/{id}/void/ - Void a completed sale
- GET /customers/ - List customers
- POST /customers/ - Create customer
"""

from decimal import Decimal
from rest_framework import viewsets, status, permissions, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Sale, SaleItem, Customer, StockMovement, CustomerPayment, CustomerLedgerEntry
from .permissions import (
    IsPharmacyStaffWithMembership, CanCreateSale, CanCompleteSale,
    CanVoidSale, CanViewSales
)
from .serializers import (
    SaleListSerializer, SaleDetailSerializer, SaleCreateSerializer,
    SaleUpdateSerializer, SaleCompleteSerializer, SaleVoidSerializer,
    SaleItemCreateUpdateSerializer, SaleItemDetailSerializer,
    CustomerSerializer, CustomerPaymentSerializer, CustomerLedgerEntrySerializer,
    StockMovementSerializer
)
from .services import SaleCompletionService, SaleVoidService
from pharmacy.models import PharmacyMembership


class CustomerViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing customers.
    
    GET /customers/ - List customers for your pharmacy
    POST /customers/ - Create a new customer
    GET /customers/{id}/ - Get customer details
    PATCH /customers/{id}/ - Update customer
    """
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyStaffWithMembership]
    serializer_class = CustomerSerializer
    
    def get_queryset(self):
        """Return customers for the user's pharmacy"""
        user = self.request.user
        
        # Build the authorized base queryset first; search is applied afterward.
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            qs = Customer.objects.all().select_related('pharmacy')
        elif user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                qs = Customer.objects.filter(pharmacy=pharmacy)
            except:
                qs = Customer.objects.none()
        else:
            memberships = PharmacyMembership.objects.filter(
                user=user,
                status='APPROVED'
            ).values_list('pharmacy_id', flat=True)
            qs = Customer.objects.filter(pharmacy_id__in=memberships)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(email__icontains=search)
            )
            try:
                limit = min(max(int(self.request.query_params.get('limit', '20')), 1), 50)
            except (TypeError, ValueError):
                limit = 20
            return qs.order_by('-created_at')[:limit]

        return qs
    
    def perform_create(self, serializer):
        """Set pharmacy when creating customer"""
        user = self.request.user
        
        if user.role == 'PHARMACY_OWNER':
            pharmacy = user.owned_pharmacy_brand
        else:
            membership = PharmacyMembership.objects.filter(
                user=user,
                status='APPROVED'
            ).first()
            pharmacy = membership.pharmacy
        
        serializer.save(pharmacy=pharmacy)

    @action(detail=True, methods=['get'])
    def ledger(self, request, pk=None):
        customer = self.get_object()
        entries = customer.ledger_entries.select_related('sale', 'payment').all()
        serializer = CustomerLedgerEntrySerializer(entries, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def payments(self, request, pk=None):
        customer = self.get_object()
        payments = customer.payments.select_related('sale', 'recorded_by').all()
        serializer = CustomerPaymentSerializer(payments, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def record_payment(self, request, pk=None):
        customer = self.get_object()
        serializer = CustomerPaymentSerializer(data=request.data, context={'customer': customer})
        serializer.is_valid(raise_exception=True)

        sale_id = request.data.get('sale_id')
        sale = None
        if sale_id:
            sale = Sale.objects.select_for_update().filter(id=sale_id, customer=customer, pharmacy=customer.pharmacy).first()
            if sale is None:
                return Response({'detail': 'Sale not found for this customer.'}, status=status.HTTP_400_BAD_REQUEST)
            if sale.status != 'COMPLETED':
                return Response({'detail': 'Only completed sales can receive customer payments.'}, status=status.HTTP_400_BAD_REQUEST)

        payment = CustomerPayment.objects.create(
            customer=customer,
            pharmacy=customer.pharmacy,
            sale=sale,
            amount=serializer.validated_data['amount'],
            payment_method=serializer.validated_data['payment_method'],
            reference=serializer.validated_data.get('reference', ''),
            notes=serializer.validated_data.get('notes', ''),
            recorded_by=request.user,
        )

        starting_balance = customer.outstanding_balance
        remaining_balance = max(Decimal('0.00'), starting_balance - payment.amount)
        customer_ledger = CustomerLedgerEntry.objects.create(
            customer=customer,
            pharmacy=customer.pharmacy,
            sale=sale,
            payment=payment,
            entry_type='PAYMENT',
            amount=payment.amount,
            description='Customer payment',
            notes=payment.notes,
            balance_after=remaining_balance,
            created_by=request.user,
        )

        if sale is not None:
            sale.apply_customer_payment(payment.amount)

        return Response({
            'payment': CustomerPaymentSerializer(payment).data,
            'ledger_entry': CustomerLedgerEntrySerializer(customer_ledger).data,
            'new_balance': remaining_balance,
        }, status=status.HTTP_201_CREATED)


class SaleItemViewSet(viewsets.ViewSet):
    """
    API endpoint for managing sale items.
    
    Note: Sale items are managed as part of sale details.
    These endpoints are for direct manipulation.
    """
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyStaffWithMembership]
    
    def get_queryset(self):
        """Return sale items for user's sales"""
        user = self.request.user
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return SaleItem.objects.all().select_related('sale', 'inventory_item')
        
        if user.role == 'PHARMACY_OWNER':
            pharmacy = user.owned_pharmacy_brand
            return SaleItem.objects.filter(
                sale__pharmacy=pharmacy
            ).select_related('sale', 'inventory_item')
        
        memberships = PharmacyMembership.objects.filter(
            user=user,
            status='APPROVED'
        ).values_list('pharmacy_id', flat=True)
        
        return SaleItem.objects.filter(
            sale__pharmacy_id__in=memberships
        ).select_related('sale', 'inventory_item')


class SaleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing sales.
    
    GET /sales/ - List sales
    POST /sales/ - Create sale (draft)
    GET /sales/{id}/ - Get sale details
    PATCH /sales/{id}/ - Update sale (draft only)
    POST /sales/{id}/add-item/ - Add item to draft sale
    POST /sales/{id}/complete/ - Complete draft sale
    POST /sales/{id}/void/ - Void completed sale
    POST /sales/{id}/stock-movements/ - Get stock movements
    """
    
    permission_classes = [permissions.IsAuthenticated, CanViewSales, IsPharmacyStaffWithMembership]

    def get_permissions(self):
        if self.action == 'create':
            return [permissions.IsAuthenticated(), CanCreateSale()]
        return super().get_permissions()
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action"""
        if self.action == 'list':
            return SaleListSerializer
        elif self.action == 'retrieve':
            return SaleDetailSerializer
        elif self.action == 'create':
            return SaleCreateSerializer
        elif self.action in ('update', 'partial_update'):
            return SaleUpdateSerializer
        elif self.action == 'complete':
            return SaleCompleteSerializer
        elif self.action == 'void':
            return SaleVoidSerializer
        return SaleDetailSerializer
    
    def get_queryset(self):
        """Return sales for user's pharmacy"""
        user = self.request.user
        
        # Platform admins see all sales
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return Sale.objects.all().select_related(
                'pharmacy', 'customer', 'sold_by', 'created_by', 'voided_by'
            ).prefetch_related('items', 'stock_movements')
        
        # Pharmacy owners see their sales
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                return Sale.objects.filter(
                    pharmacy=pharmacy
                ).select_related(
                    'pharmacy', 'customer', 'sold_by', 'created_by', 'voided_by'
                ).prefetch_related('items', 'stock_movements')
            except:
                return Sale.objects.none()
        
        # Staff see sales for approved pharmacies
        memberships = PharmacyMembership.objects.filter(
            user=user,
            status='APPROVED'
        ).values_list('pharmacy_id', flat=True)
        
        return Sale.objects.filter(
            pharmacy_id__in=memberships
        ).select_related(
            'pharmacy', 'customer', 'sold_by', 'created_by', 'voided_by'
        ).prefetch_related('items', 'stock_movements')
    
    def check_object_permissions(self, request, obj):
        """Override to check custom permissions"""
        for permission in self.get_permissions():
            if hasattr(permission, 'has_object_permission'):
                if not permission.has_object_permission(request, self, obj):
                    self.permission_denied(request)
        return super().check_object_permissions(request, obj)
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanCompleteSale])
    @transaction.atomic
    def complete(self, request, pk=None):
        """
        Complete a draft sale.
        
        This endpoint:
        1. Validates the sale can be completed
        2. Validates all items
        3. Allocates batches using FEFO
        4. Reduces batch quantities
        5. Creates stock movements
        6. Marks sale as COMPLETED
        
        Request:
        {
            "payment_status": "PAID",
            "amount_paid": "5000.00"
        }
        """
        sale = self.get_object()
        
        # Check permission
        if not CanCompleteSale().has_object_permission(request, self, sale):
            return Response(
                {'detail': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get optional fields from request
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        payment_status = serializer.validated_data.get('payment_status')
        amount_paid = serializer.validated_data.get('amount_paid')
        
        try:
            # Complete the sale (handles all business logic atomically)
            sale = SaleCompletionService.complete_sale(sale, request.user)
            
            # Update payment info if provided
            if payment_status:
                sale.payment_status = payment_status
            if amount_paid is not None:
                sale.amount_paid = amount_paid
            sale.save()
            
            # Return updated sale
            return_serializer = SaleDetailSerializer(sale, context={'request': request})
            return Response(return_serializer.data, status=status.HTTP_200_OK)
        
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'detail': f"Error completing sale: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanVoidSale])
    @transaction.atomic
    def void(self, request, pk=None):
        """
        Void a completed sale.
        
        This marks the sale as VOIDED. The original sale remains in history.
        Stock is restored from the recorded batch allocations and compensating
        VOID stock movements are created atomically.
        
        Request:
        {
            "void_reason": "Customer returned items"
        }
        """
        sale = self.get_object()
        
        # Check permission
        if not CanVoidSale().has_object_permission(request, self, sale):
            return Response(
                {'detail': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        void_reason = serializer.validated_data.get('void_reason', '')
        
        try:
            sale = SaleVoidService.void_sale(sale, request.user, void_reason)
            
            # Return updated sale
            return_serializer = SaleDetailSerializer(sale, context={'request': request})
            return Response(return_serializer.data, status=status.HTTP_200_OK)
        
        except ValueError as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def add_item(self, request, pk=None):
        """
        Add an item to a draft sale.
        
        Request:
        {
            "inventory_item_id": "uuid",
            "quantity": 5,
            "line_discount": "0.00"
        }
        """
        sale = self.get_object()
        
        # Verify sale is DRAFT
        if sale.status != 'DRAFT':
            return Response(
                {'detail': f"Cannot add items to {sale.status} sale"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Deserialize and validate item
        serializer = SaleItemCreateUpdateSerializer(
            data=request.data,
            context={'sale_id': sale.id, 'pharmacy': sale.pharmacy, 'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        try:
            # Create sale item
            item = SaleItem.objects.create(
                sale=sale,
                inventory_item=serializer.validated_data['inventory_item_id'],
                quantity=serializer.validated_data['quantity'],
                unit_price=serializer.validated_data['unit_price'],
                line_discount=serializer.validated_data['line_discount'],
                line_total=serializer.validated_data['line_total']
            )
            
            # Recalculate sale totals
            items = sale.items.all()
            subtotal = sum(i.line_total for i in items)
            sale.subtotal = subtotal
            sale.total = subtotal - sale.discount + sale.tax
            sale.save(update_fields=['subtotal', 'total', 'updated_at'])
            
            # Return created item
            item_serializer = SaleItemDetailSerializer(item)
            return Response(item_serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def stock_movements(self, request, pk=None):
        """
        Get stock movements for a completed sale.
        
        Returns all StockMovement records created when this sale was completed.
        """
        sale = self.get_object()
        movements = StockMovement.objects.filter(sale=sale).select_related(
            'pharmacy', 'inventory_item', 'batch', 'performed_by'
        )
        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)
