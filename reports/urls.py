from django.urls import path

from .views import (
    DashboardSummaryView,
    DailySalesReportView,
    InventorySummaryView,
    InventoryCurrentStockView,
    InventoryMovementReportView,
    PaymentMethodSummaryView,
    ProductSalesReportView,
    DailyOperationsSummaryView,
    LowStockReportView,
    ExpiryReportView,
    TopSellingMedicinesReportView,
)

urlpatterns = [
    path('dashboard/', DashboardSummaryView.as_view(), name='dashboard-summary'),
    path('sales/payment-methods/', PaymentMethodSummaryView.as_view(), name='sales-payment-methods'),
    path('sales/daily/', DailySalesReportView.as_view(), name='sales-daily'),
    path('sales/products/', ProductSalesReportView.as_view(), name='sales-products'),
    path('operations/summary/', DailyOperationsSummaryView.as_view(), name='operations-summary'),
    path('inventory/summary/', InventorySummaryView.as_view(), name='inventory-summary'),
    path('inventory/current-stock/', InventoryCurrentStockView.as_view(), name='inventory-current-stock'),
    path('inventory/movements/', InventoryMovementReportView.as_view(), name='inventory-movements'),
    path('inventory/low-stock/', LowStockReportView.as_view(), name='inventory-low-stock'),
    path('inventory/expiry/', ExpiryReportView.as_view(), name='inventory-expiry'),
    path('sales/top-selling/', TopSellingMedicinesReportView.as_view(), name='sales-top-selling'),
]
