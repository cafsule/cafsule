"""
Pharmacy Inventory ViewSets and Views
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.db.models import Q

from .models import (
    PharmacyInventoryItem, InventoryBatch, CustomerReturn,
    InventoryHold, StockReconciliation
)
from .serializers import (
    PharmacyInventoryListSerializer, PharmacyInventoryDetailSerializer,
    PharmacyInventoryCreateSerializer, PharmacyInventoryUpdateSerializer,
    InventoryBatchListSerializer, InventoryBatchCreateSerializer,
    PublishInventorySerializer, CustomerReturnListSerializer,
    CustomerReturnDetailSerializer, CustomerReturnInitiateSerializer,
    CustomerReturnApproveSerializer, InventoryHoldListSerializer,
    InventoryHoldDetailSerializer, InventoryHoldResolveSerializer,
    StockAdjustmentSerializer, DamageRecordSerializer, ExpiryRecordSerializer,
    LossRecordSerializer, StockReconciliationListSerializer,
    StockReconciliationDetailSerializer, StockReconciliationStartSerializer,
    StockReconciliationCountSerializer, StockReconciliationApproveSerializer,
    PublicInventorySerializer
)
from .services import (
    StockAdjustmentService, DamageService, ExpiryService, LossService,
    CustomerReturnService, StockReconciliationService, InventoryPublicationService
)
from auth.permissions import (
    CanAdjustStock, CanReconcileStock, CanProcessReturns
)
from medicine.permissions import CanManagePharmacyInventory, CanPublishInventory


class PharmacyInventoryViewSet(viewsets.ModelViewSet):
    """API endpoint for Pharmacy Inventory Items."""
    
    permission_classes = [permissions.IsAuthenticated, CanManagePharmacyInventory]

    def get_permissions(self):
        if self.action in ('publish', 'unpublish'):
            return [permissions.IsAuthenticated(), CanPublishInventory()]
        return super().get_permissions()
    
    def get_serializer_class(self):
        if self.action == 'list':
            return PharmacyInventoryListSerializer
        elif self.action == 'retrieve':
            return PharmacyInventoryDetailSerializer
        elif self.action == 'create':
            return PharmacyInventoryCreateSerializer
        elif self.action in ('update', 'partial_update'):
            return PharmacyInventoryUpdateSerializer
        elif self.action in ('publish', 'unpublish'):
            return PublishInventorySerializer
        return PharmacyInventoryDetailSerializer
    
    def get_queryset(self):
        user = self.request.user
        from pharmacy.models import PharmacyMembership
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            qs = PharmacyInventoryItem.objects.all().select_related('pharmacy', 'medicine')
        
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                qs = PharmacyInventoryItem.objects.filter(
                    pharmacy=pharmacy
                ).select_related('pharmacy', 'medicine')
            except:
                return PharmacyInventoryItem.objects.none()
        else:
            memberships = PharmacyMembership.objects.filter(
                user=user, status='APPROVED'
            ).values_list('pharmacy_id', flat=True)
            qs = PharmacyInventoryItem.objects.filter(
                pharmacy_id__in=memberships
            ).select_related('pharmacy', 'medicine')

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(medicine__generic_name__icontains=search) |
                Q(medicine__brand_name__icontains=search) |
                Q(medicine__strength__icontains=search)
            )
            try:
                limit = min(max(int(self.request.query_params.get('limit', '20')), 1), 50)
            except (TypeError, ValueError):
                limit = 20
            return qs.order_by('medicine__generic_name', 'medicine__strength')[:limit]

        return qs
    
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated, CanPublishInventory])
    @transaction.atomic
    def publish(self, request, pk=None):
        """Publish inventory item"""
        inventory_item = self.get_object()
        try:
            InventoryPublicationService.publish_inventory(inventory_item, request.user)
            return Response(PublishInventorySerializer(inventory_item).data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def unpublish(self, request, pk=None):
        """Unpublish inventory item"""
        inventory_item = self.get_object()
        try:
            InventoryPublicationService.unpublish_inventory(inventory_item, request.user)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PublishInventorySerializer(inventory_item).data)
    
    @action(detail=True, methods=['get'])
    def batches(self, request, pk=None):
        """Get batches for this item"""
        inventory_item = self.get_object()
        batches = inventory_item.batches.all().order_by('expiry_date')
        return Response(InventoryBatchListSerializer(batches, many=True).data)


class PublicInventoryViewSet(viewsets.ReadOnlyModelViewSet):
    """Public Smart Medicine Finder inventory listings."""

    serializer_class = PublicInventorySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = InventoryPublicationService.public_queryset()
        search = self.request.query_params.get('search')
        if search:
            from django.db.models import Q
            queryset = queryset.filter(
                Q(medicine__generic_name__icontains=search)
                | Q(medicine__brand_name__icontains=search)
                | Q(medicine__strength__icontains=search)
            )
        return queryset


class InventoryBatchViewSet(viewsets.ModelViewSet):
    """API endpoint for Inventory Batches."""
    
    permission_classes = [permissions.IsAuthenticated, CanManagePharmacyInventory]
    
    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return InventoryBatchCreateSerializer
        return InventoryBatchListSerializer
    
    def get_queryset(self):
        user = self.request.user
        from pharmacy.models import PharmacyMembership
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            inventory_ids = PharmacyInventoryItem.objects.values_list('id', flat=True)
        elif user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                inventory_ids = PharmacyInventoryItem.objects.filter(
                    pharmacy=pharmacy
                ).values_list('id', flat=True)
            except:
                return InventoryBatch.objects.none()
        else:
            memberships = PharmacyMembership.objects.filter(
                user=user, status='APPROVED'
            ).values_list('pharmacy_id', flat=True)
            inventory_ids = PharmacyInventoryItem.objects.filter(
                pharmacy_id__in=memberships
            ).values_list('id', flat=True)
        
        return InventoryBatch.objects.filter(
            inventory_item_id__in=inventory_ids
        ).select_related('inventory_item', 'inventory_item__medicine')
    
    def create(self, request, *args, **kwargs):
        """Create batch"""
        inventory_item_id = request.data.get('inventory_item_id')
        if not inventory_item_id:
            return Response({'detail': 'inventory_item_id required'}, status=status.HTTP_400_BAD_REQUEST)
        
        inventory_item = get_object_or_404(PharmacyInventoryItem, id=inventory_item_id)
        self.check_object_permissions(request, inventory_item)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        batch = InventoryBatch.objects.create(
            inventory_item=inventory_item,
            **serializer.validated_data
        )
        return Response(InventoryBatchListSerializer(batch).data, status=status.HTTP_201_CREATED)


# ============================================================================
# Customer Return ViewSet
# ============================================================================

class CustomerReturnViewSet(viewsets.ViewSet):
    """API endpoint for Customer Returns."""
    
    permission_classes = [permissions.IsAuthenticated, CanProcessReturns]
    
    def get_queryset(self):
        user = self.request.user
        from pharmacy.models import PharmacyMembership
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return CustomerReturn.objects.all().select_related(
                'sale', 'sale_item', 'inventory_item', 'batch', 'initiated_by', 'reviewed_by'
            )
        
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                return CustomerReturn.objects.filter(pharmacy=pharmacy).select_related(
                    'sale', 'sale_item', 'inventory_item', 'batch', 'initiated_by', 'reviewed_by'
                )
            except:
                return CustomerReturn.objects.none()
        
        memberships = PharmacyMembership.objects.filter(
            user=user, status='APPROVED'
        ).values_list('pharmacy_id', flat=True)
        
        return CustomerReturn.objects.filter(pharmacy_id__in=memberships).select_related(
            'sale', 'sale_item', 'inventory_item', 'batch', 'initiated_by', 'reviewed_by'
        )
    
    def list(self, request):
        """List returns"""
        serializer = CustomerReturnListSerializer(self.get_queryset(), many=True)
        return Response(serializer.data)
    
    def retrieve(self, request, pk=None):
        """Get return"""
        obj = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(CustomerReturnDetailSerializer(obj).data)
    
    @transaction.atomic
    def create(self, request):
        """Initiate return"""
        serializer = CustomerReturnInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            return_record = CustomerReturnService.initiate_return(
                sale=serializer.validated_data['sale'],
                sale_item=serializer.validated_data['sale_item'],
                quantity_returned=serializer.validated_data['quantity_returned'],
                condition=serializer.validated_data['condition'],
                reason=serializer.validated_data.get('reason', ''),
                user=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            return Response(CustomerReturnDetailSerializer(return_record).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """Approve/reject return"""
        return_record = get_object_or_404(self.get_queryset(), pk=pk)
        action_type = request.data.get('action', 'APPROVE')
        
        try:
            if action_type == 'APPROVE':
                CustomerReturnService.approve_return(return_record, request.user)
                return_record, movements = CustomerReturnService.process_approved_return(return_record, request.user)
            elif action_type == 'REJECT':
                return_record.reject(request.user)
            
            return Response(CustomerReturnDetailSerializer(return_record).data)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Inventory Hold ViewSet
# ============================================================================

class InventoryHoldViewSet(viewsets.ViewSet):
    """API endpoint for Inventory Holds."""
    
    permission_classes = [permissions.IsAuthenticated, CanAdjustStock]
    
    def get_queryset(self):
        user = self.request.user
        from pharmacy.models import PharmacyMembership
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return InventoryHold.objects.all().select_related(
                'batch', 'inventory_item', 'pharmacy', 'initiated_by', 'resolved_by'
            )
        
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                return InventoryHold.objects.filter(pharmacy=pharmacy).select_related(
                    'batch', 'inventory_item', 'pharmacy', 'initiated_by', 'resolved_by'
                )
            except:
                return InventoryHold.objects.none()
        
        memberships = PharmacyMembership.objects.filter(
            user=user, status='APPROVED'
        ).values_list('pharmacy_id', flat=True)
        
        return InventoryHold.objects.filter(pharmacy_id__in=memberships).select_related(
            'batch', 'inventory_item', 'pharmacy', 'initiated_by', 'resolved_by'
        )
    
    def list(self, request):
        """List holds"""
        return Response(InventoryHoldListSerializer(self.get_queryset(), many=True).data)
    
    def retrieve(self, request, pk=None):
        """Get hold"""
        obj = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(InventoryHoldDetailSerializer(obj).data)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def resolve(self, request, pk=None):
        """Resolve hold"""
        hold = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = InventoryHoldResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            hold.resolve(
                user=request.user,
                resolution=serializer.validated_data['resolution'],
                release_quantity=serializer.validated_data['quantity']
            )
            return Response(InventoryHoldDetailSerializer(hold).data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Stock Adjustment ViewSet
# ============================================================================

class StockAdjustmentViewSet(viewsets.ViewSet):
    """API endpoint for stock adjustments."""
    
    permission_classes = [permissions.IsAuthenticated, CanAdjustStock]
    
    @transaction.atomic
    def create(self, request):
        """Record adjustment"""
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            movement = StockAdjustmentService.adjust_stock(
                inventory_item=serializer.validated_data['inventory_item'],
                batch=serializer.validated_data['batch'],
                quantity_delta=serializer.validated_data['quantity_delta'],
                reason=serializer.validated_data['reason'],
                user=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            from sales.serializers import StockMovementSerializer
            return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Damage Recording ViewSet
# ============================================================================

class DamageRecordingViewSet(viewsets.ViewSet):
    """API endpoint for recording damage."""
    
    permission_classes = [permissions.IsAuthenticated, CanAdjustStock]
    
    @transaction.atomic
    def create(self, request):
        """Record damage"""
        serializer = DamageRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            movement = DamageService.record_damage(
                inventory_item=serializer.validated_data['inventory_item'],
                batch=serializer.validated_data['batch'],
                quantity=serializer.validated_data['quantity'],
                reason=serializer.validated_data['reason'],
                user=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            from sales.serializers import StockMovementSerializer
            return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Expiry Recording ViewSet
# ============================================================================

class ExpiryRecordingViewSet(viewsets.ViewSet):
    """API endpoint for recording expiry."""
    
    permission_classes = [permissions.IsAuthenticated, CanAdjustStock]
    
    @transaction.atomic
    def create(self, request):
        """Record expiry"""
        serializer = ExpiryRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            movement = ExpiryService.record_expiry_writeoff(
                inventory_item=serializer.validated_data['inventory_item'],
                batch=serializer.validated_data['batch'],
                quantity=serializer.validated_data['quantity'],
                reason=serializer.validated_data['reason'],
                user=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            from sales.serializers import StockMovementSerializer
            return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Loss Recording ViewSet
# ============================================================================

class LossRecordingViewSet(viewsets.ViewSet):
    """API endpoint for recording loss."""
    
    permission_classes = [permissions.IsAuthenticated, CanAdjustStock]
    
    @transaction.atomic
    def create(self, request):
        """Record loss"""
        serializer = LossRecordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            movement = LossService.record_loss(
                inventory_item=serializer.validated_data['inventory_item'],
                batch=serializer.validated_data['batch'],
                quantity=serializer.validated_data['quantity'],
                reason=serializer.validated_data['reason'],
                user=request.user,
                notes=serializer.validated_data.get('notes', '')
            )
            from sales.serializers import StockMovementSerializer
            return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# ============================================================================
# Stock Reconciliation ViewSet
# ============================================================================

class StockReconciliationViewSet(viewsets.ViewSet):
    """API endpoint for Stock Reconciliation."""
    
    permission_classes = [permissions.IsAuthenticated, CanReconcileStock]
    
    def get_queryset(self):
        user = self.request.user
        from pharmacy.models import PharmacyMembership
        
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return StockReconciliation.objects.all().select_related(
                'pharmacy', 'inventory_item', 'batch', 'counted_by', 'approved_by', 'reconciled_by'
            )
        
        if user.role == 'PHARMACY_OWNER':
            try:
                pharmacy = user.owned_pharmacy_brand
                return StockReconciliation.objects.filter(pharmacy=pharmacy).select_related(
                    'pharmacy', 'inventory_item', 'batch', 'counted_by', 'approved_by', 'reconciled_by'
                )
            except:
                return StockReconciliation.objects.none()
        
        memberships = PharmacyMembership.objects.filter(
            user=user, status='APPROVED'
        ).values_list('pharmacy_id', flat=True)
        
        return StockReconciliation.objects.filter(pharmacy_id__in=memberships).select_related(
            'pharmacy', 'inventory_item', 'batch', 'counted_by', 'approved_by', 'reconciled_by'
        )
    
    def list(self, request):
        """List reconciliations"""
        return Response(StockReconciliationListSerializer(self.get_queryset(), many=True).data)
    
    def retrieve(self, request, pk=None):
        """Get reconciliation"""
        obj = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(StockReconciliationDetailSerializer(obj).data)
    
    @action(detail=False, methods=['post'])
    @transaction.atomic
    def start(self, request):
        """Start count"""
        serializer = StockReconciliationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            reconciliation = StockReconciliationService.start_count(
                inventory_item=serializer.validated_data['inventory_item'],
                batch=serializer.validated_data['batch'],
                user=request.user
            )
            return Response(StockReconciliationDetailSerializer(reconciliation).data, status=status.HTTP_201_CREATED)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def count(self, request, pk=None):
        """Submit count"""
        reconciliation = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = StockReconciliationCountSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            reconciliation = StockReconciliationService.finalize_count(
                reconciliation,
                counted_quantity=serializer.validated_data['counted_quantity'],
                user=request.user
            )
            return Response(StockReconciliationDetailSerializer(reconciliation).data)
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def approve(self, request, pk=None):
        """Approve count"""
        reconciliation = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = StockReconciliationApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            reconciliation = StockReconciliationService.approve_count(
                reconciliation,
                user=request.user,
                notes=serializer.validated_data.get('approval_notes', '')
            )
            return Response(StockReconciliationDetailSerializer(reconciliation).data)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    @transaction.atomic
    def reconcile(self, request, pk=None):
        """Reconcile"""
        reconciliation = get_object_or_404(self.get_queryset(), pk=pk)
        
        try:
            reconciliation, movement = StockReconciliationService.reconcile(reconciliation, user=request.user)
            return Response(StockReconciliationDetailSerializer(reconciliation).data)
        except (PermissionError, ValueError) as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
