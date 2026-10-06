from rest_framework import serializers, status
from rest_framework.exceptions import APIException
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from django.conf import settings
from django.core.validators import EmailValidator
from django.utils import timezone
from django.db import transaction
from .models import User, EmailVerificationToken, PasswordResetToken
import re

# Import PharmacyBrand at module level for validation
try:
    from pharmacy.models import PharmacyBrand, PharmacyMembership
except ImportError:
    PharmacyBrand = None
    PharmacyMembership = None

class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model - public representation"""
    
    full_name = serializers.SerializerMethodField()
    pharmacy_memberships = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'full_name',
            'phone_number', 'role', 'account_status', 'is_verified',
            'is_active', 'date_joined', 'last_login', 'pharmacy_memberships'
        ]
        read_only_fields = [
            'id', 'is_verified', 'account_status', 'date_joined',
            'last_login', 'is_superuser', 'is_staff', 'pharmacy_memberships'
        ]
    
    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_pharmacy_memberships(self, obj):
        memberships = getattr(obj, 'pharmacy_memberships', None)
        if memberships is None:
            return []
        return [
            {
                'id': str(member.id),
                'pharmacy': str(member.pharmacy_id),
                'role': member.role,
                'status': member.status,
                'approved_by': str(member.approved_by_id) if member.approved_by_id else None,
                'approved_at': member.approved_at,
                'created_at': member.created_at,
            }
            for member in memberships.select_related('pharmacy', 'approved_by').all()
        ]

class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for user registration"""
    
    password = serializers.CharField(
        write_only=True,
        required=True,
        validators=[validate_password]
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True
    )
    class Meta:
        model = User
        fields = [
            'email', 'first_name', 'last_name', 'phone_number',
            'password', 'password_confirm', 'role'
        ]
        extra_kwargs = {
            'email': {
                'required': True,
                'validators': [EmailValidator()],
            },
            'first_name': {'required': True},
            'last_name': {'required': True},
        }
    
    def validate(self, attrs):
        """Validate password confirmation and prevent platform-role registration."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': "Passwords do not match"
            })
        
        # Prevent users from setting admin roles
        if attrs.get('role') in ['SUPER_ADMIN', 'PLATFORM_ADMIN']:
            raise serializers.ValidationError({
                'role': "Cannot register with admin role"
            })
        
        return attrs
    
    def validate_email(self, value):
        """Normalize and validate email"""
        value = value.lower().strip()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists")
        return value
    
    def validate_phone_number(self, value):
        """Validate and format phone number"""
        if not value:
            return ''
        
        # Clean the phone number
        phone = re.sub(r'[\s\-()]+', '', value)
        
        # Check if it starts with + (international format)
        if not phone.startswith('+'):
            # For Nigerian numbers, assume 234 prefix
            if phone.startswith('0'):
                phone = '+234' + phone[1:]
            else:
                phone = '+234' + phone
        
        # Validate using regex
        if not re.match(r'^\+?1?\d{9,15}$', phone):
            raise serializers.ValidationError(
                "Phone number must be in E.164 format: +234XXXXXXXXXX"
            )
        
        return phone
    
    @transaction.atomic
    def create(self, validated_data):
        """Create a new user and optionally create a PharmacyMembership for staff"""
        validated_data.pop('password_confirm')
        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            phone_number=validated_data.get('phone_number', ''),
            role=validated_data.get('role', 'PHARMACY_STAFF'),
        )
        
        # User is created unverified by default
        user.account_status = 'UNVERIFIED'
        user.is_verified = False
        user.save()
        
        # Registration should use the existing OTP email verification flow that
        # matches the frontend verification page and OTP endpoints.
        # Keep the legacy email-token flow intact for compatibility, but do not
        # send the link email during signup.
        from .tasks import send_otp_email
        from .tokens import generate_otp
        otp = generate_otp(user, 'EMAIL_VERIFICATION')
        send_otp_email(user.id, otp.otp_code, 'EMAIL_VERIFICATION')

        return user

class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""
    
    email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    def validate(self, attrs):
        """Validate credentials"""
        email = attrs.get('email', '').lower().strip()
        password = attrs.get('password', '')
        
        if not email or not password:
            raise serializers.ValidationError({
                'detail': "Email and password are required"
            })
        
        # First try the configured authenticate (may rely on custom backend)
        user = authenticate(email=email, password=password)

        # If authenticate() didn't return a user, fall back to direct lookup
        # and password check (handles setups without email-auth backend).
        if not user:
            try:
                user_obj = User.objects.get(email=email)
                if user_obj.check_password(password):
                    user = user_obj
                else:
                    user = None
            except User.DoesNotExist:
                user = None

        if not user:
            raise serializers.ValidationError({
                'detail': "Invalid credentials"
            })
        
        if not user.is_active:
            raise serializers.ValidationError({
                'detail': "Account is deactivated"
            })
        
        if user.account_status == 'SUSPENDED':
            raise serializers.ValidationError({
                'detail': "Account is suspended"
            })
        
        attrs['user'] = user
        return attrs

class EmailVerificationSerializer(serializers.Serializer):
    """Serializer for email verification"""
    
    token = serializers.CharField(required=True)

class ResendVerificationSerializer(serializers.Serializer):
    """Serializer for resending verification email"""
    
    email = serializers.EmailField(required=True)

class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        """Validate email exists"""
        value = value.lower().strip()
        if not User.objects.filter(email=value).exists():
            # Don't reveal if email exists
            return value
        return value

class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""
    
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(
        required=True
    )
    
    def validate(self, attrs):
        """Validate passwords match"""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Passwords do not match"
            })
        return attrs

class TokenRefreshSerializer(serializers.Serializer):
    """Serializer for token refresh"""
    
    refresh = serializers.CharField(required=True)


class IdentityProviderUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'Identity verification is temporarily unavailable.'


class SocialAuthSerializer(serializers.Serializer):
    """Verify Google's signed ID token before using its identity claims."""

    provider = serializers.ChoiceField(choices=(('GOOGLE', 'Google'),), required=True)
    id_token = serializers.CharField(required=True, write_only=True, trim_whitespace=True)

    def validate(self, attrs):
        if not settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY:
            raise IdentityProviderUnavailable('Google sign-in is not configured.')

        # Google rotates signing keys. google-auth validates the signature,
        # issuer, expiry, and configured client-ID audience using Google's keys.
        from google.auth.exceptions import GoogleAuthError
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        try:
            claims = id_token.verify_oauth2_token(
                attrs['id_token'],
                Request(),
                audience=settings.SOCIAL_AUTH_GOOGLE_OAUTH2_KEY,
            )
        except ValueError as exc:
            raise serializers.ValidationError({'id_token': 'Invalid Google ID token.'}) from exc
        except GoogleAuthError as exc:
            raise IdentityProviderUnavailable() from exc

        email = claims.get('email')
        provider_user_id = claims.get('sub')
        if not provider_user_id or not email or claims.get('email_verified') is not True:
            raise serializers.ValidationError(
                {'id_token': 'The Google account must have a verified email address.'}
            )

        attrs.update({
            'provider_user_id': provider_user_id,
            'email': email.lower().strip(),
            'first_name': claims.get('given_name', ''),
            'last_name': claims.get('family_name', ''),
        })
        return attrs

