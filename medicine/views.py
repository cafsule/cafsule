"""Views for the global medicine catalog and legacy pharmacy-compatible routes."""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Q
from django.shortcuts import get_object_or_404

from pharmacy.models import PharmacyBrand, PharmacyMembership
from pharmacy.pagination import StandardResultsSetPagination
from .models import Medicine
from .serializers import (
    AdminMedicineSerializer,
    MedicineCreateSerializer,
    MedicineDetailSerializer,
    MedicineListSerializer,
    MedicineUpdateSerializer,
    PharmacyMedicineSerializer,
)
from .permissions import CanCreateAdminMedicine, CanCreateMedicine, CanViewMedicine

ADMIN_ROLES = {'SUPER_ADMIN', 'PLATFORM_ADMIN'}
PHARMACY_CREATE_ROLES = {'PHARMACY_OWNER', 'PHARMACY_MANAGER'}


class PlatformMedicineViewSet(viewsets.ModelViewSet):
    """Admin-only global medicine catalog for platform administrators."""

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    queryset = Medicine.objects.select_related('created_by', 'created_by_pharmacy')

    def get_queryset(self):
        if self.request.user.role not in ADMIN_ROLES:
            return Medicine.objects.none()

        queryset = Medicine.objects.select_related('created_by', 'created_by_pharmacy')
        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(generic_name__icontains=search)
                | Q(brand_name__icontains=search)
                | Q(strength__icontains=search)
                | Q(manufacturer__icontains=search)
                | Q(nafdac_registration__icontains=search)
            )
        return queryset.order_by('generic_name', 'strength')

    def get_serializer_class(self):
        if self.action in ('update', 'partial_update'):
            return MedicineUpdateSerializer
        return AdminMedicineSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated(), CanCreateAdminMedicine()]
        return [permissions.IsAuthenticated(), CanViewMedicine()]

    def create(self, request, *args, **kwargs):
        serializer = MedicineCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        medicine = serializer.save()
        response_serializer = AdminMedicineSerializer(medicine, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PharmacyMedicineViewSet(viewsets.ModelViewSet):
    """Compatibility view for pharmacy-side medicine search and creation.

    This keeps the legacy pharmacy routes working while treating medicine as a
    global catalog record instead of a pharmacy-owned entity.
    """

    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    queryset = Medicine.objects.all()

    def get_pharmacy(self):
        pharmacy_id = self.kwargs.get('pharmacy_id')
        if not pharmacy_id:
            return None
        return get_object_or_404(PharmacyBrand, id=pharmacy_id)

    def user_has_access_to_pharmacy(self, pharmacy):
        if pharmacy is None:
            return False

        user = self.request.user
        if user.role in ADMIN_ROLES:
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

    def resolve_created_by_pharmacy(self):
        user = self.request.user
        if user.role in ADMIN_ROLES:
            return None

        pharmacy_id = self.kwargs.get('pharmacy_id') or self.request.query_params.get('pharmacy_id')
        pharmacy = get_object_or_404(PharmacyBrand, id=pharmacy_id) if pharmacy_id else None
        if pharmacy is not None and self.user_has_access_to_pharmacy(pharmacy):
            return pharmacy
        if user.role == 'PHARMACY_OWNER' and getattr(user, 'owned_pharmacy_brand', None):
            return user.owned_pharmacy_brand

        memberships = PharmacyMembership.objects.filter(
            user=user,
            status='APPROVED',
        ).select_related('pharmacy').order_by('pharmacy__brand_name')
        if memberships.count() == 1:
            return memberships.first().pharmacy
        return None

    def get_queryset(self):
        queryset = Medicine.objects.all()
        if self.action == 'retrieve' and self.request.user.role in ADMIN_ROLES:
            queryset = queryset.select_related('created_by', 'created_by_pharmacy')
        search = self.request.query_params.get('search', '').strip() or self.request.query_params.get('q', '').strip()
        if search:
            queryset = queryset.filter(
                Q(generic_name__icontains=search)
                | Q(brand_name__icontains=search)
                | Q(strength__icontains=search)
                | Q(manufacturer__icontains=search)
            )
        return queryset.order_by('generic_name', 'strength')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.action == 'create':
            context['created_by_pharmacy'] = self.resolve_created_by_pharmacy()
            context['source'] = 'PHARMACY' if context['created_by_pharmacy'] else None
        return context

    def get_serializer_class(self):
        if self.action == 'create':
            return MedicineCreateSerializer
        if self.action == 'retrieve':
            return AdminMedicineSerializer if self.request.user.role in ADMIN_ROLES else PharmacyMedicineSerializer
        return MedicineListSerializer

    def get_permissions(self):
        if self.action in ('create', 'update', 'partial_update', 'destroy'):
            return [permissions.IsAuthenticated(), CanCreateMedicine()]
        return [permissions.IsAuthenticated(), CanViewMedicine()]

    def create(self, request, *args, **kwargs):
        if request.user.role in ADMIN_ROLES:
            return Response({'detail': 'Use the admin medicine endpoint to create a catalog record as an administrator.'}, status=status.HTTP_403_FORBIDDEN)

        pharmacy = self.resolve_created_by_pharmacy()
        if not pharmacy:
            return Response({'detail': 'A valid pharmacy context with approved access is required. Provide pharmacy_id when you belong to multiple pharmacies.'}, status=status.HTTP_403_FORBIDDEN)
        if not self.user_has_access_to_pharmacy(pharmacy):
            return Response({'detail': 'You do not have access to this pharmacy.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data, context={'request': request, 'created_by_pharmacy': pharmacy})
        serializer.is_valid(raise_exception=True)
        medicine = serializer.save()
        response_serializer = PharmacyMedicineSerializer(medicine, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'])
    def search(self, request, **kwargs):
        search_term = request.query_params.get('q', '').strip() or request.query_params.get('search', '').strip()
        if not search_term or len(search_term) < 2:
            return Response({'detail': 'Search term must be at least 2 characters'}, status=status.HTTP_400_BAD_REQUEST)

        limit_param = request.query_params.get('limit', '20')
        try:
            limit = min(max(int(limit_param), 1), 50)
        except (TypeError, ValueError):
            limit = 20

        medicines = self.get_queryset().filter(
            Q(generic_name__icontains=search_term)
            | Q(brand_name__icontains=search_term)
            | Q(strength__icontains=search_term)
            | Q(manufacturer__icontains=search_term)
        )[:limit]
        serializer = MedicineListSerializer(medicines, many=True)
        return Response(serializer.data)
