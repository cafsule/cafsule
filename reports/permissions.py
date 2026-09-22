from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission

from pharmacy.models import PharmacyMembership

User = get_user_model()


class IsReportingAllowed(BasePermission):
    """Permission gate for pharmacy reporting endpoints."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True

        if request.user.role in ('PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            if request.user.role == 'PHARMACY_OWNER':
                return True
            return PharmacyMembership.objects.filter(
                user=request.user,
                status='APPROVED',
            ).exists()

        return False