class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password"""
    
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(
        required=True
    )
    
    def validate(self, attrs):
        """Validate passwords match"""
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                'new_password_confirm': "Passwords do not match"
            })
        return attrs

class UpdateProfileSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile"""
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone_number']
    
    def validate_phone_number(self, value):
        """Validate and format phone number"""
        if not value:
            return ''
        
        phone = re.sub(r'[\s\-()]+', '', value)
        
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = '+234' + phone[1:]
            else:
                phone = '+234' + phone
        
        if not re.match(r'^\+?1?\d{9,15}$', phone):
            raise serializers.ValidationError(
                "Phone number must be in E.164 format: +234XXXXXXXXXX"
            )
        
        return phone

class OTPRequestSerializer(serializers.Serializer):
    """Serializer for requesting OTP"""
    
    email = serializers.EmailField(required=True)
    otp_type = serializers.ChoiceField(
        choices=['EMAIL_VERIFICATION', 'PASSWORD_RESET', 'LOGIN', 'PHONE_VERIFICATION', 'TWO_FACTOR'],
        required=True
    )
    send_via = serializers.ChoiceField(
        choices=['EMAIL', 'SMS', 'BOTH'],
        default='EMAIL'
    )

class OTPVerifySerializer(serializers.Serializer):
    """Serializer for verifying OTP"""
    
    email = serializers.EmailField(required=True)
    otp_code = serializers.CharField(min_length=6, max_length=6, required=True)
    otp_type = serializers.ChoiceField(
        choices=['EMAIL_VERIFICATION', 'PASSWORD_RESET', 'LOGIN', 'PHONE_VERIFICATION', 'TWO_FACTOR'],
        required=True
    )
class UserApprovalSerializer(serializers.Serializer):
    """Serializer for approving/rejecting users"""
    
    user_id = serializers.UUIDField(required=True)
    action = serializers.ChoiceField(choices=['approve', 'reject'], required=True)
    notes = serializers.CharField(required=False, allow_blank=True)

class PendingUsersSerializer(serializers.ModelSerializer):
    """Serializer for listing pending users"""
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'phone_number',
            'role', 'date_joined', 'account_status'
        ]
