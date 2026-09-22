import secrets
import random

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status, throttling as throttle
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    EmailVerificationToken,
    PasswordResetToken,
    OTPVerification,
    UserActivityLog,
)
from .serializers import OTPRequestSerializer, OTPVerifySerializer, UserSerializer

User = get_user_model()

def generate_email_verification_token(user):
    """Generate a secure email verification token"""
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timezone.timedelta(
        hours=settings.EMAIL_VERIFICATION_TOKEN_EXPIRY_HOURS
    )
    
    return EmailVerificationToken.objects.create(
        user=user,
        token=token,
        expires_at=expires_at
    )

def generate_password_reset_token(user):
    """Generate a secure password reset token"""
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timezone.timedelta(
        hours=settings.PASSWORD_RESET_TOKEN_EXPIRY_HOURS
    )
    
    return PasswordResetToken.objects.create(
        user=user,
        token=token,
        expires_at=expires_at
    )

def get_email_verification_token(user):
    """Get active verification token for user"""
    try:
        return EmailVerificationToken.objects.filter(
            user=user,
            is_active=True,
            is_used=False,
            expires_at__gt=timezone.now()
        ).latest('created_at')
    except EmailVerificationToken.DoesNotExist:
        return None

def get_password_reset_token(user):
    """Get active password reset token for user"""
    try:
        return PasswordResetToken.objects.filter(
            user=user,
            is_active=True,
            is_used=False,
            expires_at__gt=timezone.now()
        ).latest('created_at')
    except PasswordResetToken.DoesNotExist:
        return None

import random
from django.utils import timezone
from django.conf import settings
from .models import OTPVerification

def generate_otp(user, otp_type, length=6, expiry_minutes=10):
    """Generate a numeric OTP for verification"""
    # Generate random 6-digit code
    otp_code = ''.join([str(random.randint(0, 9)) for _ in range(length)])
    
    # Calculate expiry time
    expires_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes)
    
    # Deactivate any existing active OTPs of the same type
    OTPVerification.objects.filter(
        user=user,
        otp_type=otp_type,
        is_active=True
    ).update(is_active=False)
    
    # Create new OTP
    otp = OTPVerification.objects.create(
        user=user,
        otp_code=otp_code,
        otp_type=otp_type,
        expires_at=expires_at
    )
    
    return otp

def verify_otp(user, otp_code, otp_type):
    """Verify OTP code for a user"""
    try:
        otp = OTPVerification.objects.get(
            user=user,
            otp_code=otp_code,
            otp_type=otp_type,
            is_active=True,
            is_used=False
        )
        
        if not otp.is_valid():
            if not otp.is_expired():
                otp.increment_attempts()
            return False, "OTP is invalid or expired"
        
        # Mark OTP as used
        otp.use_otp()
        return True, "OTP verified successfully"
        
    except OTPVerification.DoesNotExist:
        return False, "Invalid OTP code"

from .models import OTPVerification
from .tokens import generate_otp, verify_otp
from .tasks import send_otp_email, send_otp_sms
from .task_utils import call_task_safely

class OTPRequestView(APIView):
    """Request OTP for verification"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data or {}
        email = (validated_data.get('email') or '').lower().strip()
        otp_type = validated_data.get('otp_type')
        send_via = validated_data.get('send_via', 'EMAIL')

        if not email or not otp_type:
            return Response({
                'error': 'Email and OTP type are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(email=email)
            
            # Check if user is active
            if not user.is_active:
                return Response({
                    'error': 'Account is not active'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Generate OTP
            otp = generate_otp(user, otp_type)
            
            # Send OTP via selected channel
            if send_via in ['EMAIL', 'BOTH']:
                call_task_safely(send_otp_email, user.id, otp.otp_code, otp_type)
            
            if send_via in ['SMS', 'BOTH'] and user.phone_number:
                call_task_safely(send_otp_sms, user.id, otp.otp_code)
            
            # Log activity
            UserActivityLog.objects.create(
                user=user,
                action='OTP_REQUEST',
                ip_address=self.get_client_ip(request),
                user_agent=self.get_user_agent(request),
                details={'otp_type': otp_type, 'send_via': send_via}
            )
            
            return Response({
                'message': f'OTP sent to your {send_via.lower()}',
                'expires_in': 10,  # minutes
                'method': send_via
            }, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            # Don't reveal if user exists
            return Response({
                'message': 'If an account exists, an OTP will be sent'
            }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class OTPVerifyView(APIView):
    """Verify OTP code"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = OTPVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email'].lower().strip()
        otp_code = serializer.validated_data['otp_code']
        otp_type = serializer.validated_data['otp_type']
        
        try:
            user = User.objects.get(email=email)
            
            # Verify OTP
            is_valid, message = verify_otp(user, otp_code, otp_type)
            
            if not is_valid:
                return Response({
                    'error': message
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Handle different OTP types
            if otp_type == 'EMAIL_VERIFICATION':
                # Verify user's email
                user.is_verified = True
                if user.account_status == 'UNVERIFIED':
                    user.account_status = 'ACTIVE'
                user.save(update_fields=['is_verified', 'account_status', 'updated_at'])
                
                # Log activity
                UserActivityLog.objects.create(
                    user=user,
                    action='EMAIL_VERIFICATION',
                    ip_address=self.get_client_ip(request),
                    user_agent=self.get_user_agent(request),
                    details={'method': 'OTP'}
                )
                
                return Response({
                    'message': 'Email verified successfully',
                    'verified': True
                }, status=status.HTTP_200_OK)
            
            elif otp_type == 'PASSWORD_RESET':
                # Generate password reset token
                from .tokens import generate_password_reset_token
                reset_token = generate_password_reset_token(user)
                
                return Response({
                    'message': 'OTP verified. You can now reset your password.',
                    'reset_token': reset_token.token,
                    'verified': True
                }, status=status.HTTP_200_OK)
            
            elif otp_type == 'LOGIN':
                # Generate JWT tokens for login
                from rest_framework_simplejwt.tokens import RefreshToken
                refresh = RefreshToken.for_user(user)
                
                # Update last_login
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                
                # Log activity
                UserActivityLog.objects.create(
                    user=user,
                    action='LOGIN',
                    ip_address=self.get_client_ip(request),
                    user_agent=self.get_user_agent(request),
                    details={'method': 'OTP'}
                )
                
                return Response({
                    'message': 'Login successful',
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                    'user': UserSerializer(user).data,
                    'verified': True
                }, status=status.HTTP_200_OK)
            
            else:
                # Generic OTP verification success
                return Response({
                    'message': 'OTP verified successfully',
                    'verified': True
                }, status=status.HTTP_200_OK)
                
        except User.DoesNotExist:
            return Response({
                'error': 'Invalid credentials'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')