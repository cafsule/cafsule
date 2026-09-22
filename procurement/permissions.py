from rest_framework.permissions import BasePermission


class CanManageProcurement(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and user.is_active and
            user.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER', 'PHARMACY_MANAGER'}
        )
