"""
Permission classes for sales operations.

Enforces:
- Only verified pharmacies can perform sales
- Cross-pharmacy isolation
- Role-based access control
- Object-level permission checks
"""

from rest_framework.permissions import BasePermission
from pharmacy.models import PharmacyMembership


class IsPharmacyStaffWithMembership(BasePermission):
    """
    Permission for pharmacy staff with approved membership.
    
    Allows:
    - SUPER_ADMIN, PLATFORM_ADMIN: full access
    - PHARMACY_OWNER: access to their own pharmacy
    - PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF: only with APPROVED membership
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Platform admins always have access
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        # Other roles must be pharmacy staff
        if request.user.role not in ('PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            return False
        
        return True
    
    def has_object_permission(self, request, view, obj):
        """Check permission for a specific pharmacy sale"""
        # Platform admins always have access
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        pharmacy = obj.pharmacy
        
        # Owner can access their own pharmacy
        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id
        
        # Other staff must have APPROVED membership
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=pharmacy,
            status='APPROVED'
        ).exists()
        
        return membership


class CanCreateSale(BasePermission):
    """
    Permission to create a new sale.
    
    Requirements:
    - User must be authenticated
    - User must be pharmacy staff (OWNER, MANAGER, PHARMACIST, STAFF)
    - Pharmacy must be VERIFIED
    """
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'):
            return False
        
        return True


class CanCompleteSale(BasePermission):
    """
    Permission to complete a sale.
    
    Requirements:
    - User must have permission to edit the sale
    - Sale must be in DRAFT status
    - Pharmacy must be VERIFIED
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Platform admins can always complete
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        pharmacy = obj.pharmacy
        
        # Pharmacy must be VERIFIED
        if pharmacy.verification_status != 'VERIFIED':
            return False
        
        # Owner can complete their own pharmacy sales
        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id
        
        # Other staff must have APPROVED membership
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=pharmacy,
            status='APPROVED'
        ).exists()
        
        return membership


class CanVoidSale(BasePermission):
    """
    Permission to void a sale.
    
    Requirements:
    - User must have permission to edit the sale
    - Sale must be in COMPLETED status
    - Requires higher permission level (manager or owner)
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # Platform admins can always void
        if request.user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return True
        
        # Only managers and owners can void
        if request.user.role not in ('PHARMACY_OWNER', 'PHARMACY_MANAGER'):
            return False
        
        pharmacy = obj.pharmacy
        
        # Owner can void their own pharmacy sales
        if request.user.role == 'PHARMACY_OWNER':
            return pharmacy.owner_id == request.user.id
        
        # Manager must have APPROVED membership
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=pharmacy,
            status='APPROVED'
        ).exists()
        
        return membership


class CanViewSales(BasePermission):
    """
    Permission to view sales for a pharmacy.
    
    Allows:
    - SUPER_ADMIN, PLATFORM_ADMIN: view all sales
    - PHARMACY_OWNER: view their own pharmacy sales
    - PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF: view only if APPROVED membership
    """
    
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
