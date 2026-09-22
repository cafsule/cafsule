from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, generics, status
from rest_framework.views import APIView
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.contrib.gis.db.models.functions import Distance
from django.http import Http404
from django.conf import settings
from .models import PharmacyBrand, PharmacyBrandImage, PharmacyMembership, PharmacyVerificationDocument
from .serializers import (
    PharmacyBrandListSerializer, PharmacyBrandDetailSerializer, PharmacyBrandCreateSerializer, PharmacyBrandUpdateSerializer,
    PharmacyJoinPreviewSerializer, PharmacyMembershipRequestSerializer,
    PharmacyBrandImageSerializer, PharmacyMembershipSerializer, PharmacyMembershipApprovalSerializer,
    PharmacyVerificationDocumentSerializer,
)
from .permissions import IsSuperAdmin, IsPlatformAdmin, IsPharmacyOwner, IsPharmacyOwnerOrPlatformAdmin, IsApprovedPharmacyMember, CanManagePharmacyStaff, IsOwnPharmacyOwner
from .services import (
    submit_pharmacy_brand,
    start_pharmacy_review,
    approve_pharmacy_brand,
    reject_pharmacy_brand,
    suspend_pharmacy_brand,
    create_membership_request,
    approve_membership,
    reject_membership,
    suspend_membership,
    regenerate_pharmacy_id,
    repair_missing_pharmacy_ids,
)
from .validators import validate_latitude, validate_longitude, validate_radius_km

User = get_user_model()


