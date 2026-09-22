from rest_framework import permissions

class IsAuthenticatedAndActive(permissions.BasePermission):
    """Permission check for authenticated and active users"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_active and 
            request.user.account_status == 'ACTIVE'
        )

class IsOwnerOrReadOnly(permissions.BasePermission):
    """Object-level permission to only allow owners to edit their own objects"""
    
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write permissions are only allowed to the owner
        return obj == request.user

class IsAdminUser(permissions.BasePermission):
    """Permission check for admin users"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            (
                request.user.is_superuser or 
                request.user.role in ['SUPER_ADMIN', 'PLATFORM_ADMIN']
            )
        )

class IsSuperAdmin(permissions.BasePermission):
    """Permission check for super admin users"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.is_superuser
        )

class IsPharmacyAdmin(permissions.BasePermission):
    """Permission check for pharmacy admin roles"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.role in [
                'PHARMACY_OWNER', 
                'PHARMACY_MANAGER'
            ]
        )

class IsPharmacyStaff(permissions.BasePermission):
    """Permission check for pharmacy staff roles"""
    
    def has_permission(self, request, view):
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.role in [
                'PHARMACY_OWNER', 
                'PHARMACY_MANAGER', 
                'PHARMACIST', 
                'PHARMACY_STAFF'
            ]
        )
class IsPharmacyOwner(permissions.BasePermission):
    """Permission check for pharmacy owners"""
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.role == 'PHARMACY_OWNER' and
            request.user.is_approved and
            request.user.is_active and
            request.user.account_status == 'ACTIVE'
        )

class IsApprovedUser(permissions.BasePermission):
    """Permission check for approved users"""
    
    def has_permission(self, request, view):
        return (
            request.user and
            request.user.is_authenticated and
            request.user.is_approved and
            request.user.is_active
        )


class CanAdjustStock(permissions.BasePermission):
    """Permission check for stock adjustment operations"""
    
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_active):
            return False
        
        # Super admins and platform admins can always adjust stock
        if request.user.role in ['SUPER_ADMIN', 'PLATFORM_ADMIN']:
            return True
        
        # Pharmacy owners and managers can adjust stock in their pharmacy
        if request.user.role in ['PHARMACY_OWNER', 'PHARMACY_MANAGER']:
            return True
        
        return False


class CanReconcileStock(permissions.BasePermission):
    """Permission check for stock reconciliation operations"""
    
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_active):
            return False
        
        # Super admins and platform admins can reconcile
        if request.user.role in ['SUPER_ADMIN', 'PLATFORM_ADMIN']:
            return True
        
        # Pharmacy owners and managers can reconcile in their pharmacy
        if request.user.role in ['PHARMACY_OWNER', 'PHARMACY_MANAGER']:
            return True
        
        return False


class CanProcessReturns(permissions.BasePermission):
    """Permission check for customer return processing"""
    
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and request.user.is_active):
            return False
        
        # Super admins and platform admins can process returns
        if request.user.role in ['SUPER_ADMIN', 'PLATFORM_ADMIN']:
            return True
        
        # Staff can initiate returns, managers/owners can approve
        if request.user.role in ['PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF']:
            return True
        
        return False