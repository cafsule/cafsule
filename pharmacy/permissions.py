from django.contrib.auth import get_user_model
from rest_framework.permissions import BasePermission
from .models import PharmacyMembership, PharmacyBrand

User = get_user_model()


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'SUPER_ADMIN')


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'PLATFORM_ADMIN')


class IsPharmacyOwner(BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.role == 'PHARMACY_OWNER')

    def has_object_permission(self, request, view, obj):
        # obj is PharmacyBrand
        return bool(request.user and request.user.is_authenticated and getattr(obj, 'owner_id', None) == request.user.id)


class IsPharmacyOwnerOrPlatformAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.role == 'PLATFORM_ADMIN' or request.user.role == 'SUPER_ADMIN':
            return True
        return bool(request.user and request.user.is_authenticated and getattr(obj, 'owner_id', None) == request.user.id)


class IsApprovedPharmacyMember(BasePermission):
    """Checks that the user has an APPROVED membership for the referenced pharmacy."""
    def has_object_permission(self, request, view, obj):
        # obj may be PharmacyBrand or PharmacyMembership
        pharmacy = obj if isinstance(obj, PharmacyBrand) else getattr(obj, 'pharmacy', None)
        if not pharmacy:
            return False
        if not pharmacy.is_verified:
            return False
        if not request.user or not request.user.is_authenticated:
            return False
        membership = PharmacyMembership.objects.filter(user=request.user, pharmacy=pharmacy, status='APPROVED').first()
        return bool(membership and request.user.is_active and request.user.is_verified)


class IsPharmacyMemberOrPlatformAdmin(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.role in ('PLATFORM_ADMIN', 'SUPER_ADMIN'):
            return True
        return IsApprovedPharmacyMember().has_object_permission(request, view, obj)


class CanManagePharmacyStaff(BasePermission):
    """
    Permission to manage (approve/reject/suspend) staff for a pharmacy.
    Only the pharmacy owner can manage staff for their own pharmacy.
    Platform admins can manage any pharmacy's staff.
    """
    def has_permission(self, request, view):
        # General permission check - must be authenticated
        return bool(request.user and request.user.is_authenticated)
    
    def has_object_permission(self, request, view, obj):
        # obj is PharmacyMembership
        if not isinstance(obj, PharmacyMembership):
            return False
        
        # Platform admins can always manage
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        # Only pharmacy owner can manage
        if request.user.role == 'PHARMACY_OWNER':
            return obj.pharmacy.owner_id == request.user.id
        
        # Other staff cannot manage memberships
        return False


class IsOwnPharmacyOwner(BasePermission):
    """
    Permission to access resources for one's own pharmacy.
    Pharmacy owners can only access their own pharmacy.
    Platform admins can access any pharmacy.
    """
    def has_object_permission(self, request, view, obj):
        # obj is PharmacyBrand
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        if request.user.role == 'PHARMACY_OWNER':
            return obj.owner_id == request.user.id
        
        return False
