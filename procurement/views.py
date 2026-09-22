from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Purchase, Supplier
from .permissions import CanManageProcurement
from .serializers import (
    PurchaseCreateSerializer,
    PurchaseDetailSerializer,
    PurchaseListSerializer,
    ReceivePurchaseSerializer,
    SupplierSerializer,
)
from .services import PurchaseService, resolve_pharmacy, scoped_purchase_queryset, scoped_supplier_queryset


class SupplierViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated, CanManageProcurement)
    serializer_class = SupplierSerializer

    def get_queryset(self):
        queryset = scoped_supplier_queryset(self.request.user)
        search = self.request.query_params.get('search', '').strip()
        status_filter = self.request.query_params.get('status', '').strip()
        if search:
            from django.db.models import Q
            queryset = queryset.filter(Q(name__icontains=search) | Q(contact_person__icontains=search) | Q(phone__icontains=search) | Q(email__icontains=search))
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        return queryset

    def perform_create(self, serializer):
        requested_pharmacy = self.request.data.get('pharmacy_id')
        pharmacy = resolve_pharmacy(self.request.user, requested_pharmacy)
        if pharmacy.verification_status != 'VERIFIED':
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'Suppliers require a VERIFIED pharmacy'})
        serializer.save(pharmacy=pharmacy, created_by=self.request.user)


class PurchaseViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated, CanManageProcurement)

    def get_queryset(self):
        queryset = scoped_purchase_queryset(self.request.user)
        status_filter = self.request.query_params.get('status', '').strip()
        supplier = self.request.query_params.get('supplier', '').strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if supplier:
            queryset = queryset.filter(supplier_id=supplier)
        return queryset

    def get_serializer_class(self):
        if self.action == 'list':
            return PurchaseListSerializer
        if self.action == 'create':
            return PurchaseCreateSerializer
        if self.action == 'receive':
            return ReceivePurchaseSerializer
        return PurchaseDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pharmacy = resolve_pharmacy(request.user, serializer.validated_data.pop('pharmacy_id', None))
        supplier = serializer.validated_data.pop('supplier')
        try:
            purchase = PurchaseService.create_purchase(
                user=request.user,
                pharmacy=pharmacy,
                supplier=supplier,
                **serializer.validated_data,
            )
        except (PermissionError, ValueError) as error:
            return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PurchaseDetailSerializer(purchase).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=('post',))
    def submit(self, request, pk=None):
        purchase = self.get_object()
        try:
            purchase = PurchaseService.submit(purchase, request.user)
        except ValueError as error:
            return Response({'detail': str(error)}, status=status.HTTP_409_CONFLICT)
        return Response(PurchaseDetailSerializer(purchase).data)

    @action(detail=True, methods=('post',))
    def receive(self, request, pk=None):
        purchase = self.get_object()
        serializer = ReceivePurchaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item_id = serializer.validated_data.pop('item_id')
        item = purchase.items.filter(pk=item_id).first()
        if item is None:
            return Response({'detail': 'Purchase item could not be found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            PurchaseService.receive(purchase=purchase, purchase_item=item, user=request.user, **serializer.validated_data)
        except (PermissionError, ValueError, IntegrityError) as error:
            return Response({'detail': str(error)}, status=status.HTTP_409_CONFLICT)
        return Response(PurchaseDetailSerializer(self.get_queryset().get(pk=purchase.pk)).data)

    @action(detail=True, methods=('post',))
    def cancel(self, request, pk=None):
        purchase = self.get_object()
        if purchase.status not in ('DRAFT', 'SUBMITTED'):
            return Response({'detail': 'Only open purchases can be cancelled.'}, status=status.HTTP_409_CONFLICT)
        purchase.status = 'CANCELLED'
        purchase.save(update_fields=('status', 'updated_at'))
        return Response(PurchaseDetailSerializer(purchase).data)
