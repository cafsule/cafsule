from django.urls import path
from . import views

urlpatterns = [
    # Authentication endpoints
    path('register/', views.RegisterView.as_view(), name='register'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('token/refresh/', views.TokenRefreshView.as_view(), name='token_refresh'),
    
    # User profile endpoints
    path('me/', views.MeView.as_view(), name='me'),
    path('profile/', views.UpdateProfileView.as_view(), name='update_profile'),
    path('change-password/', views.ChangePasswordView.as_view(), name='change_password'),
    
    # Email verification endpoints
    path('verify-email/', views.EmailVerificationView.as_view(), name='verify_email'),
    path('resend-verification/', views.ResendVerificationView.as_view(), name='resend_verification'),
    
    # Password reset endpoints
    path('password/reset/', views.PasswordResetRequestView.as_view(), name='password_reset'),
    path('password/reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    # Add to your urlpatterns
    path('otp/request/', views.OTPRequestView.as_view(), name='otp_request'),
    path('otp/verify/', views.OTPVerifyView.as_view(), name='otp_verify'),
    path('oauth/', views.SocialAuthView.as_view(), name='social_auth'),
    path('pending-users/', views.PendingUsersView.as_view(), name='pending_users'),
    path('approve-user/', views.ApproveUserView.as_view(), name='approve_user'),
    path('my-staff/', views.MyPharmacyStaffView.as_view(), name='my_staff'),
]