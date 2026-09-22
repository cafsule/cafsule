# Auth App Guide

This document explains what the auth app contains, how it is structured, and what each file and function is responsible for in the current codebase.

This guide is intended for AI assistants and developers working on the authentication and user approval flow so they understand the app without guessing.

---

## 1. Purpose of the auth app

The auth app is responsible for:

- custom user authentication using email instead of username
- registration and login flows
- email verification
- password reset
- OTP-based verification
- social login support
- user activity logging
- pharmacy approval workflow for staff users
- role-based authorization checks and permission helpers

The custom user model is defined here and is used as the project authentication model.

---

## 2. App structure

The current auth app includes the following files:

- `__init__.py` — package marker
- `admin.py` — Django admin configuration for auth models
- `apps.py` — app config
- `migrations/` — database migrations
- `models.py` — custom `User` model and related auth models
- `permissions.py` — custom DRF permission classes
- `serializers.py` — input validation and serialization logic
- `tasks.py` — Celery async tasks for emails and notifications
- `tests.py` — auth/email task tests
- `tokens.py` — token generation utilities and OTP views
- `urls.py` — all auth routes
- `views.py` — all HTTP API endpoints

---

## 3. Core domain model: User

The main model in `auth/models.py` is `User`, which extends Django's `AbstractBaseUser` and `PermissionsMixin`.

### 3.1 UserManager

File: `auth/models.py`

`UserManager` is a custom manager with:

- `create_user(email, password=None, **extra_fields)`
  - validates email is present
  - normalizes email
  - creates and saves the user
  - hashes the password using Django's password set logic

- `create_superuser(email, password=None, **extra_fields)`
  - sets staff/superuser flags
  - sets account as active and verified
  - defaults account status to `ACTIVE`
  - defaults role to `SUPER_ADMIN`
  - enforces `is_staff=True` and `is_superuser=True`

### 3.2 Role choices

`User.ROLE_CHOICES` includes:

- `SUPER_ADMIN`
- `PLATFORM_ADMIN`
- `PHARMACY_OWNER`
- `PHARMACY_MANAGER`
- `PHARMACIST`
- `PHARMACY_STAFF`

These are the application’s role set for user authorization and workflow gating.

### 3.3 Account status choices

`User.ACCOUNT_STATUS_CHOICES` includes:

- `ACTIVE`
- `UNVERIFIED`
- `PENDING_APPROVAL`
- `SUSPENDED`
- `DEACTIVATED`
- `REJECTED`

### 3.4 User fields

The `User` model contains:

- `id` — UUID primary key
- `email` — unique email as login username
- `first_name` and `last_name`
- `phone_number` — validated using a regex for E.164-like numbers
- `groups` and `user_permissions` — standard Django auth relationships with custom related names
- `is_active`, `is_staff`, `is_superuser`
- `is_verified`
- `date_joined`, `last_login`
- `created_at`, `updated_at`
- `is_approved`
- `approved_by` — self-referential FK to approving user
- `approved_at`
- `pharmacy_brand` — currently a plain `CharField`, not a real FK to the pharmacy app
- `role`
- `account_status`
- `oauth_provider`
- `oauth_provider_user_id`

### 3.5 User metadata and methods

The `User` model defines:

- `__str__()` — returns the email
- `get_full_name()` — returns first + last name
- `get_short_name()` — returns first name
- `has_perm()` — allows superusers full access and otherwise delegates to Django
- `has_module_perms()` — same pattern for app-level permission checks
- `approve(approver)`
  - currently requires approver role to be `PHARMACY_OWNER`
  - sets `is_approved=True`
  - sets `approved_by` and `approved_at`
  - transitions `PENDING_APPROVAL` to `ACTIVE`
- `reject(approver)`
  - currently requires approver role to be `PHARMACY_OWNER`
  - sets `is_approved=False`
  - sets `account_status='REJECTED'`
- `requires_approval()`
  - returns `True` for `PHARMACY_MANAGER`, `PHARMACIST`, and `PHARMACY_STAFF`
- `can_approve_users()`
  - returns `True` if user is an approved owner and active
- `activate()`
  - sets `is_active=True`
  - changes status to `ACTIVE`
- `deactivate()`
  - sets `is_active=False`
  - changes status to `DEACTIVATED`
- `suspend()`
  - sets `is_active=False`
  - changes status to `SUSPENDED`
- `verify()`
  - sets `is_verified=True`
  - changes `UNVERIFIED` to `ACTIVE`

