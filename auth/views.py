from rest_framework import status, generics, permissions, throttling as throttle
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken, AccessToken
from rest_framework_simplejwt.views import TokenRefreshView as JWTTokenRefreshView
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db.models import Q
import logging

from .models import User, EmailVerificationToken, PasswordResetToken, UserActivityLog
from pharmacy.models import PharmacyBrand, PharmacyVerificationHistory
from .serializers import (
    UserSerializer, RegisterSerializer, LoginSerializer,
    EmailVerificationSerializer, ResendVerificationSerializer,
    PasswordResetRequestSerializer, PasswordResetConfirmSerializer,
    UpdateProfileSerializer, ChangePasswordSerializer,
    OTPRequestSerializer, OTPVerifySerializer,
    UserApprovalSerializer, PendingUsersSerializer, SocialAuthSerializer
)
from .tokens import generate_email_verification_token, generate_password_reset_token, generate_otp, verify_otp
from .permissions import IsOwnerOrReadOnly, IsAuthenticatedAndActive, IsPharmacyOwner, IsAdminUser
from .tasks import (
    send_otp_email,
    send_otp_sms,
    send_approval_request_notification,
    send_password_reset_email,
    send_verification_email,
)
from .task_utils import call_task_safely

logger = logging.getLogger(__name__)
User = get_user_model()

class RegisterView(generics.CreateAPIView):
    """User registration endpoint"""
    
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = self.perform_create(serializer)
        
        # Log the activity
        UserActivityLog.objects.create(
            user=user,
            action='REGISTRATION',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request),
            details={'email': user.email, 'role': user.role}
        )
        
        # If user requires approval, notify pharmacy owners
        if user.requires_approval():
            # For now, get all pharmacy owners (will be filtered by pharmacy brand later)
            pharmacy_owners = User.objects.filter(
                role='PHARMACY_OWNER',
                is_approved=True,
                is_active=True,
                account_status='ACTIVE'
            )
            
            # Send notification to each owner
            for owner in pharmacy_owners:
                call_task_safely(send_approval_request_notification, owner.id, user.id)
        
        return Response({
            'message': 'Registration successful. Please verify your email.' + 
                      (' Your account is pending approval by the pharmacy owner.' if user.requires_approval() else ''),
            'user': UserSerializer(user).data,
            'requires_approval': user.requires_approval()
        }, status=status.HTTP_201_CREATED)
    
    def perform_create(self, serializer):
        return serializer.save()
    
    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        """Get user agent"""
        return request.META.get('HTTP_USER_AGENT', '')

