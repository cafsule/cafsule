"""Permission classes for the global medicine catalog and inventory management."""

from rest_framework.permissions import BasePermission
from django.contrib.auth import get_user_model

User = get_user_model()


class CanCreateMedicine(BasePermission):
    """Grant permission to create or manage global medicine catalog entries for pharmacy users."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role in ('PHARMACY_OWNER', 'PHARMACY_MANAGER')

    def has_object_permission(self, request, view, obj):
        pharmacy = getattr(obj, 'created_by_pharmacy', None)
        if not pharmacy:
            return False

        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id

        if request.user.role == 'PHARMACY_MANAGER':
            from pharmacy.models import PharmacyMembership
            return PharmacyMembership.objects.filter(
                user=request.user,
                pharmacy=pharmacy,
                status='APPROVED',
            ).exists()

        return False


class CanCreateAdminMedicine(BasePermission):
    """Platform admin-only medicine creation permission."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        return request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN')

    def has_object_permission(self, request, view, obj):
        return request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN')


class CanViewMedicine(BasePermission):
    """Authenticated users can view the global medicine catalog."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class CanManagePharmacyInventory(BasePermission):
    """
    Permission to manage inventory for a specific pharmacy.
    
    PHARMACY_OWNER can manage their own pharmacy's inventory.
    PHARMACY_MANAGER with explicit permission can manage inventory.
    PHARMACIST with explicit permission can manage inventory.
    PHARMACY_STAFF with explicit permission can manage inventory.
    Platform admins can manage any pharmacy's inventory.
    """
    def has_permission(self, request, view):
        # General permission check
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Platform admins have full access
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        # Non-platform users must have approved membership
        # This is validated at object level
        return request.user.role in ('PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF')
    
    def has_object_permission(self, request, view, obj):
        # obj is PharmacyInventoryItem
        from pharmacy.models import PharmacyMembership
        
        # Platform admins have full access
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        pharmacy = obj.pharmacy
        
        # Owner can manage their own pharmacy
        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id
        
        # Other staff must have APPROVED membership
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=pharmacy,
            status='APPROVED'
        ).first()
        
        return bool(membership)


class CanPublishInventory(BasePermission):
    """
    Permission to publish inventory items.
    
    Publication requires:
    - Ownership/membership of the pharmacy
    - Pharmacy must be VERIFIED
    - Inventory item must meet publication requirements
    """
    def has_permission(self, request, view):
        # General permission check
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Platform admins can publish
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        return request.user.role == 'PHARMACY_OWNER'
    
    def has_object_permission(self, request, view, obj):
        # obj is PharmacyInventoryItem
        from pharmacy.models import PharmacyMembership
        
        pharmacy = obj.pharmacy
        
        # Platform admins can always publish
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        # Pharmacy must be VERIFIED
        if pharmacy.verification_status != 'VERIFIED':
            return False
        
        # Owner can publish their own pharmacy
        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id
        
        return False
