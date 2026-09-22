import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
class UserManager(BaseUserManager):
    """Custom user manager for the User model"""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and save a regular user"""
        if not email:
            raise ValueError('Email address is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('account_status', 'ACTIVE')
        extra_fields.setdefault('role', 'SUPER_ADMIN')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model with email as primary identifier"""
    
    # User roles
    ROLE_CHOICES = (
        ('SUPER_ADMIN', 'Super Admin'),
        ('PLATFORM_ADMIN', 'Platform Admin'),
        ('PHARMACY_OWNER', 'Pharmacy Owner'),
        ('PHARMACY_MANAGER', 'Pharmacy Manager'),
        ('PHARMACIST', 'Pharmacist'),
        ('PHARMACY_STAFF', 'Pharmacy Staff'),
    )
    
    # Account status
    ACCOUNT_STATUS_CHOICES = (
        ('ACTIVE', 'Active'),
        ('UNVERIFIED', 'Unverified'),
        ('PENDING_APPROVAL', 'Pending Approval'),  # Add this
        ('SUSPENDED', 'Suspended'),
        ('DEACTIVATED', 'Deactivated'),
        ('REJECTED', 'Rejected'),  # Add this
    )
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, max_length=255)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(
        max_length=17,
        blank=True,
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message="Phone number must be in E.164 format: +234XXXXXXXXXX"
            )
        ]
    )
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='auth_app_users',  # Changed from default
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='auth_app_users',  # Changed from default
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions',
    )
    
    # Django fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_users'
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    # NOTE: `pharmacy_brand` relationship has been moved into the
    # `pharmacy.PharmacyMembership` model. Do NOT re-add a direct
    # ForeignKey from User to PharmacyBrand. See pharmacy.models.PharmacyMembership.

    # Role and status
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='PHARMACY_STAFF')
    account_status = models.CharField(
        max_length=20,
        choices=ACCOUNT_STATUS_CHOICES,
        default='UNVERIFIED'
    )
    
    # OAuth fields
    oauth_provider = models.CharField(max_length=50, blank=True, null=True)
    oauth_provider_user_id = models.CharField(max_length=255, blank=True, null=True)

    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']
    
    class Meta:
        db_table = 'auth_app_user'  # Changed from 'auth_user'
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['account_status']),
        ]
    
    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()
    
    def get_short_name(self):
        return self.first_name
    
    def has_perm(self, perm, obj=None):
        """Check if user has a specific permission"""
        if self.is_superuser:
            return True
        # Additional permission checks will be implemented based on role
        return super().has_perm(perm, obj)
    
    def has_module_perms(self, app_label):
        """Check if user has permissions for a specific app"""
        if self.is_superuser:
            return True
        return super().has_module_perms(app_label)
    def approve(self, approver):
        """Approve user by pharmacy owner"""
        if approver.role != 'PHARMACY_OWNER':
            raise ValueError("Only pharmacy owners can approve users")
        
        self.is_approved = True
        self.approved_by = approver
        self.approved_at = timezone.now()
        if self.account_status == 'PENDING_APPROVAL':
            self.account_status = 'ACTIVE'
        self.save(update_fields=['is_approved', 'approved_by', 'approved_at', 'account_status', 'updated_at'])

    def reject(self, approver):
        """Reject user by pharmacy owner"""
        if approver.role != 'PHARMACY_OWNER':
            raise ValueError("Only pharmacy owners can reject users")
        
        self.is_approved = False
        self.account_status = 'REJECTED'
        self.save(update_fields=['is_approved', 'account_status', 'updated_at'])

    def requires_approval(self):
        """Check if user requires approval"""
        return self.role in ['PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF']

    def can_approve_users(self):
        """Check if user can approve others"""
        return self.role == 'PHARMACY_OWNER' and self.is_approved and self.is_active
    
    @property
    def is_authenticated(self):
        """Always return True for authenticated users"""
        return True
    
    def activate(self):
        """Activate the user account"""
        self.is_active = True
        self.account_status = 'ACTIVE'
        self.save(update_fields=['is_active', 'account_status', 'updated_at'])
    
    def deactivate(self):
        """Deactivate the user account"""
        self.is_active = False
        self.account_status = 'DEACTIVATED'
        self.save(update_fields=['is_active', 'account_status', 'updated_at'])
    
    def suspend(self):
        """Suspend the user account"""
        self.is_active = False
        self.account_status = 'SUSPENDED'
        self.save(update_fields=['is_active', 'account_status', 'updated_at'])
    
    def verify(self):
        """Verify the user's email"""
        self.is_verified = True
        if self.account_status == 'UNVERIFIED':
            self.account_status = 'ACTIVE'
        self.save(update_fields=['is_verified', 'account_status', 'updated_at'])