The model also sets:

- `USERNAME_FIELD = 'email'`
- `REQUIRED_FIELDS = ['first_name', 'last_name']`

---

## 4. Additional models in auth/models.py

### 4.1 EmailVerificationToken

Stores email verification tokens for a user.

Fields:

- `user` — FK to `User`
- `token` — unique token string
- `created_at`
- `expires_at`
- `is_used`
- `is_active`

Methods:

- `__str__()`
- `is_expired()`
- `use_token()`
- `is_valid()`

This is used to verify a new user’s email address.

### 4.2 PasswordResetToken

Stores password reset tokens.

Fields and logic are the same pattern as email verification tokens but for password recovery.

Methods:

- `is_expired()`
- `use_token()`
- `is_valid()`

### 4.3 UserActivityLog

Tracks user activity events.

Fields:

- `user`
- `action`
- `ip_address`
- `user_agent`
- `details` (JSON)
- `created_at`

Action choices include:

- `LOGIN`
- `LOGOUT`
- `TOKEN_REFRESH`
- `PASSWORD_RESET`
- `EMAIL_VERIFICATION`
- `PROFILE_UPDATE`
- `REGISTRATION`

This is used for auditing and logging.

### 4.4 OTPVerification

Stores OTP codes for user verification actions.

Fields:

- `user`
- `otp_code`
- `otp_type`
- `created_at`
- `expires_at`
- `is_used`
- `is_active`
- `attempts`
- `max_attempts`

OTP types include:

- `EMAIL_VERIFICATION`
- `PASSWORD_RESET`
- `LOGIN`
- `PHONE_VERIFICATION`
- `TWO_FACTOR`

Methods:

- `is_expired()`
- `is_valid()`
- `use_otp()`
- `increment_attempts()`

---

## 5. File-by-file explanation

## 5.1 `auth/serializers.py`

This file contains Django REST Framework serializer logic for validation and request parsing.

### Key serializers

#### `UserSerializer`
Purpose:
- public representation of a user
- used in login responses and account data responses

Output includes:
- id
- email
- first name
- last name
- full_name
- phone_number
- role
- account_status
- is_verified
- is_active
- date_joined
- last_login

#### `RegisterSerializer`
Purpose:
- validates registration payload
- checks password confirmation
- blocks platform admin roles from self-registration
- creates the user via `User.objects.create_user()`
- sends a verification email after creation

Validation rules:
- password must match `password_confirm`
- email must be unique
- phone numbers are normalized
- platform roles `SUPER_ADMIN` and `PLATFORM_ADMIN` are rejected for public registration

`create()` currently:
- creates user
- sets `account_status='UNVERIFIED'`
- sets `is_verified=False`
- creates email verification token
- triggers verification email task

#### `LoginSerializer`
Purpose:
- authenticates a user with email + password
- checks account activity and suspension state
- attaches the validated user to `attrs['user']`

Current checks include:
- email/password presence
- valid user credentials
- inactive account handling
- suspended account handling

This is the primary serializer used by the login endpoint.

#### `EmailVerificationSerializer`
Used for verifying a user via token.

#### `ResendVerificationSerializer`
Used to resend a verification email.

#### `PasswordResetRequestSerializer`
Validates the reset request email.

#### `PasswordResetConfirmSerializer`
Validates new password and confirmation.

#### `TokenRefreshSerializer`
For refresh-token payload validation.

#### `SocialAuthSerializer`
Validates OAuth/social login data.

Supported providers:
- `GOOGLE`
- `FACEBOOK`
- `APPLE`

Fields:
- `provider`
- `provider_user_id`
- `email`
- `first_name`
- `last_name`

#### `ChangePasswordSerializer`
Validates old password / new password confirmation.

#### `UpdateProfileSerializer`
Handles profile updates for first name, last name, phone number.

#### `OTPRequestSerializer`
Validates OTP request payload:
- email
- otp_type
- send_via

#### `OTPVerifySerializer`
Validates OTP payload for verification:
- email
- otp_code
- otp_type

#### `UserApprovalSerializer`
Used by approval endpoints.

Fields:
- `user_id`
- `action` (`approve` or `reject`)
- `notes`

#### `PendingUsersSerializer`
Simplified serializer for listing users waiting for approval.

---

## 5.2 `auth/views.py`

This is the main API layer for authentication and approval workflows.

### User registration

#### `RegisterView`
Purpose:
- public registration endpoint
- validates and creates the user
- logs registration activity
- if user requires approval, sends approval request notifications to pharmacy owners

