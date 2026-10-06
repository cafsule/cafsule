from django.urls import path
from .views import PharmacyMedicineViewSet, PlatformMedicineViewSet

urlpatterns = [
    path('medicines/', PharmacyMedicineViewSet.as_view({'get': 'list', 'post': 'create'}), name='global-medicines-list'),
    path('medicines/search/', PharmacyMedicineViewSet.as_view({'get': 'search'}), name='global-medicines-search'),
    path('medicines/<uuid:pk>/', PharmacyMedicineViewSet.as_view({'get': 'retrieve'}), name='global-medicines-detail'),
    path('admin/medicines/', PlatformMedicineViewSet.as_view({'get': 'list', 'post': 'create'}), name='platform-medicines-list'),
    path('admin/medicines/<uuid:pk>/', PlatformMedicineViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'put': 'update'}), name='platform-medicines-detail'),
]
