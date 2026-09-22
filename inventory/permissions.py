"""
Permission classes for inventory management.

Enforces:
- Only pharmacy owners/staff can manage their own pharmacy inventory
- Only VERIFIED pharmacies can publish inventory
- Cross-pharmacy isolation (owner A cannot see owner B's inventory)
"""

from rest_framework.permissions import BasePermission
from pharmacy.models import PharmacyMembership


class CanManagePharmacyInventory(BasePermission):
    """
    Allow only pharmacy owner or approved staff to manage inventory.
    
    Rules:
    - PHARMACY_OWNER must own the pharmacy
    - Other roles must have APPROVED PharmacyMembership for that pharmacy
    - PLATFORM_ADMIN can manage any inventory
    """
    
    message = "You do not have permission to manage this pharmacy's inventory."
    
    def has_permission(self, request, view):
        # Platform admin can do anything
        if request.user.role == 'PLATFORM_ADMIN':
            return True
        
        # Pharmacy owner can manage
        if request.user.role == 'PHARMACY_OWNER':
            return True
        
        # Other roles must have pharmacy membership
        if hasattr(request.user, 'memberships'):
            return request.user.memberships.filter(
                status='APPROVED'
            ).exists()
        
        return False
    
    def has_object_permission(self, request, view, obj):
        # Platform admin can access any object
        if request.user.role == 'PLATFORM_ADMIN':
            return True
        
        # Pharmacy owner must own this pharmacy
        if request.user.role == 'PHARMACY_OWNER':
            return obj.pharmacy.owner_id == request.user.id
        
        # Other staff must have APPROVED membership for this pharmacy
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=obj.pharmacy,
            status='APPROVED'
        ).exists()
        
        return membership


class CanPublishInventory(BasePermission):
    """
    Allow publishing only for VERIFIED pharmacies.
    
    Additional to CanManagePharmacyInventory:
    - Pharmacy must have verification_status='VERIFIED'
    """
    
    message = "Only verified pharmacies can publish inventory."
    
    def has_permission(self, request, view):
        # Platform admin can do anything
        if request.user.role == 'PLATFORM_ADMIN':
            return True
        
        # Pharmacy owner can manage
        if request.user.role == 'PHARMACY_OWNER':
            return True
        
        # Other roles must have pharmacy membership
        if hasattr(request.user, 'memberships'):
            return request.user.memberships.filter(
                status='APPROVED'
            ).exists()
        
        return False
    
    def has_object_permission(self, request, view, obj):
        # Platform admin can access any object
        if request.user.role == 'PLATFORM_ADMIN':
            return True
        
        # Pharmacy must be VERIFIED
        if obj.pharmacy.verification_status != 'VERIFIED':
            return False
        
        # Pharmacy owner must own this pharmacy
        if request.user.role == 'PHARMACY_OWNER':
            return obj.pharmacy.owner_id == request.user.id
        
        # Other staff must have APPROVED membership for this pharmacy
        membership = PharmacyMembership.objects.filter(
            user=request.user,
            pharmacy=obj.pharmacy,
            status='APPROVED'
        ).exists()
        
        return membership