Response includes:
- success message
- serialized user
- `requires_approval`

### Login

#### `LoginView`
Purpose:
- accepts email/password
- validates with `LoginSerializer`
- updates `last_login`
- issues JWT refresh/access tokens
- logs login activity

### Social authentication

#### `SocialAuthView`
Purpose:
- handles Google/Facebook/Apple authentication
- finds user by provider + provider_user_id or by email
- creates a new user if none exists
- sets OAuth metadata and issues JWT tokens
- logs social login activity

This flow currently sets account status to `ACTIVE` in several places and does not apply any staff approval workflow consistently.

### Logout and token refresh

#### `LogoutView`
- accepts refresh token
- validates and blacklists it
- logs logout

#### `TokenRefreshView`
- extends the default JWT refresh view
- logs refresh activity

### User profile and account management

#### `MeView`
- authenticated current-user profile endpoint
- permission classes: `IsAuthenticated` + `IsAuthenticatedAndActive`

#### `UpdateProfileView`
- update current user's profile

#### `ChangePasswordView`
- validates current password
- sets a new password
- logs the event

### Email verification

#### `EmailVerificationView`
- verifies email token
- marks user as verified
- sets `account_status='ACTIVE'` when in `UNVERIFIED`
- logs verification activity

#### `ResendVerificationView`
- resends email verification token

### Password reset

#### `PasswordResetRequestView`
- creates a reset token and emails the user

#### `PasswordResetConfirmView`
- validates reset token
- sets new password
- invalidates token
- logs reset event

### OTP endpoints

#### `OTPRequestView`
- sends OTP for email verification, password reset, or login
- checks active status before sending
- dispatches via email or SMS tasks

#### `OTPVerifyView`
- verifies OTP code
- handles different OTP types:
  - `EMAIL_VERIFICATION`
  - `PASSWORD_RESET`
  - `LOGIN`
  - default success response
- when `LOGIN`, it generates JWT tokens and logs the user in

### Approval endpoints

#### `PendingUsersView`
- lists users waiting for pharmacy owner approval
- currently filters by account status/role but not by real pharmacy brand relation

#### `ApproveUserView`
- approves or rejects a pending staff user
- validates target user and action
- calls `target_user.approve()` or `target_user.reject()`
- sends notification task

#### `MyPharmacyStaffView`
- returns staff under the pharmacy owner
- currently broad list with “will be filtered by pharmacy_brand later” logic

#### `PendingApprovalCountView`
- counts pending approvals for owner dashboard

---

## 5.3 `auth/permissions.py`

This file defines custom DRF permissions.

### `IsAuthenticatedAndActive`
Checks:
- request.user exists
- user is authenticated
- user is active
- account_status == `ACTIVE`

### `IsOwnerOrReadOnly`
Allows safe methods for all users but only allows writes to the owner object.

### `IsAdminUser`
Allows:
- superusers
- `SUPER_ADMIN`
- `PLATFORM_ADMIN`

### `IsSuperAdmin`
Allows only users with `is_superuser=True`.

### `IsPharmacyAdmin`
Allows:
- `PHARMACY_OWNER`
- `PHARMACY_MANAGER`

### `IsPharmacyStaff`
Allows:
- `PHARMACY_OWNER`
- `PHARMACY_MANAGER`
- `PHARMACIST`
- `PHARMACY_STAFF`

### `IsPharmacyOwner`
Allows only:
- authenticated owner
- role `PHARMACY_OWNER`
- `is_approved=True`
- `is_active=True`
- `account_status='ACTIVE'`

### `IsApprovedUser`
Allows any authenticated user that is approved and active.

---

## 5.4 `auth/tokens.py`

This file contains token helper functions and OTP utilities.

### Token helpers

- `generate_email_verification_token(user)`
  - creates an email verification token with expiry

- `generate_password_reset_token(user)`
  - creates a password reset token with expiry

- `get_email_verification_token(user)`
  - fetches latest valid email verification token

- `get_password_reset_token(user)`
  - fetches latest valid password reset token

### OTP helpers

- `generate_otp(user, otp_type, length=6, expiry_minutes=10)`
  - creates a fresh OTP for a specific user and type
  - invalidates any current active OTPs of the same type for that user

- `verify_otp(user, otp_code, otp_type)`
  - looks up an active OTP
  - validates it and increments attempts if invalid
  - marks it used on success

### OTP request and verification API classes

