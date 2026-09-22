from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Note: Medicine endpoints are now accessed through pharmacy-specific routes
# GET /api/pharmacy/brands/{pharmacy_id}/medicines/ - List pharmacy medicines
# POST /api/pharmacy/brands/{pharmacy_id}/medicines/ - Create medicine
# GET /api/pharmacy/brands/{pharmacy_id}/medicines/{id}/ - Get medicine
# PATCH /api/pharmacy/brands/{pharmacy_id}/medicines/{id}/ - Update medicine
# DELETE /api/pharmacy/brands/{pharmacy_id}/medicines/{id}/ - Delete medicine

urlpatterns = [
    # All medicine endpoints are now managed through pharmacy routes
    # See pharmacy/urls.py for the medicine endpoints
]
