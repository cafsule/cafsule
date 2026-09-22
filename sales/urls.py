"""
URL configuration for Sales API endpoints.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SaleViewSet, CustomerViewSet

router = DefaultRouter()
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'customers', CustomerViewSet, basename='customer')

app_name = 'sales'

urlpatterns = [
    path('', include(router.urls)),
]
