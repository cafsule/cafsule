from django.urls import path, include, re_path
from rest_framework.routers import DefaultRouter
from .views import (
    PharmacyBrandViewSet,
    PharmacyBrandImageViewSet,
    PharmacyMembershipViewSet,
    PharmacyVerificationDocumentViewSet,
    MyPharmacyView,
    MyMembershipsView,
    PharmacySearchView,
    PharmacyJoinLookupView,
    PharmacyJoinRequestView,
)
from medicine.views import PharmacyMedicineViewSet

# Main router for pharmacy endpoints
router = DefaultRouter()
router.register(r'brands', PharmacyBrandViewSet, basename='pharmacybrand')
router.register(r'brand-images', PharmacyBrandImageViewSet, basename='pharmacybrandimage')
router.register(r'memberships', PharmacyMembershipViewSet, basename='pharmacymembership')
router.register(r'verification-documents', PharmacyVerificationDocumentViewSet, basename='pharmacyverificationdocument')

urlpatterns = [
    path('brands/search/', PharmacySearchView.as_view(), name='pharmacy-search'),
    path('', include(router.urls)),
    # Nested routes for pharmacy medicines
    path('brands/<uuid:pharmacy_id>/medicines/', PharmacyMedicineViewSet.as_view({'get': 'list', 'post': 'create'}), name='pharmacy-medicines-list'),
    path('brands/<uuid:pharmacy_id>/medicines/<uuid:pk>/', PharmacyMedicineViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'put': 'update', 'delete': 'destroy'}), name='pharmacy-medicines-detail'),
    path('brands/<uuid:pharmacy_id>/medicines/search/', PharmacyMedicineViewSet.as_view({'get': 'search'}), name='pharmacy-medicines-search'),
    path('my-pharmacy/', MyPharmacyView.as_view(), name='my-pharmacy'),
    path('my-memberships/', MyMembershipsView.as_view(), name='my-memberships'),
    path('join/lookup/', PharmacyJoinLookupView.as_view(), name='pharmacy-join-lookup'),
    path('join/request/', PharmacyJoinRequestView.as_view(), name='pharmacy-join-request'),
]
