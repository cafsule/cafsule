from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PharmacyInventoryViewSet, InventoryBatchViewSet,
    CustomerReturnViewSet, InventoryHoldViewSet,
    StockAdjustmentViewSet, DamageRecordingViewSet,
    ExpiryRecordingViewSet, LossRecordingViewSet,
    StockReconciliationViewSet, PublicInventoryViewSet
)

router = DefaultRouter()
router.register(r'items', PharmacyInventoryViewSet, basename='inventory-item')
router.register(r'batches', InventoryBatchViewSet, basename='inventory-batch')
router.register(r'returns', CustomerReturnViewSet, basename='customer-return')
router.register(r'holds', InventoryHoldViewSet, basename='inventory-hold')
router.register(r'adjustments', StockAdjustmentViewSet, basename='stock-adjustment')
router.register(r'damage', DamageRecordingViewSet, basename='damage-recording')
router.register(r'expiry', ExpiryRecordingViewSet, basename='expiry-recording')
router.register(r'loss', LossRecordingViewSet, basename='loss-recording')
router.register(r'reconciliations', StockReconciliationViewSet, basename='stock-reconciliation')
router.register(r'public', PublicInventoryViewSet, basename='public-inventory')

urlpatterns = [
    path('', include(router.urls)),
]
