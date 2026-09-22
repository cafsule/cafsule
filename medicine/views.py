"""
Medicine Catalog ViewSets and Views

Each pharmacy manages their own medicine catalog independently.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from django.shortcuts import get_object_or_404

from pharmacy.models import PharmacyBrand, PharmacyMembership
from .models import Medicine
from .serializers import (
    MedicineListSerializer, MedicineDetailSerializer,
    MedicineCreateSerializer, MedicineUpdateSerializer
)
from .permissions import CanCreateMedicine, CanViewMedicine


class PharmacyMedicineViewSet(viewsets.ModelViewSet):
    """
    API endpoint for Pharmacy-specific medicines.
    
    GET /api/pharmacy/{pharmacy_id}/medicines/ - List pharmacy's medicines
    POST /api/pharmacy/{pharmacy_id}/medicines/ - Create medicine (owner only)
    GET /api/pharmacy/{pharmacy_id}/medicines/{id}/ - Get medicine details
    PATCH /api/pharmacy/{pharmacy_id}/medicines/{id}/ - Update medicine (owner only)
    DELETE /api/pharmacy/{pharmacy_id}/medicines/{id}/ - Delete medicine (owner only)
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    def get_pharmacy(self):
        """Get the pharmacy from URL parameter"""
        pharmacy_id = self.kwargs.get('pharmacy_id')
        return get_object_or_404(PharmacyBrand, id=pharmacy_id)
    
    def get_serializer_class(self):
        if self.action == 'list':
            return MedicineListSerializer
        elif self.action == 'retrieve':
            return MedicineDetailSerializer
        elif self.action == 'create':
            return MedicineCreateSerializer
        elif self.action in ('update', 'partial_update'):
            return MedicineUpdateSerializer
        return MedicineDetailSerializer
    
    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [CanCreateMedicine()]
        return [CanViewMedicine()]
    
    def get_queryset(self):
        pharmacy = self.get_pharmacy()
        qs = Medicine.objects.filter(pharmacy=pharmacy)
        
        # Allow search by generic name or brand name
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(generic_name__icontains=search) |
                Q(brand_name__icontains=search) |
                Q(strength__icontains=search)
            )
        
        return qs.order_by('generic_name', 'strength')
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['pharmacy'] = self.get_pharmacy()
        return context

    def user_has_access_to_pharmacy(self, pharmacy):
        user = self.request.user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        if user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == user.id
        if user.role == 'PHARMACY_MANAGER':
            return PharmacyMembership.objects.filter(
                user=user,
                pharmacy=pharmacy,
                status='APPROVED',
            ).exists()
        return False

    def create(self, request, *args, **kwargs):
        pharmacy = self.get_pharmacy()
        if not self.user_has_access_to_pharmacy(pharmacy):
            return Response({'detail': 'You do not have access to this pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        pharmacy = self.get_pharmacy()
        if not self.user_has_access_to_pharmacy(pharmacy):
            return Response({'detail': 'You do not have access to this pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        pharmacy = self.get_pharmacy()
        if not self.user_has_access_to_pharmacy(pharmacy):
            return Response({'detail': 'You do not have access to this pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        pharmacy = self.get_pharmacy()
        if not self.user_has_access_to_pharmacy(pharmacy):
            return Response({'detail': 'You do not have access to this pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save()

    def perform_update(self, serializer):
        serializer.save()

    @action(detail=False, methods=['get'])
    def search(self, request, **kwargs):
        """
        Search for medicines by name/strength within this pharmacy.
        
        Query parameters:
            q: search term (generic name, brand name, or strength)
        """
        search_term = request.query_params.get('q', '').strip()
        
        if not search_term or len(search_term) < 2:
            return Response(
                {'detail': 'Search term must be at least 2 characters'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        pharmacy = self.get_pharmacy()
        limit_param = request.query_params.get('limit', '20')
        try:
            limit = min(max(int(limit_param), 1), 50)
        except (TypeError, ValueError):
            limit = 20

        medicines = Medicine.objects.filter(
            pharmacy=pharmacy
        ).filter(
            Q(generic_name__icontains=search_term) |
            Q(brand_name__icontains=search_term) |
            Q(strength__icontains=search_term)
        ).order_by('generic_name', 'strength')[:limit]
        
        serializer = MedicineListSerializer(medicines, many=True)
        return Response(serializer.data)
