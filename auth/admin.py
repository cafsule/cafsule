from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, EmailVerificationToken, PasswordResetToken, UserActivityLog

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom admin interface for User model"""
    
    list_display = [
        'email', 'get_full_name', 'role', 'account_status',
        'is_verified', 'is_active', 'date_joined'
    ]
    list_filter = ['role', 'account_status', 'is_verified', 'is_active', 'is_staff']
    search_fields = ['email', 'first_name', 'last_name', 'phone_number']
    ordering = ['-date_joined']
    
    fieldsets = (
    (None, {'fields': ('email', 'password')}),
    (_('Personal info'), {
        'fields': ('first_name', 'last_name', 'phone_number')
    }),
    (_('Account status'), {
        'fields': ('role', 'account_status', 'is_verified')
    }),
    (_('Permissions'), {
        'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
    }),
    (_('OAuth'), {
        'fields': ('oauth_provider', 'oauth_provider_user_id')
    }),
    (_('Important dates'), {
        'fields': ('date_joined', 'last_login')
    }),
)
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ['date_joined', 'last_login']
    
    def get_full_name(self, obj):
        return obj.get_full_name()
    get_full_name.short_description = 'Full Name'

@admin.register(EmailVerificationToken)
class EmailVerificationTokenAdmin(admin.ModelAdmin):
    """Admin interface for EmailVerificationToken"""
    
    list_display = ['user', 'token', 'created_at', 'expires_at', 'is_used', 'is_active']
    list_filter = ['is_used', 'is_active', 'created_at']
    search_fields = ['user__email', 'token']
    ordering = ['-created_at']
    readonly_fields = ['user', 'token', 'created_at', 'expires_at']

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """Admin interface for PasswordResetToken"""
    
    list_display = ['user', 'token', 'created_at', 'expires_at', 'is_used', 'is_active']
    list_filter = ['is_used', 'is_active', 'created_at']
    search_fields = ['user__email', 'token']
    ordering = ['-created_at']
    readonly_fields = ['user', 'token', 'created_at', 'expires_at']

@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    """Admin interface for UserActivityLog"""
    
    list_display = ['user', 'action', 'created_at', 'ip_address']
    list_filter = ['action', 'created_at']
    search_fields = ['user__email', 'ip_address', 'user_agent']
    ordering = ['-created_at']
    readonly_fields = ['user', 'action', 'ip_address', 'user_agent', 'details', 'created_at']

from .models import OTPVerification

@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    """Admin interface for OTPVerification"""
    
    list_display = ['user', 'otp_code', 'otp_type', 'created_at', 'expires_at', 'is_used', 'is_active']
    list_filter = ['otp_type', 'is_used', 'is_active', 'created_at']
    search_fields = ['user__email', 'otp_code']
    ordering = ['-created_at']
    readonly_fields = ['user', 'otp_code', 'otp_type', 'created_at', 'expires_at']