class PharmacyBrandViewSet(viewsets.ModelViewSet):
    queryset = PharmacyBrand.objects.all().select_related('owner')
    permission_classes = [AllowAny]

    def get_serializer_class(self):
        if self.action == 'list':
            return PharmacyBrandListSerializer
        if self.action in ('retrieve',):
            if not self.request.user.is_authenticated or self.request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER'):
                return PharmacyBrandListSerializer
            return PharmacyBrandDetailSerializer
        if self.action == 'create':
            return PharmacyBrandCreateSerializer
        if self.action in ('partial_update', 'update'):
            return PharmacyBrandUpdateSerializer
        return PharmacyBrandDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        brand = serializer.save()
        detail_serializer = PharmacyBrandDetailSerializer(brand, context={'request': request})
        headers = self.get_success_headers(detail_serializer.data)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def get_permissions(self):
        if self.action == 'create':
            return [IsAuthenticated(), IsPharmacyOwner()]
        if self.action in ('partial_update', 'update', 'destroy'):
            return [IsAuthenticated(), IsOwnPharmacyOwner()]
        if self.action in ('approve', 'reject', 'suspend'):
            return [IsAuthenticated()]
        return [AllowAny()]

    def get_queryset(self):
        # Public listing only shows verified brands
        qs = super().get_queryset()
        if self.action == 'list':
            qs = qs.filter(verification_status='VERIFIED')
        elif self.action == 'membership_requests':
            return qs
        elif self.request.user.is_authenticated:
            if self.request.user.role == 'PHARMACY_OWNER':
                qs = qs.filter(owner=self.request.user)
            elif self.request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
                qs = qs.filter(verification_status='VERIFIED')
        else:
            qs = qs.filter(verification_status='VERIFIED')
        return qs

    def partial_update(self, request, *args, **kwargs):
        # Owners may update their brand
        instance = self.get_object()
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN') and instance.owner_id != request.user.id:
            return Response({'detail': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)
        return super().partial_update(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='submit-for-verification')
    def submit_for_verification(self, request, pk=None):
        try:
            brand = submit_pharmacy_brand(self.get_object(), request.user)
            return Response(PharmacyBrandDetailSerializer(brand).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'], url_path='pending-verification')
    def pending_verification(self, request):
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        brands = self.queryset.filter(verification_status__in=('PENDING_VERIFICATION', 'UNDER_REVIEW'))
        return Response(PharmacyBrandDetailSerializer(brands, many=True).data)

    @action(detail=True, methods=['post'], url_path='start-review')
    def start_review(self, request, pk=None):
        try:
            brand = start_pharmacy_review(self.get_object(), request.user)
            return Response(PharmacyBrandDetailSerializer(brand).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        brand = self.get_object()
        try:
            brand = approve_pharmacy_brand(brand, request.user)
            return Response(PharmacyBrandDetailSerializer(brand).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)

    @action(detail=False, methods=['get'], url_path='my-pharmacy-id')
    def my_pharmacy_id(self, request):
        if request.user.role != 'PHARMACY_OWNER':
            return Response({'detail': 'Only pharmacy owners can access a Pharmacy ID'}, status=status.HTTP_403_FORBIDDEN)
        brand = get_object_or_404(PharmacyBrand, owner=request.user)
        if brand.verification_status == 'VERIFIED' and not brand.pharmacy_id:
            repair_missing_pharmacy_ids(brand)
            brand.refresh_from_db()
        if brand.verification_status != 'VERIFIED' or not brand.pharmacy_id:
            return Response({'detail': 'Pharmacy ID is available after pharmacy approval'}, status=status.HTTP_404_NOT_FOUND)
        return Response({'pharmacy_id': brand.pharmacy_id})

    @action(detail=False, methods=['post'], url_path='regenerate-pharmacy-id')
    def regenerate_pharmacy_id(self, request):
        if request.user.role != 'PHARMACY_OWNER':
            return Response({'detail': 'Only pharmacy owners can regenerate a Pharmacy ID'}, status=status.HTTP_403_FORBIDDEN)
        brand = get_object_or_404(PharmacyBrand, owner=request.user)
        try:
            brand = regenerate_pharmacy_id(brand, request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'pharmacy_id': brand.pharmacy_id})

    @action(detail=True, methods=['get'], url_path='membership-requests')
    def membership_requests(self, request, pk=None):
        brand = self.get_object()
        # Only owner of this pharmacy and platform admins can see membership requests
        if not (request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN') or brand.owner_id == request.user.id):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        # Only fetch PENDING memberships to avoid exposing rejected/approved staff unnecessarily
        requests_qs = PharmacyMembership.objects.filter(pharmacy=brand, status='PENDING').select_related('user')
        from .serializers import PharmacyMembershipRequestSerializer
        return Response(PharmacyMembershipRequestSerializer(requests_qs, many=True).data)
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        brand = self.get_object()
        reason = request.data.get('reason', '')
        try:
            brand = reject_pharmacy_brand(brand, request.user, reason=reason)
            return Response(PharmacyBrandDetailSerializer(brand).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        brand = self.get_object()
        try:
            brand = suspend_pharmacy_brand(brand, request.user, reason=request.data.get('reason', ''))
            return Response(PharmacyBrandDetailSerializer(brand).data)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class PharmacySearchView(generics.ListAPIView):
    serializer_class = PharmacyBrandListSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        q = self.request.query_params.get('q', '').strip()
        qs = PharmacyBrand.objects.filter(verification_status='VERIFIED')
        if q:
            qs = qs.filter(Q(brand_name__icontains=q) | Q(legal_name__icontains=q) | Q(city__icontains=q) | Q(state__icontains=q))
        return qs


class PharmacyBrandImageViewSet(viewsets.ModelViewSet):
    serializer_class = PharmacyBrandImageSerializer
    permission_classes = [IsAuthenticated]
    queryset = PharmacyBrandImage.objects.select_related('brand', 'brand__owner')

    def get_queryset(self):
        user = self.request.user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return self.queryset
        return self.queryset.filter(brand__owner=user)

    def perform_create(self, serializer):
        serializer.save()


class PharmacyVerificationDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = PharmacyVerificationDocumentSerializer
    permission_classes = [IsAuthenticated]
    queryset = PharmacyVerificationDocument.objects.select_related('brand', 'brand__owner')

    def get_queryset(self):
        user = self.request.user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return self.queryset
        return self.queryset.filter(brand__owner=user)

    def perform_create(self, serializer):
        serializer.save()


class PharmacyNearbyView(generics.ListAPIView):
    serializer_class = PharmacyBrandListSerializer
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        lat = request.query_params.get('latitude')
        lng = request.query_params.get('longitude')
        radius = request.query_params.get('radius', '5')
        try:
            validate_latitude(lat)
            validate_longitude(lng)
            validate_radius_km(radius)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure PostGIS is available
        engine = settings.DATABASES.get('default', {}).get('ENGINE', '')
        if 'postgis' not in engine:
            return Response({'detail': 'Geospatial queries are not available on this database'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user_point = Point(float(lng), float(lat), srid=4326)
        except Exception:
            return Response({'detail': 'Invalid coordinates'}, status=status.HTTP_400_BAD_REQUEST)

        qs = PharmacyBrand.objects.filter(verification_status='VERIFIED', location__distance_lte=(user_point, D(km=float(radius))))
        qs = qs.annotate(distance=Distance('location', user_point)).order_by('distance')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


class PharmacyMembershipViewSet(viewsets.ModelViewSet):
    queryset = PharmacyMembership.objects.all().select_related('user', 'pharmacy')
    serializer_class = PharmacyMembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return self.queryset
        if self.action in ('approve', 'reject', 'suspend'):
            return self.queryset
        return self.queryset.filter(Q(user=user) | Q(pharmacy__owner=user)).distinct()

    def perform_create(self, serializer):
        # Use the serializer's create for validation then call service for business rules
        membership = serializer.save()
        return membership

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        membership = self.get_object()
        # Check permission
        if not CanManagePharmacyStaff().has_object_permission(request, self, membership):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        try:
            approve_membership(membership, request.user)
            return Response({'detail': 'Membership approved'})
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        membership = self.get_object()
        # Check permission
        if not CanManagePharmacyStaff().has_object_permission(request, self, membership):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({'detail': 'Rejection reason is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            reject_membership(membership, request.user, reason=reason)
            return Response({'detail': 'Membership rejected'})
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        membership = self.get_object()
        # Check permission
        if not CanManagePharmacyStaff().has_object_permission(request, self, membership):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)
        try:
            suspend_membership(membership, request.user)
            return Response({'detail': 'Membership suspended'})
        except ValueError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class MyPharmacyView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PharmacyBrandDetailSerializer

    def get_object(self):
        user = self.request.user
        brand = PharmacyBrand.objects.filter(owner=user).first()
        if not brand:
            membership = (
                PharmacyMembership.objects
                .filter(user=user, status='APPROVED')
                .select_related('pharmacy')
                .order_by('-created_at')
                .first()
            )
            if membership:
                brand = membership.pharmacy
            else:
                raise Http404('No owned pharmacy')
        if brand.verification_status == 'VERIFIED' and not brand.pharmacy_id:
            repair_missing_pharmacy_ids(brand)
            brand.refresh_from_db()
        return brand


class MyMembershipsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PharmacyMembershipSerializer

    def get_queryset(self):
        return PharmacyMembership.objects.filter(user=self.request.user)


class PharmacyJoinLookupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pharmacy_id = str(request.data.get('pharmacy_id', '')).strip().upper()
        if not pharmacy_id:
            return Response({'detail': 'That Pharmacy ID is not valid.'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.role not in dict(PharmacyMembership.ROLE_CHOICES):
            return Response({'detail': 'Only pharmacy employees can join a pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        if not request.user.is_active or not request.user.is_verified or request.user.account_status != 'ACTIVE':
            return Response({'detail': 'Your account must be active and verified before joining a pharmacy.'}, status=status.HTTP_403_FORBIDDEN)
        brand = PharmacyBrand.objects.filter(pharmacy_id=pharmacy_id, verification_status='VERIFIED').first()
        if not brand:
            return Response({'detail': 'That Pharmacy ID is not valid.'}, status=status.HTTP_404_NOT_FOUND)
        existing = PharmacyMembership.objects.filter(user=request.user, pharmacy=brand).first()
        if existing and existing.status == 'APPROVED':
            return Response({'detail': 'You are already a member of this pharmacy.'}, status=status.HTTP_409_CONFLICT)
        if existing and existing.status == 'PENDING':
            return Response({'detail': 'You already have a pending request to join this pharmacy.'}, status=status.HTTP_409_CONFLICT)
        return Response(PharmacyJoinPreviewSerializer(brand).data)


class PharmacyJoinRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        pharmacy_id = str(request.data.get('pharmacy_id', '')).strip().upper()
        brand = PharmacyBrand.objects.filter(pharmacy_id=pharmacy_id, verification_status='VERIFIED').first()
        if not brand:
            return Response({'detail': 'That Pharmacy ID is not valid.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            membership = create_membership_request(request.user, brand, request.user.role)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(PharmacyMembershipRequestSerializer(membership).data, status=status.HTTP_201_CREATED)
from django.shortcuts import render

# Create your views here.