class EmailVerificationToken(models.Model):
    """Model for email verification tokens"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_verification_tokens')
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'auth_app_email_verification_token'  
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Verification token for {self.user.email}"
    
    def is_expired(self):
        """Check if the token has expired"""
        return timezone.now() > self.expires_at
    
    def use_token(self):
        """Mark the token as used"""
        self.is_used = True
        self.is_active = False
        self.save(update_fields=['is_used', 'is_active'])
    
    def is_valid(self):
        """Check if the token is still valid"""
        return (
            self.is_active and
            not self.is_used and
            not self.is_expired()
        )

class PasswordResetToken(models.Model):
    """Model for password reset tokens"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_tokens')
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        db_table = 'auth_password_reset_token'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Password reset token for {self.user.email}"
    
    def is_expired(self):
        """Check if the token has expired"""
        return timezone.now() > self.expires_at
    
    def use_token(self):
        """Mark the token as used"""
        self.is_used = True
        self.is_active = False
        self.save(update_fields=['is_used', 'is_active'])
    
    def is_valid(self):
        """Check if the token is still valid"""
        return (
            self.is_active and
            not self.is_used and
            not self.is_expired()
        )

class UserActivityLog(models.Model):
    """Model for tracking user activity"""
    
    ACTION_CHOICES = (
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
        ('TOKEN_REFRESH', 'Token Refresh'),
        ('PASSWORD_RESET', 'Password Reset'),
        ('EMAIL_VERIFICATION', 'Email Verification'),
        ('PROFILE_UPDATE', 'Profile Update'),
        ('REGISTRATION', 'Registration'),
    )
    
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='activity_logs')
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'auth_app_user_activity_log'  # Changed
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['action']),
        ]

    
    def __str__(self):
        return f"{self.action} by {self.user.email if self.user else 'Anonymous'} at {self.created_at}"


class OTPVerification(models.Model):
    """Model for OTP verification"""
    
    OTP_TYPE_CHOICES = (
        ('EMAIL_VERIFICATION', 'Email Verification'),
        ('PASSWORD_RESET', 'Password Reset'),
        ('LOGIN', 'Login'),
        ('PHONE_VERIFICATION', 'Phone Verification'),
        ('TWO_FACTOR', 'Two Factor Authentication'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_verifications')
    otp_code = models.CharField(max_length=6)
    otp_type = models.CharField(max_length=50, choices=OTP_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)
    
    class Meta:
        db_table = 'auth_app_otp_verification'  # Changed
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'otp_type']),
            models.Index(fields=['otp_code']),
        ]
    
    def __str__(self):
        return f"OTP for {self.user.email} - {self.otp_type}"
    
    def is_expired(self):
        """Check if OTP has expired"""
        return timezone.now() > self.expires_at
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return (
            self.is_active and
            not self.is_used and
            not self.is_expired() and
            self.attempts < self.max_attempts
        )
    
    def use_otp(self):
        """Mark OTP as used"""
        self.is_used = True
        self.is_active = False
        self.save(update_fields=['is_used', 'is_active'])
    
    def increment_attempts(self):
        """Increment attempt count"""
        self.attempts += 1
        if self.attempts >= self.max_attempts:
            self.is_active = False
        self.save(update_fields=['attempts', 'is_active'])