class LoginView(APIView):
    """User login endpoint with JWT tokens"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data.get('user') if serializer.validated_data is not None else None
        if user is None:
            raise ValidationError({'user': 'Authenticated user not found in validated data'})
        
        # Update last_login
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Log the activity
        UserActivityLog.objects.create(
            user=user,
            action='LOGIN',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request),
            details={'login_method': 'email_password'}
        )
        
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data
        }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')


class SocialAuthView(APIView):
    """Handle Google login only after the serializer verifies its ID token."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SocialAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data['provider']
        provider_user_id = serializer.validated_data['provider_user_id']
        email = serializer.validated_data.get('email') or ''
        first_name = serializer.validated_data.get('first_name', '')
        last_name = serializer.validated_data.get('last_name', '')

        # Identity fields here come only from the verified Google ID token.
        user = None
        try:
            user = User.objects.get(oauth_provider=provider, oauth_provider_user_id=provider_user_id)
        except User.DoesNotExist:
            # Try to find by email and link
            if email:
                try:
                    user = User.objects.get(email=email)
                    user.oauth_provider = provider
                    user.oauth_provider_user_id = provider_user_id
                    user.is_verified = True
                    if user.account_status == 'UNVERIFIED':
                        user.account_status = 'ACTIVE'
                    user.save(update_fields=['oauth_provider', 'oauth_provider_user_id', 'is_verified', 'account_status', 'updated_at'])
                except User.DoesNotExist:
                    user = None

        # Create a new user if none found
        if not user:
            # Generate a fallback unique email if provider did not supply email
            if not email:
                email = f"{provider_user_id}@{provider.lower()}.local"

            password = User.objects.make_random_password()
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            user.oauth_provider = provider
            user.oauth_provider_user_id = provider_user_id
            user.is_verified = True
            user.is_active = True
            user.account_status = 'ACTIVE'
            user.save()

        if not user.is_active or user.account_status in {'SUSPENDED', 'DEACTIVATED', 'REJECTED'}:
            return Response(
                {'detail': 'This account is inactive or unavailable.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Generate tokens
        try:
            refresh = RefreshToken.for_user(user)
            access = str(refresh.access_token)
            refresh_token = str(refresh)

            # Log activity
            UserActivityLog.objects.create(
                user=user,
                action='LOGIN',
                ip_address=self.get_client_ip(request),
                user_agent=self.get_user_agent(request),
                details={'method': 'oauth', 'provider': provider}
            )

            return Response({
                'access': access,
                'refresh': refresh_token,
                'user': UserSerializer(user).data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Social auth token generation error: {str(e)}")
            return Response({
                'error': 'Failed to authenticate via social provider'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')

    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class LogoutView(APIView):
    """User logout endpoint - blacklists refresh token"""
    
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [throttle.UserRateThrottle]
    
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            
            # Log the activity
            UserActivityLog.objects.create(
                user=request.user,
                action='LOGOUT',
                ip_address=self.get_client_ip(request),
                user_agent=self.get_user_agent(request)
            )
            
            return Response({
                'message': 'Successfully logged out'
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Logout error: {str(e)}")
            return Response({
                'error': 'Invalid token or already logged out'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class TokenRefreshView(JWTTokenRefreshView):
    """Token refresh endpoint with activity logging"""
    
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        # Log refresh activity
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                user_id = token.payload.get('user_id')
                if user_id:
                    user = User.objects.get(id=user_id)
                    UserActivityLog.objects.create(
                        user=user,
                        action='TOKEN_REFRESH',
                        ip_address=self.get_client_ip(request),
                        user_agent=self.get_user_agent(request)
                    )
        except Exception as e:
            logger.error(f"Token refresh logging error: {str(e)}")
        
        return response
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class PlatformActivityListView(generics.ListAPIView):
    """Return the real platform activity records that exist in the backend."""

    permission_classes = [permissions.IsAuthenticated, IsAdminUser]

    def get_queryset(self):
        return []

    def get(self, request, *args, **kwargs):
        search = (request.query_params.get('search') or '').strip()
        action = (request.query_params.get('action') or '').strip()
        resource_type = (request.query_params.get('resource_type') or '').strip()
        start_date = (request.query_params.get('start_date') or '').strip()
        end_date = (request.query_params.get('end_date') or '').strip()

        activity = []

        user_logs = UserActivityLog.objects.select_related('user').all()
        if search:
            user_logs = user_logs.filter(
                Q(user__email__icontains=search)
                | Q(user__first_name__icontains=search)
                | Q(user__last_name__icontains=search)
                | Q(action__icontains=search)
            )
        if action:
            user_logs = user_logs.filter(action=action)
        if start_date:
            user_logs = user_logs.filter(created_at__date__gte=start_date)
        if end_date:
            user_logs = user_logs.filter(created_at__date__lte=end_date)

        for log in user_logs:
            actor = log.user
            event = {
                'id': f'user-activity:{log.pk}',
                'event_type': 'USER_ACTIVITY',
                'timestamp': log.created_at.isoformat(),
                'action': log.get_action_display(),
                'resource_type': 'USER',
                'resource_id': str(log.user_id) if log.user_id else None,
                'resource_name': actor.get_full_name() if actor else 'System',
                'actor': {
                    'id': str(actor.id) if actor else None,
                    'name': actor.get_full_name() if actor else 'System',
                    'email': actor.email if actor else None,
                    'role': actor.role if actor else None,
                },
                'pharmacy': None,
                'previous_state': None,
                'new_state': None,
                'reason': None,
                'details': log.details or {},
                'status': 'SUCCESS',
                'result': log.get_action_display(),
            }
            activity.append(event)

        pharmacy_history = PharmacyVerificationHistory.objects.select_related('pharmacy_brand', 'performed_by').all()
        if search:
            pharmacy_history = pharmacy_history.filter(
                Q(performed_by__email__icontains=search)
                | Q(performed_by__first_name__icontains=search)
                | Q(performed_by__last_name__icontains=search)
                | Q(pharmacy_brand__brand_name__icontains=search)
                | Q(pharmacy_brand__legal_name__icontains=search)
                | Q(action__icontains=search)
            )
        if action:
            pharmacy_history = pharmacy_history.filter(action=action)
        if resource_type:
            pharmacy_history = pharmacy_history.filter(pharmacy_brand__isnull=False)
        if start_date:
            pharmacy_history = pharmacy_history.filter(created_at__date__gte=start_date)
        if end_date:
            pharmacy_history = pharmacy_history.filter(created_at__date__lte=end_date)

        for history in pharmacy_history:
            actor = history.performed_by
            event = {
                'id': f'pharmacy-verification:{history.pk}',
                'event_type': 'PHARMACY_VERIFICATION',
                'timestamp': history.created_at.isoformat(),
                'action': history.get_action_display(),
                'resource_type': 'PHARMACY',
                'resource_id': str(history.pharmacy_brand_id),
                'resource_name': history.pharmacy_brand.brand_name if history.pharmacy_brand else 'Pharmacy',
                'actor': {
                    'id': str(actor.id) if actor else None,
                    'name': actor.get_full_name() if actor else 'System',
                    'email': actor.email if actor else None,
                    'role': actor.role if actor else None,
                },
                'pharmacy': {
                    'id': str(history.pharmacy_brand_id),
                    'brand_name': history.pharmacy_brand.brand_name if history.pharmacy_brand else None,
                    'legal_name': history.pharmacy_brand.legal_name if history.pharmacy_brand else None,
                    'pharmacy_id': history.pharmacy_brand.pharmacy_id if history.pharmacy_brand else None,
                },
                'previous_state': history.previous_status,
                'new_state': history.new_status,
                'reason': history.reason or None,
                'details': {'notes': history.notes} if history.notes else {},
                'status': history.new_status,
                'result': history.get_action_display(),
            }
            activity.append(event)

        activity.sort(key=lambda entry: entry['timestamp'], reverse=True)
        return Response(activity)


class MeView(generics.RetrieveUpdateAPIView):
    """Get and update current user's profile"""
    
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthenticatedAndActive]
    
    def get_object(self):
        return self.request.user

class UpdateProfileView(generics.UpdateAPIView):
    """Update user profile"""
    
    serializer_class = UpdateProfileSerializer
    permission_classes = [permissions.IsAuthenticated, IsAuthenticatedAndActive]
    
    def get_object(self):
        return self.request.user
    
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        return Response({
            'message': 'Profile updated successfully',
            'user': UserSerializer(instance).data
        })

class ChangePasswordView(APIView):
    """Change user password"""
    
    permission_classes = [permissions.IsAuthenticated, IsAuthenticatedAndActive]
    throttle_classes = [throttle.UserRateThrottle]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        
        # Check current password
        if not user.check_password(serializer.validated_data['current_password']):
            return Response({
                'current_password': 'Current password is incorrect'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # Log the activity
        UserActivityLog.objects.create(
            user=user,
            action='PASSWORD_RESET',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request),
            details={'change_method': 'self_change'}
        )
        
        return Response({
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class EmailVerificationView(APIView):
    """Verify email with token"""
    
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = EmailVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        token_value = serializer.validated_data['token']
        
        try:
            token = EmailVerificationToken.objects.get(token=token_value)
        except EmailVerificationToken.DoesNotExist:
            return Response({
                'detail': 'Invalid token'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not token.is_valid():
            return Response({
                'detail': 'Token has expired or has been used'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = token.user
        
        # Verify user
        user.is_verified = True
        if user.account_status == 'UNVERIFIED':
            user.account_status = 'ACTIVE'
        user.save(update_fields=['is_verified', 'account_status', 'updated_at'])
        
        # Mark token as used
        token.use_token()
        
        # Log the activity
        UserActivityLog.objects.create(
            user=user,
            action='EMAIL_VERIFICATION',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request)
        )

        refresh = RefreshToken.for_user(user)
        
        return Response({
            'message': 'Email verified successfully',
            'verified': True,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class ResendVerificationView(APIView):
    """Resend verification email"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email'].lower().strip()
        
        try:
            user = User.objects.get(email=email)
            
            # Check if already verified
            if user.is_verified:
                return Response({
                    'message': 'Email is already verified'
                }, status=status.HTTP_200_OK)
            
            # Delete old verification tokens
            EmailVerificationToken.objects.filter(
                user=user,
                is_active=True
            ).update(is_active=False)
            
            # Create new token
            token = generate_email_verification_token(user)
            
            # Send verification email
            send_verification_email(user.id, token.token)

            return Response({
                'message': 'Verification email sent'
            }, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            # Don't reveal if email exists
            return Response({
                'message': 'If an account exists with this email, a verification link will be sent'
            }, status=status.HTTP_200_OK)

class PasswordResetRequestView(APIView):
    """Request password reset"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email'].lower().strip()
        
        try:
            user = User.objects.get(email=email)
            
            # Delete old reset tokens
            PasswordResetToken.objects.filter(
                user=user,
                is_active=True
            ).update(is_active=False)
            
            # Create new token
            token = generate_password_reset_token(user)
            
            # Send password reset email
            send_password_reset_email(user.id, token.token)
            
        except User.DoesNotExist:
            # Don't reveal if email exists
            pass
        
        return Response({
            'message': 'If an account exists with this email, a password reset link will be sent'
        }, status=status.HTTP_200_OK)

class PasswordResetConfirmView(APIView):
    """Confirm password reset with token"""
    
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        token_value = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        try:
            token = PasswordResetToken.objects.get(token=token_value)
        except PasswordResetToken.DoesNotExist:
            return Response({
                'detail': 'Invalid token'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not token.is_valid():
            return Response({
                'detail': 'Token has expired or has been used'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = token.user
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        # Mark token as used
        token.use_token()
        
        # Log the activity
        UserActivityLog.objects.create(
            user=user,
            action='PASSWORD_RESET',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request),
            details={'reset_method': 'password_reset_flow'}
        )
        
        return Response({
            'message': 'Password reset successful'
        }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class OTPRequestView(APIView):
    """Request OTP for verification"""
    
    permission_classes = [permissions.AllowAny]
    throttle_classes = [throttle.AnonRateThrottle]
    
    def post(self, request):
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        email = serializer.validated_data['email'].lower().strip()
        otp_type = serializer.validated_data['otp_type']
        send_via = serializer.validated_data.get('send_via', 'EMAIL')
        
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
                
                # Keep OTP verification on the same authenticated-session contract as login.
                refresh = RefreshToken.for_user(user)
                access = str(refresh.access_token)
                refresh_token = str(refresh)
                user_data = UserSerializer(user).data

                return Response({
                    'message': 'Email verified successfully',
                    'verified': True,
                    'access': access,
                    'refresh': refresh_token,
                    'user': user_data
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


class PlatformUserListView(APIView):
    """Platform-wide user listing for SUPER_ADMIN and PLATFORM_ADMIN."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

        queryset = User.objects.all().order_by('-date_joined')
        search = (request.query_params.get('search') or '').strip()
        role = request.query_params.get('role')
        status_filter = request.query_params.get('status')
        verified = request.query_params.get('verified')

        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone_number__icontains=search)
            )
        if role:
            queryset = queryset.filter(role=role)
        if status_filter:
            queryset = queryset.filter(account_status=status_filter)
        if verified is not None:
            verified_value = str(verified).lower() in {'1', 'true', 'yes', 'y'}
            queryset = queryset.filter(is_verified=verified_value)

        serializer = UserSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PlatformUserDetailView(APIView):
    """Detailed platform user record for admin review."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            return Response({'detail': 'Forbidden'}, status=status.HTTP_403_FORBIDDEN)

        user = get_object_or_404(User, pk=pk)
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ==================== PHARMACY OWNER APPROVAL VIEWS ====================

class PendingUsersView(APIView):
    """List pending users for approval across the platform."""
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyOwner]
    throttle_classes = [throttle.UserRateThrottle]
    
    def get(self, request):
        if request.user.role in ['SUPER_ADMIN', 'PLATFORM_ADMIN']:
            pending_users = User.objects.filter(
                account_status='PENDING_APPROVAL',
                role__in=['PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'],
                is_approved=False
            ).order_by('-date_joined')
        else:
            pending_users = User.objects.filter(
                account_status='PENDING_APPROVAL',
                role__in=['PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'],
                is_approved=False
            ).order_by('-date_joined')
        
        serializer = PendingUsersSerializer(pending_users, many=True)
        return Response({
            'pending_count': pending_users.count(),
            'users': serializer.data
        }, status=status.HTTP_200_OK)

class ApproveUserView(APIView):
    """Approve or reject a user by pharmacy owner"""
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyOwner]
    throttle_classes = [throttle.UserRateThrottle]
    
    def post(self, request):
        serializer = UserApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user_id = serializer.validated_data['user_id']
        action = serializer.validated_data['action']
        notes = serializer.validated_data.get('notes', '')
        
        try:
            target_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response({
                'error': 'User not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Check if user requires approval
        if not target_user.requires_approval():
            return Response({
                'error': 'This user does not require approval'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user is already approved
        if target_user.is_approved:
            return Response({
                'error': 'User is already approved'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if user is already rejected
        if target_user.account_status == 'REJECTED':
            return Response({
                'error': 'User has already been rejected'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Perform action
        if action == 'approve':
            target_user.approve(request.user)
            message = 'User approved successfully'
            
            # Send approval notification
            from .tasks import send_approval_notification
            call_task_safely(send_approval_notification, target_user.id, 'approve')
            
        else:  # reject
            target_user.reject(request.user)
            message = 'User rejected successfully'
            
            # Send rejection notification
            from .tasks import send_approval_notification
            call_task_safely(send_approval_notification, target_user.id, 'reject')
        
        # Log the activity
        UserActivityLog.objects.create(
            user=request.user,
            action=f'USER_{action.upper()}',
            ip_address=self.get_client_ip(request),
            user_agent=self.get_user_agent(request),
            details={
                'target_user': target_user.email,
                'target_role': target_user.role,
                'action': action,
                'notes': notes
            }
        )
        
        return Response({
            'message': message,
            'user': UserSerializer(target_user).data
        }, status=status.HTTP_200_OK)
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR')
    
    def get_user_agent(self, request):
        return request.META.get('HTTP_USER_AGENT', '')

class MyPharmacyStaffView(APIView):
    """Get all approved staff across the platform for owners and admins."""
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyOwner]
    
    def get(self, request):
        staff = User.objects.filter(
            role__in=['PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'],
            is_approved=True,
            is_active=True,
            account_status='ACTIVE'
        ).order_by('first_name', 'last_name')
        
        serializer = UserSerializer(staff, many=True)
        return Response({
            'total_staff': staff.count(),
            'staff': serializer.data
        }, status=status.HTTP_200_OK)

class PendingApprovalCountView(APIView):
    """Get count of pending approvals for pharmacy owner or platform admin dashboard."""
    
    permission_classes = [permissions.IsAuthenticated, IsPharmacyOwner]
    
    def get(self, request):
        pending_count = User.objects.filter(
            account_status='PENDING_APPROVAL',
            role__in=['PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF'],
            is_approved=False
        ).count()
        
        return Response({
            'pending_approvals': pending_count
        }, status=status.HTTP_200_OK)