This file also includes API classes that duplicate the same OTP functionality that appears in the main auth view layer. In the current codebase, OTP request and verification logic is split between `views.py` and `tokens.py`.

---

## 5.5 `auth/tasks.py`

This file contains Celery background jobs used for mail delivery.

### Functions

#### `_frontend_url(path)`
Builds frontend URLs from the configured `FRONTEND_URL` setting.

#### `send_verification_email(user_id, token)`
Sends a verification email with a link containing the token.

#### `send_password_reset_email(user_id, token)`
Sends a password reset link.

#### `cleanup_expired_tokens()`
Deactivates expired verification and reset tokens.

#### `send_otp_email(user_id, otp_code, otp_type)`
Sends an OTP by email.

#### `send_otp_sms(user_id, otp_code)`
Logs SMS OTP sending; currently implemented as a placeholder for a real SMS provider.

#### `send_approval_notification(user_id, action)`
Sends an approval or rejection email to the user after owner decision.

#### `send_approval_request_notification(owner_id, new_user_id)`
Notifies a pharmacy owner that a new staff user is awaiting approval.

---

## 5.6 `auth/urls.py`

This file defines the auth routes.

Current routes include:

- `register/` -> `RegisterView`
- `login/` -> `LoginView`
- `logout/` -> `LogoutView`
- `token/refresh/` -> `TokenRefreshView`
- `me/` -> `MeView`
- `profile/` -> `UpdateProfileView`
- `change-password/` -> `ChangePasswordView`
- `verify-email/` -> `EmailVerificationView`
- `resend-verification/` -> `ResendVerificationView`
- `password/reset/` -> `PasswordResetRequestView`
- `password/reset/confirm/` -> `PasswordResetConfirmView`
- `otp/request/` -> `OTPRequestView`
- `otp/verify/` -> `OTPVerifyView`
- `oauth/` -> `SocialAuthView`
- `pending-users/` -> `PendingUsersView`
- `approve-user/` -> `ApproveUserView`
- `my-staff/` -> `MyPharmacyStaffView`

These are mounted under `api/auth/` from the project-level URL configuration.

---

## 5.7 `auth/admin.py`

This file registers major auth models in Django admin.

Admin registrations include:

- `User`
- `EmailVerificationToken`
- `PasswordResetToken`
- `UserActivityLog`
- `OTPVerification`

It defines custom display lists, filters, and search fields for quick admin use.

---

## 5.8 `auth/tests.py`

Current tests focus on email task behavior:

- `test_send_verification_email_sends_verification_link`
- `test_send_password_reset_email_sends_reset_link`

These tests verify that the tasks send correct emails with expected URLs.

---

## 6. Authentication flow summary

The current auth workflow generally works like this:

1. User registers with email and password.
2. The system creates the user in `UNVERIFIED` state.
3. An email verification token is created.
4. User verifies email.
5. User logs in with email/password.
6. JWT tokens are issued.
7. For staff roles, there is a pharmacy approval stage meant to occur after registration.

---

## 7. Important caveat in the current implementation

The current codebase contains a couple of structural issues that are important for future changes:

- `User.pharmacy_brand` is a plain `CharField`, not a real ForeignKey to the pharmacy app.
- The approval logic is not actually scoped to a specific pharmacy brand.
- There are comments like “will be filtered by pharmacy brand later,” which show the intended architecture was never fully completed.
- There is no real `Pharmacy` model in the pharmacy app at the moment, so the current auth approval logic is still a simplified approximation rather than the final pharmacy-owned workflow.

This means the auth app is functional for basic account management, but the brand-scoped approval architecture is not yet fully implemented in the ORM layer.

---

## 8. Practical understanding for future edits

If you are going to modify this app, keep these core facts in mind:

- `User` is the custom authentication model.
- The app manages both identity and role-based approval logic.
- The logic is intentionally split across models, serializers, views, permissions, and tasks.
- Staff approval is conceptually tied to a pharmacy brand, but the current model still uses a placeholder field rather than a proper relationship.
- The auth app is the authority for user data and session issuance, but the pharmacy domain is expected to provide the actual brand and membership model.

---

## 9. Short summary

The auth app is the system’s identity layer. It handles:

- sign-up
- login/logout
- JWT issuing
- email and OTP verification
- password reset
- OAuth/social login
- user activity logging
- pharmacy staff approval workflow
- role-based access control

It is a working foundation for the authentication domain, but the pharmacy-brand approval architecture still needs a real pharmacy model and proper brand membership relations to be completed correctly.
