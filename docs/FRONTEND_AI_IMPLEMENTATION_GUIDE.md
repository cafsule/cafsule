# Smart Medicine Finder - Frontend Implementation Guide
## Backend API & Permissions Documentation

**Last Updated:** August 29, 2026  
**Version:** 1.0  
**Target:** Frontend AI Implementation Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [User Roles & Permissions](#user-roles--permissions)
3. [Authentication & Authorization](#authentication--authorization)
4. [Complete API Reference](#complete-api-reference)
5. [Permission Matrix](#permission-matrix)
6. [Implementation Checklist](#implementation-checklist)
7. [Critical Implementation Notes](#critical-implementation-notes)

---

## Overview

### System Architecture
This is a **Role-Based Access Control (RBAC)** system with multi-level approval workflows. The frontend must enforce permissions at:
- **UI Level**: Hide/show features based on user role and approval status
- **Request Level**: Send proper authentication headers and role identifiers
- **Navigation Level**: Route users to appropriate modules based on permissions
- **Component Level**: Disable actions for unauthorized users

### Key Concepts

| Concept | Definition | Impact on Frontend |
|---------|-----------|-------------------|
| **User Role** | Core role determining core capabilities (PHARMACY_OWNER, PHARMACIST, etc.) | Controls main menu, available features |
| **Approval Status** (`is_approved`) | Whether user has been approved by pharmacy owner/admin | Controls access to sensitive operations |
| **Account Status** | User's account state (ACTIVE, UNVERIFIED, PENDING_APPROVAL, SUSPENDED, etc.) | Controls login, feature access |
| **Verification Status** | Email verification for authentication | Controls access to authenticated endpoints |
| **Pharmacy Membership** | User's relationship with a specific pharmacy | Controls pharmacy-specific data access |

---

## User Roles & Permissions

### 1. **SUPER_ADMIN** (System Administrator)
**Access Level:** ⭐⭐⭐⭐⭐ (Unrestricted)

**Capabilities:**
- View all users across all pharmacies
- Approve/reject pharmacy registrations
- Approve/reject user accounts
- View all pharmacies and their data
- Manage platform settings
- Access all reporting features
- Verify pharmacy documents

**Frontend Behavior:**
```javascript
if (user.role === 'SUPER_ADMIN') {
  showMenu(['Users Management', 'Pharmacy Verification', 'Analytics', 'Settings'])
  enableAllFeatures()
}
```

**Required Endpoints:**
- View pending users
- View pending pharmacies
- Approve users
- Verify pharmacies

---

### 2. **PLATFORM_ADMIN** (Platform Administrator)
**Access Level:** ⭐⭐⭐⭐ (Mostly Unrestricted)

**Capabilities:**
- View all users across all pharmacies
- Approve/reject pharmacy registrations
- View all pharmacies and their data
- Manage platform settings
- Access reporting features

**Frontend Behavior:** Similar to SUPER_ADMIN but with some limitations

---

### 3. **PHARMACY_OWNER** (Pharmacy Business Owner)
**Access Level:** ⭐⭐⭐ (Own Pharmacy + Staff)

**Must Have:**
- `is_approved = True` (approved by platform admin)
- `is_verified = True` (email verified)
- `account_status = 'ACTIVE'`
- Own PharmacyBrand with `verification_status = 'VERIFIED'`

**Capabilities:**
- Own a verified pharmacy
- Create/manage pharmacy staff (invite, approve, reject)
- View staff performance metrics
- Manage inventory (in their pharmacy)
- View sales/transactions (in their pharmacy)
- Update pharmacy profile
- Cannot view other pharmacies' data

**Frontend Routes:**
```
/dashboard
/pharmacy/profile
/staff/management
/staff/pending-approval
/inventory
/sales
```

**Key Check Before Showing UI:**
```javascript
if (user.role === 'PHARMACY_OWNER' && 
    user.is_approved && 
    user.is_verified && 
    user.account_status === 'ACTIVE') {
  showPharmacyOwnerDashboard()
} else {
  showPendingApprovalMessage()
}
```

---

### 4. **PHARMACY_MANAGER** (Pharmacy Management Staff)
**Access Level:** ⭐⭐ (Pharmacy-Specific)

**Must Have:**
- `is_approved = True` (approved by their pharmacy owner)
- `is_verified = True`
- `account_status = 'ACTIVE'`
- Active PharmacyMembership with approval from owner

**Capabilities:**
- Cannot view other pharmacies' data
- Can view pharmacy staff (only in their pharmacy)
- Can view inventory (only in their pharmacy)
- Can view sales (only in their pharmacy)
- Can update pharmacy profile (limited fields)
- Cannot approve/reject other staff

**Frontend Routes:**
```
/dashboard
/pharmacy/profile (read-only or limited)
/staff/list (their pharmacy only)
/inventory (their pharmacy only)
/sales (their pharmacy only)
```

---

### 5. **PHARMACIST** (Licensed Pharmacist)
**Access Level:** ⭐⭐ (Pharmacy-Specific, Read Focus)

**Capabilities:**
- View pharmacy staff list (read-only)
- View inventory (read-only)
- Prepare sales/prescriptions
- View sales records (pharmacy-specific)

**Frontend Behavior:** Limited to read-only dashboards

---

### 6. **PHARMACY_STAFF** (Pharmacy Employee)
**Access Level:** ⭐ (Limited Pharmacy-Specific)

**Capabilities:**
- View inventory (read-only)
- View sales records (read-only)
- Cannot approve/manage anyone

**Frontend Behavior:** Read-only access to assigned pharmacy data

---

## Authentication & Authorization

### Registration Flow

```
STEP 1: Registration (Public)
  POST /api/auth/register/ 
  No authentication required
  
  Request body:
  {
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone_number": "+2347011111111",
    "password": "SecurePassword123!",
    "password_confirm": "SecurePassword123!",
    "role": "PHARMACY_OWNER",  // or PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF
    "pharmacy_brand": null  // ONLY for PHARMACY_OWNER
  }
  
  Response 201:
  {
    "message": "Registration successful. Please verify your email.",
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "first_name": "John",
      "last_name": "Doe",
      "full_name": "John Doe",
      "role": "PHARMACY_OWNER",
      "account_status": "UNVERIFIED",
      "is_verified": false,
      "is_active": true
    },
    "requires_approval": true
  }

STEP 2: Email Verification (Required for all users)
  1. User receives verification email with token
  2. Frontend extracts token from email link: /verify-email?token=xxx
  3. POST /api/auth/verify-email/
  
  Request:
  {
    "token": "verification-token-from-email"
  }
  
  Response 200:
  {
    "message": "Email verified successfully. Please wait for approval.",
    "user": { ... with is_verified: true }
  }

STEP 3: Approval (For certain roles)
  1. Platform admin reviews user
  2. POST /api/auth/approve-user/
  
  Request (by admin):
  {
    "user_id": "user-uuid",
    "action": "approve"  // or "reject"
  }
  
  Response:
  {
    "message": "User approved successfully",
    "user": { ... with is_approved: true }
  }

STEP 4: Login (After verification & approval)
  POST /api/auth/login/
  
  Request:
  {
    "email": "user@example.com",
    "password": "SecurePassword123!"
  }
  
  Response 200:
  {
    "access": "eyJhbGc...",
    "refresh": "eyJhbGc...",
    "user": {
      "id": "uuid",
      "email": "user@example.com",
      "role": "PHARMACY_OWNER",
      "is_approved": true,
      "is_verified": true,
      "account_status": "ACTIVE"
    }
  }
```

### Token Management

```javascript
// Store tokens after login
localStorage.setItem('access_token', response.access)
localStorage.setItem('refresh_token', response.refresh)

// Send token in all authenticated requests
const headers = {
  'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
  'Content-Type': 'application/json'
}

// Handle token expiration and refresh
if (response.status === 401) {
  POST /api/auth/token/refresh/
  {
    "refresh": localStorage.getItem('refresh_token')
  }
  
  Then retry original request with new access token
}
```

### Social Authentication (Optional)

```
POST /api/auth/oauth/

Request:
{
  "provider": "google",  // Currently supports Google
  "id_token": "google-token",
  "code": "authorization-code"
}

Response 200:
{
  "access": "jwt-access-token",
  "refresh": "jwt-refresh-token",
  "user": { ... user object }
}
```

---

## Complete API Reference

### 🔐 Authentication Endpoints

#### 1. Register User
```
POST /api/auth/register/
Content-Type: application/json
Authentication: None

Request Body:
{
  "email": "john@pharmacy.com",
  "first_name": "John",
  "last_name": "Doe",
  "phone_number": "+2347011111111",
  "password": "StrongPass123!",
  "password_confirm": "StrongPass123!",
  "role": "PHARMACY_OWNER",
  "pharmacy_brand": null
}

Success Response (201):
{
  "message": "Registration successful. Please verify your email.",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@pharmacy.com",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "phone_number": "+2347011111111",
    "role": "PHARMACY_OWNER",
    "account_status": "UNVERIFIED",
    "is_verified": false,
    "is_active": true,
    "date_joined": "2026-08-29T13:39:24.123456Z",
    "last_login": null
  },
  "requires_approval": true
}

Error Response (400):
{
  "email": ["User with this email already exists"],
  "password": ["This password is too common"]
}
```

---

#### 2. Login
```
POST /api/auth/login/
Content-Type: application/json
Authentication: None

Request Body:
{
  "email": "john@pharmacy.com",
  "password": "StrongPass123!"
}

Success Response (200):
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@pharmacy.com",
    "first_name": "John",
    "last_name": "Doe",
    "full_name": "John Doe",
    "role": "PHARMACY_OWNER",
    "is_verified": true,
    "is_active": true,
    "account_status": "ACTIVE",
    "is_approved": true,
    "date_joined": "2026-08-29T13:39:24.123456Z",
    "last_login": "2026-08-29T14:05:00.123456Z"
  }
}

Error Response (400):
{
  "error": "Invalid email or password"
}

// Account not verified
{
  "error": "Account is not verified. Please check your email for verification link.",
  "requires_verification": true
}

// Account pending approval
{
  "error": "Account is not approved yet. Please wait for approval.",
  "requires_approval": true,
  "account_status": "PENDING_APPROVAL"
}

// Account suspended
{
  "error": "Account is suspended"
}
```

---

#### 3. Refresh Token
```
POST /api/auth/token/refresh/
Content-Type: application/json
Authentication: None

Request Body:
{
  "refresh": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}

Success Response (200):
{
  "access": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}

Error Response (401):
{
  "detail": "Token is invalid or expired"
}
```

---

#### 4. Logout
```
POST /api/auth/logout/
Content-Type: application/json
Authorization: Bearer {access_token}

Request Body:
{}

Success Response (200):
{
  "message": "Logged out successfully"
}
```

---

#### 5. Verify Email
```
POST /api/auth/verify-email/
Content-Type: application/json
Authentication: None

Request Body:
{
  "token": "verification-token-from-email"
}

Success Response (200):
{
  "message": "Email verified successfully. Please wait for approval.",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "john@pharmacy.com",
    "is_verified": true,
    "account_status": "PENDING_APPROVAL",
    "is_approved": false
  }
}

Error Response (400):
{
  "error": "Invalid or expired verification token"
}
```

---

#### 6. Resend Verification Email
```
POST /api/auth/resend-verification/
Content-Type: application/json
Authentication: None

Request Body:
{
  "email": "john@pharmacy.com"
}

Success Response (200):
{
  "message": "Verification email resent to john@pharmacy.com"
}
```

---

#### 7. Request OTP (For additional verification)
```
POST /api/auth/otp/request/
Content-Type: application/json
Authorization: Bearer {access_token}

Request Body:
{
  "email": "john@pharmacy.com",
  "otp_type": "EMAIL_VERIFICATION",  // or "PASSWORD_RESET", "LOGIN_VERIFICATION"
  "send_via": "EMAIL"  // or "SMS", "BOTH"
}

Success Response (200):
{
  "message": "OTP sent successfully",
  "otp_code": "123456",  // Only in development
  "otp_type": "EMAIL_VERIFICATION"
}

Error Response (500):
{
  "error": "Failed to send OTP due to Redis connection issue"
}
```

---

#### 8. Verify OTP
```
POST /api/auth/otp/verify/
Content-Type: application/json
Authorization: Bearer {access_token}

Request Body:
{
  "email": "john@pharmacy.com",
  "otp_code": "123456",
  "otp_type": "EMAIL_VERIFICATION"
}

Success Response (200):
{
  "message": "OTP verified successfully",
  "verified": true
}

Error Response (400):
{
  "error": "Invalid or expired OTP code"
}
```

---

#### 9. Password Reset Request
```
POST /api/auth/password/reset/
Content-Type: application/json
Authentication: None

Request Body:
{
  "email": "john@pharmacy.com"
}

Success Response (200):
{
  "message": "Password reset email sent to john@pharmacy.com"
}
```

---

#### 10. Password Reset Confirm
```
POST /api/auth/password/reset/confirm/
Content-Type: application/json
Authentication: None

Request Body:
{
  "token": "reset-token-from-email",
  "new_password": "NewPassword123!",
  "confirm_password": "NewPassword123!"
}

Success Response (200):
{
  "message": "Password reset successfully"
}
```

---

### 👤 User Profile Endpoints

#### 1. Get Current User Profile
```
GET /api/auth/me/
Authorization: Bearer {access_token}

Success Response (200):
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "john@pharmacy.com",
  "first_name": "John",
  "last_name": "Doe",
  "full_name": "John Doe",
  "phone_number": "+2347011111111",
  "role": "PHARMACY_OWNER",
  "account_status": "ACTIVE",
  "is_verified": true,
  "is_active": true,
  "is_approved": true,
  "date_joined": "2026-08-29T13:39:24.123456Z",
  "last_login": "2026-08-29T14:05:00.123456Z"
}
```

---

#### 2. Update User Profile
```
PUT /api/auth/profile/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body (all fields optional):
{
  "first_name": "John",
  "last_name": "Doe",
  "phone_number": "+2347011111111"
}

Success Response (200):
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "john@pharmacy.com",
  "first_name": "John",
  "last_name": "Doe",
  "phone_number": "+2347011111111",
  "role": "PHARMACY_OWNER",
  "account_status": "ACTIVE",
  "is_verified": true,
  "is_approved": true,
  "date_joined": "2026-08-29T13:39:24.123456Z",
  "last_login": "2026-08-29T14:05:00.123456Z"
}
```

---

#### 3. Change Password
```
POST /api/auth/change-password/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body:
{
  "old_password": "CurrentPassword123!",
  "new_password": "NewPassword456!",
  "new_password_confirm": "NewPassword456!"
}

Success Response (200):
{
  "message": "Password changed successfully"
}

Error Response (400):
{
  "old_password": ["Incorrect old password"]
}
```

---

### 🏥 Pharmacy Management Endpoints

#### 1. Create Pharmacy Brand (PHARMACY_OWNER only)
```
POST /api/pharmacy/brands/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body:
{
  "legal_name": "John's Pharmacy Limited",
  "brand_name": "John's Pharmacy",
  "description": "A community pharmacy serving the neighborhood",
  "business_email": "business@johnspharmacy.com",
  "business_phone": "+2347011111111",
  "address_line_1": "123 Main Street",
  "address_line_2": "Suite 100",
  "city": "Lagos",
  "state": "Lagos",
  "lga": "Ikoyi",
  "postal_code": "106104",
  "country": "Nigeria",
  "location": "-74.0062,40.7128",  // longitude,latitude format
  "pharmacy_type": "COMMUNITY_PHARMACY",
  "years_in_operation": 5,
  "cac_registration_number": "CAC/001/2021",
  "cac_registration_type": "Limited Company",
  "pcn_premises_registration_number": "PCN/01/2021",
  "pcn_license_number": "PCN-LIC-001/2021",
  "pcn_issue_date": "2021-01-15",
  "pcn_expiry_date": "2026-01-15",
  "nafdac_registration_number": "NAFDAC/002/2021",
  "nafdac_certificate_number": "NAF-CERT-001",
  "nafdac_expiry_date": "2026-12-31"
}

Success Response (201):
{
  "id": "pharmacy-uuid",
  "owner": {
    "id": "user-uuid",
    "email": "john@pharmacy.com"
  },
  "legal_name": "John's Pharmacy Limited",
  "brand_name": "John's Pharmacy",
  "verification_status": "DRAFT",
  "is_verified": false,
  "is_awaiting_verification": false,
  "created_at": "2026-08-29T13:39:24.123456Z",
  "updated_at": "2026-08-29T13:39:24.123456Z"
}

Error Response (400):
{
  "pharmacy_type": ["Invalid pharmacy type"]
}

Error Response (403):
{
  "error": "Only pharmacy owners can create brands"
}
```

---

#### 2. Get My Pharmacy
```
GET /api/pharmacy/my-pharmacy/
Authorization: Bearer {access_token}

Success Response (200):
{
  "id": "pharmacy-uuid",
  "owner": {
    "id": "user-uuid",
    "email": "john@pharmacy.com",
    "full_name": "John Doe"
  },
  "legal_name": "John's Pharmacy Limited",
  "brand_name": "John's Pharmacy",
  "description": "A community pharmacy",
  "business_email": "business@johnspharmacy.com",
  "business_phone": "+2347011111111",
  "address_line_1": "123 Main Street",
  "city": "Lagos",
  "state": "Lagos",
  "postal_code": "106104",
  "country": "Nigeria",
  "latitude": 40.7128,
  "longitude": -74.0062,
  "pharmacy_type": "COMMUNITY_PHARMACY",
  "years_in_operation": 5,
  "verification_status": "VERIFIED",
  "is_verified": true,
  "is_awaiting_verification": false,
  "verified_at": "2026-08-29T14:00:00.123456Z",
  "verified_by": {
    "id": "admin-uuid",
    "email": "admin@platform.com"
  },
  "created_at": "2026-08-29T13:39:24.123456Z",
  "updated_at": "2026-08-29T13:39:24.123456Z"
}
```

---

#### 3. Update Pharmacy Brand
```
PUT /api/pharmacy/brands/{pharmacy_id}/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body (any fields can be updated):
{
  "brand_name": "John's Pharmacy - Updated",
  "description": "Updated description",
  "business_phone": "+2347022222222"
}

Success Response (200):
{
  "id": "pharmacy-uuid",
  "brand_name": "John's Pharmacy - Updated",
  "description": "Updated description",
  "business_phone": "+2347022222222",
  ...
}
```

---

#### 4. Get All Pharmacies (Admin only, with filtering)
```
GET /api/pharmacy/brands/?verification_status=VERIFIED&city=Lagos&limit=20&offset=0
Authorization: Bearer {access_token}

Success Response (200):
{
  "count": 150,
  "next": "http://api.example.com/pharmacy/brands/?limit=20&offset=20",
  "previous": null,
  "results": [
    {
      "id": "pharmacy-uuid",
      "brand_name": "John's Pharmacy",
      "city": "Lagos",
      "verification_status": "VERIFIED",
      "is_verified": true,
      ...
    }
  ]
}

Query Parameters:
- verification_status: DRAFT, PENDING_VERIFICATION, UNDER_REVIEW, VERIFIED, REJECTED, SUSPENDED
- city: Filter by city
- limit: Number of results (default 20)
- offset: Pagination offset
- search: Search by brand_name or legal_name
```

---

### 👥 User Approval & Staff Management

#### 1. Get Pending Users (Admin only)
```
GET /api/auth/pending-users/
Authorization: Bearer {access_token}

Query Parameters:
- role: Filter by role (PHARMACY_OWNER, PHARMACY_MANAGER, etc.)
- limit: Number of results
- offset: Pagination offset

Success Response (200):
{
  "count": 12,
  "results": [
    {
      "id": "user-uuid",
      "email": "manager@pharmacy.com",
      "first_name": "Alice",
      "last_name": "Manager",
      "full_name": "Alice Manager",
      "role": "PHARMACY_MANAGER",
      "account_status": "PENDING_APPROVAL",
      "is_verified": true,
      "is_approved": false,
      "date_joined": "2026-08-29T13:39:24.123456Z"
    }
  ]
}
```

---

#### 2. Approve or Reject User
```
POST /api/auth/approve-user/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body:
{
  "user_id": "user-uuid-to-approve",
  "action": "approve"  // or "reject"
  "rejection_reason": "Does not meet requirements"  // Optional, only for rejection
}

Success Response (200):
{
  "message": "User approved successfully",
  "user": {
    "id": "user-uuid",
    "email": "manager@pharmacy.com",
    "is_approved": true,
    "is_active": true,
    "account_status": "ACTIVE"
  }
}

Rejection Response (200):
{
  "message": "User rejected successfully",
  "user": {
    "id": "user-uuid",
    "email": "manager@pharmacy.com",
    "is_approved": false,
    "account_status": "REJECTED",
    "rejection_reason": "Does not meet requirements"
  }
}
```

---

#### 3. Get Pending Approval Count
```
GET /api/auth/pending-approval-count/
Authorization: Bearer {access_token}

Success Response (200):
{
  "pending_count": 5
}
```

---

#### 4. Get My Pharmacy Staff
```
GET /api/auth/my-staff/
Authorization: Bearer {access_token}

Query Parameters:
- role: Filter by role (PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF)
- status: Filter by approval status (approved, pending, all)
- limit: Number of results

Success Response (200):
{
  "results": [
    {
      "id": "user-uuid",
      "email": "pharmacist@pharmacy.com",
      "first_name": "Bob",
      "last_name": "Pharmacist",
      "full_name": "Bob Pharmacist",
      "role": "PHARMACIST",
      "is_approved": true,
      "is_active": true,
      "date_joined": "2026-08-28T10:00:00.123456Z"
    }
  ]
}
```

---

#### 5. Get My Pharmacy Memberships
```
GET /api/pharmacy/my-memberships/
Authorization: Bearer {access_token}

Success Response (200):
{
  "results": [
    {
      "id": "membership-uuid",
      "user": {
        "id": "user-uuid",
        "email": "manager@pharmacy.com",
        "full_name": "Alice Manager",
        "role": "PHARMACY_MANAGER"
      },
      "pharmacy": {
        "id": "pharmacy-uuid",
        "brand_name": "John's Pharmacy"
      },
      "role_in_pharmacy": "PHARMACY_MANAGER",
      "is_approved": true,
      "approved_at": "2026-08-29T13:39:24.123456Z",
      "approved_by": {
        "id": "owner-uuid",
        "email": "owner@pharmacy.com"
      }
    }
  ]
}
```

---

### 📦 Inventory Management Endpoints

#### 1. Get Pharmacy Inventory
```
GET /api/inventory/items/?pharmacy_id={pharmacy_id}&status=ACTIVE&published=true
Authorization: Bearer {access_token}

Query Parameters:
- pharmacy_id: Filter by pharmacy (required for staff, auto-filled for owner)
- status: ACTIVE or INACTIVE
- published: true or false
- limit: Number of results

Success Response (200):
{
  "count": 50,
  "results": [
    {
      "id": "item-uuid",
      "pharmacy": {
        "id": "pharmacy-uuid",
        "brand_name": "John's Pharmacy"
      },
      "medicine": {
        "id": "medicine-uuid",
        "generic_name": "Paracetamol",
        "brand_name": "Panadol",
        "strength": "500mg",
        "dosage_form": "TABLET",
        "route": "ORAL"
      },
      "selling_price": "500.00",
      "status": "ACTIVE",
      "is_published": true,
      "published_at": "2026-08-29T13:39:24.123456Z",
      "published_by": {
        "id": "user-uuid",
        "email": "manager@pharmacy.com"
      }
    }
  ]
}
```

---

#### 2. Create Inventory Item
```
POST /api/inventory/items/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body:
{
  "pharmacy": "pharmacy-uuid",
  "medicine": "medicine-uuid",
  "selling_price": "500.00",
  "status": "ACTIVE",
  "is_published": true
}

Success Response (201):
{
  "id": "item-uuid",
  "pharmacy": { ... },
  "medicine": { ... },
  "selling_price": "500.00",
  "status": "ACTIVE",
  "is_published": true,
  "created_at": "2026-08-29T13:39:24.123456Z"
}
```

---

#### 3. Update Inventory Item
```
PUT /api/inventory/items/{item_id}/
Authorization: Bearer {access_token}
Content-Type: application/json

Request Body:
{
  "selling_price": "550.00",
  "status": "ACTIVE",
  "is_published": false
}

Success Response (200):
{
  "id": "item-uuid",
  "selling_price": "550.00",
  "status": "ACTIVE",
  "is_published": false,
  ...
}
```

---

### 💊 Medicine Catalog Endpoints

#### 1. Get All Medicines
```
GET /api/medicines/?generic_name=Paracetamol&limit=20&offset=0
Authorization: Bearer {access_token}

Query Parameters:
- generic_name: Filter by generic name
- brand_name: Filter by brand name
- dosage_form: Filter by dosage form (TABLET, CAPSULE, SYRUP, etc.)
- route: Filter by route (ORAL, INTRAVENOUS, TOPICAL, etc.)
- limit: Number of results
- offset: Pagination offset
- search: Search across all fields

Success Response (200):
{
  "count": 500,
  "results": [
    {
      "id": "medicine-uuid",
      "generic_name": "Paracetamol",
      "brand_name": "Panadol",
      "strength": "500mg",
      "dosage_form": "TABLET",
      "route": "ORAL",
      "pack_size_unit": "STRIP",
      "pack_size_quantity": 10,
      "manufacturer": "GlaxoSmithKline",
      "sku": "PANADOL-500MG",
      "is_prescription_required": false,
      "created_at": "2026-08-01T10:00:00.123456Z"
    }
  ]
}
```

---

#### 2. Get Single Medicine
```
GET /api/medicines/{medicine_id}/
Authorization: Bearer {access_token}

Success Response (200):
{
  "id": "medicine-uuid",
  "generic_name": "Paracetamol",
  "brand_name": "Panadol",
  "strength": "500mg",
  "dosage_form": "TABLET",
  "route": "ORAL",
  "pack_size_unit": "STRIP",
  "pack_size_quantity": 10,
  "manufacturer": "GlaxoSmithKline",
  "sku": "PANADOL-500MG",
  "is_prescription_required": false
}
```

---

### 💰 Sales & Transactions (if applicable)

#### 1. Get Sales Records
```
GET /api/sales/?pharmacy_id={pharmacy_id}&start_date=2026-08-01&end_date=2026-08-31
Authorization: Bearer {access_token}

Query Parameters:
- pharmacy_id: Filter by pharmacy
- start_date: Filter by date range (YYYY-MM-DD)
- end_date: End of date range
- status: COMPLETED, PENDING, CANCELLED
- limit: Number of results

Success Response (200):
{
  "count": 100,
  "results": [
    {
      "id": "sale-uuid",
      "pharmacy": { ... },
      "items": [ ... ],
      "total_amount": "2500.00",
      "status": "COMPLETED",
      "created_at": "2026-08-29T13:39:24.123456Z"
    }
  ]
}
```

---

## Permission Matrix

### Complete Permission Table

| Endpoint | GET | POST | PUT | DELETE | SUPER_ADMIN | PLATFORM_ADMIN | PHARMACY_OWNER | PHARMACY_MANAGER | PHARMACIST | PHARMACY_STAFF |
|----------|-----|------|-----|--------|-------------|----------------|-----------------|-----------------|-----------|----------------|
| `/auth/register/` | - | ✅ (Public) | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/auth/login/` | - | ✅ (Public) | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/auth/me/` | ✅ | - | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/auth/profile/` | - | - | ✅ | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/auth/change-password/` | - | ✅ | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/auth/pending-users/` | ✅ | - | - | - | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `/auth/approve-user/` | - | ✅ | - | - | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `/auth/my-staff/` | ✅ | - | - | - | ✅ | ✅ | ✅ (own) | ⚠️ (read-only) | ⚠️ (read-only) | ⚠️ (read-only) |
| `/pharmacy/brands/` | ✅ | ✅ (Owner) | ✅ (Owner) | ⚠️ | ✅ | ✅ | ✅ (own) | ⚠️ | ⚠️ | ⚠️ |
| `/pharmacy/my-pharmacy/` | ✅ | - | ✅ | - | ✅ | ✅ | ✅ (own) | ✅ (own) | ✅ (own) | ✅ (own) |
| `/pharmacy/my-memberships/` | ✅ | - | - | - | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `/inventory/items/` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ (own) | ✅ (own) | ⚠️ | ⚠️ |
| `/medicines/` | ✅ | ✅ (Admin) | ✅ (Admin) | ✅ (Admin) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Legend:**
- ✅ = Full access
- ⚠️ = Limited access (read-only or own data only)
- ❌ = No access
- (Public) = No authentication required
- (Owner) = Only owner can perform action
- (own) = Only own data accessible

---

## Implementation Checklist

### Phase 1: Authentication & Authorization (CRITICAL - Do First)
- [ ] **Implement JWT Token Management**
  - [ ] Store `access_token` and `refresh_token` in localStorage
  - [ ] Send Authorization header in all authenticated requests: `Authorization: Bearer {access_token}`
  - [ ] Implement auto-token refresh when 401 is received
  - [ ] Clear tokens on logout

- [ ] **Implement Registration Flow**
  - [ ] Create registration form with: email, first_name, last_name, phone_number, password, password_confirm, role
  - [ ] Show role selection: PHARMACY_OWNER, PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF
  - [ ] Store registration response
  - [ ] Redirect to email verification page

- [ ] **Implement Email Verification**
  - [ ] Capture verification token from email link
  - [ ] Create verification form
  - [ ] Handle verification responses
  - [ ] Show appropriate messages for different account statuses

- [ ] **Implement Login Flow**
  - [ ] Create login form
  - [ ] Handle different error types:
    - Invalid credentials
    - Account not verified
    - Account pending approval
    - Account suspended
  - [ ] Store user data and tokens
  - [ ] Redirect based on user role and approval status

- [ ] **Implement Permission Checks**
  - [ ] Create utility function: `hasPermission(action, userRole, isApproved, isVerified, accountStatus)`
  - [ ] Use in UI to show/hide features
  - [ ] Disable buttons/forms for unauthorized users
  - [ ] Show permission denied messages

### Phase 2: User Dashboard & Profile
- [ ] **Dashboard Layout**
  - [ ] Create role-based dashboard views (different for each role)
  - [ ] Show user info summary
  - [ ] Show pending approval count (for admins/owners)
  - [ ] Show pharmacy status (if applicable)

- [ ] **Profile Management**
  - [ ] Create profile view page
  - [ ] Implement profile edit functionality
  - [ ] Implement password change
  - [ ] Show account status and approval information

### Phase 3: Pharmacy Management (PHARMACY_OWNER)
- [ ] **Pharmacy Registration & Profile**
  - [ ] Create pharmacy registration form
  - [ ] Implement pharmacy profile view
  - [ ] Implement pharmacy profile editing
  - [ ] Show verification status
  - [ ] Show location on map

- [ ] **Staff Management (PHARMACY_OWNER)**
  - [ ] List pharmacy staff
  - [ ] Show pending approval count
  - [ ] Implement approval/rejection flow
  - [ ] Filter staff by role and approval status

### Phase 4: Inventory Management
- [ ] **Inventory List**
  - [ ] Display inventory items with medicine details
  - [ ] Implement filters by status, published status
  - [ ] Implement search by medicine name
  - [ ] Show selling price

- [ ] **Inventory Operations**
  - [ ] Create inventory item
  - [ ] Edit inventory item (price, status, publication)
  - [ ] Delete inventory item
  - [ ] Publish/unpublish items

### Phase 5: Medicines Catalog
- [ ] **Browse Medicines**
  - [ ] Display all medicines in catalog
  - [ ] Implement search and filters
  - [ ] Show medicine details (generic name, brand, strength, dosage form, route)

### Phase 6: User Approval Workflow (ADMIN)
- [ ] **Pending Users List**
  - [ ] Show pending users with filters
  - [ ] Display user details
  - [ ] Implement approve/reject buttons

- [ ] **Pharmacy Verification** (if needed)
  - [ ] Show pending pharmacies
  - [ ] Review pharmacy documents
  - [ ] Approve/reject pharmacies

### Phase 7: Error Handling & Edge Cases
- [ ] Handle all HTTP error codes with appropriate messages
- [ ] Handle network errors gracefully
- [ ] Implement loading states for all async operations
- [ ] Implement retry logic for failed requests
- [ ] Handle token expiration and refresh
- [ ] Show validation errors from backend
- [ ] Handle permission denied scenarios

### Phase 8: Testing Checklist
- [ ] Test registration flow with all user roles
- [ ] Test email verification
- [ ] Test login with different account statuses
- [ ] Test token refresh
- [ ] Test permission checks for all endpoints
- [ ] Test profile updates
- [ ] Test pharmacy operations (create, update, verify)
- [ ] Test staff approval workflow
- [ ] Test inventory management
- [ ] Test error handling for all scenarios

---

## Critical Implementation Notes

### 1. **User Approval Workflow is CRITICAL**

The system has a multi-step approval process:

```
User Registration
    ↓
Email Verification (Required)
    ↓
Admin Approval (For most roles)
    ↓
Account Status = ACTIVE
```

**Frontend MUST:**
- Show clear status messages after each step
- Prevent login until all steps complete
- Show waiting message while approval is pending
- Handle rejection gracefully with clear messaging

---

### 2. **Pharmacy Ownership vs Staff Membership**

```
PHARMACY_OWNER:
- Creates pharmacy brand
- Owns exactly ONE verified pharmacy
- Can manage staff for their pharmacy
- Cannot see other pharmacies

Staff (MANAGER, PHARMACIST, STAFF):
- Do NOT own pharmacy
- Register with existing verified pharmacy
- Requires approval from pharmacy owner
- Can only see their assigned pharmacy
```

**Frontend MUST:**
- Prevent PHARMACY_OWNER from selecting pharmacy during registration
- Require staff to select verified pharmacy during registration
- Show only assigned pharmacy data to staff

---

### 3. **Permission Checks MUST Happen in Multiple Places**

```javascript
// 1. At Navigation Level
if (!user.is_approved) {
  hideMenu(['Staff Management', 'Inventory', 'Sales'])
}

// 2. At Component Level
if (!canEditInventory(user)) {
  disableEditButtons()
  showReadOnlyView()
}

// 3. At Request Level
if (!user.is_verified) {
  throw new Error("Email verification required")
}

// 4. Handle Response Errors
if (response.status === 403) {
  showPermissionDeniedMessage()
}
```

---

### 4. **Token Refresh Implementation**

```javascript
// Intercept 401 responses and refresh token
if (response.status === 401) {
  const refreshResponse = await fetch('/api/auth/token/refresh/', {
    method: 'POST',
    body: JSON.stringify({
      refresh: localStorage.getItem('refresh_token')
    })
  })
  
  if (refreshResponse.ok) {
    // Save new token and retry original request
    const data = await refreshResponse.json()
    localStorage.setItem('access_token', data.access)
    // Retry original request
  } else {
    // Redirect to login
    redirectToLogin()
  }
}
```

---

### 5. **Error Messages Should Be User-Friendly**

```javascript
// NOT THIS:
"DetailException: HTTP 400: Invalid request payload"

// DO THIS:
"Please enter a valid email address"
"This email is already registered. Try logging in instead."
"Your account is suspended. Contact support for assistance."
"Passwords do not match. Please try again."
```

---

### 6. **Pharmacy Location Handling**

Location can be stored in two formats:
- GIS format: Point object with x (longitude), y (latitude)
- Text format: "longitude,latitude" string

**Frontend MUST:**
- Accept location input as latitude/longitude
- Send as "longitude,latitude" format
- Display on map using received coordinates
- Handle missing location gracefully

---

### 7. **Inventory Publication Status**

```javascript
is_published = false  // Hidden from Smart Medicine Finder
is_published = true   // Visible in search/catalog

// PHARMACY_OWNER/MANAGER must explicitly publish items
// for them to appear in customer search
```

---

### 8. **OTP System (Optional but Recommended)**

The backend supports OTP for additional security:

```
Request OTP:
POST /api/auth/otp/request/
{
  "email": "user@example.com",
  "otp_type": "EMAIL_VERIFICATION",
  "send_via": "EMAIL"
}

Verify OTP:
POST /api/auth/otp/verify/
{
  "email": "user@example.com",
  "otp_code": "123456",
  "otp_type": "EMAIL_VERIFICATION"
}
```

Note: Backend handles Redis connection errors gracefully (sends OTP synchronously if Redis fails)

---

### 9. **Role-Based UI Layout**

```javascript
const dashboardLayout = {
  'SUPER_ADMIN': [
    'Users Management',
    'Pharmacy Verification',
    'Platform Analytics',
    'Settings'
  ],
  'PHARMACY_OWNER': [
    'My Pharmacy',
    'Staff Management',
    'Inventory',
    'Sales Reports',
    'Profile'
  ],
  'PHARMACY_MANAGER': [
    'Staff Directory',
    'Inventory',
    'Sales',
    'Profile'
  ],
  'PHARMACIST': [
    'Inventory (Read-Only)',
    'Sales (Read-Only)',
    'Profile'
  ],
  'PHARMACY_STAFF': [
    'Inventory (Read-Only)',
    'Sales (Read-Only)',
    'Profile'
  ]
}
```

---

### 10. **Data Privacy & Security**

```javascript
// DO:
✅ Store only essential user data in frontend
✅ Clear tokens on logout
✅ Use HTTPS for all requests
✅ Validate all user inputs
✅ Never expose sensitive info (like rejection reasons) carelessly
✅ Show appropriate error messages without exposing backend details

// DON'T:
❌ Store passwords anywhere
❌ Store full pharmacy staff list in localStorage
❌ Display full error messages from backend to users
❌ Make unauthenticated API calls
❌ Store refresh token in cookies without HttpOnly flag
```

---

## API Base URL

```
Development:  http://localhost:8000/api
Staging:      https://staging-api.example.com/api
Production:   https://api.example.com/api
```

---

## Rate Limiting

```
Anonymous Endpoints:
- Register: 5 per hour
- Login: 10 per minute
- Password Reset: 3 per hour
- Email Verification: 5 per hour

Authenticated Endpoints:
- General: 60 per minute
```

If you exceed rate limits, you'll receive a 429 (Too Many Requests) response.

---

## Common Implementation Patterns

### Pattern 1: Checking Permission Before Showing Component

```javascript
// ✅ Correct
<PharmacyStaffManagement>
  {canApproveUsers(user) ? (
    <ApprovalPanel />
  ) : (
    <ReadOnlyStaffList />
  )}
</PharmacyStaffManagement>

function canApproveUsers(user) {
  return (
    user.role === 'PHARMACY_OWNER' &&
    user.is_approved &&
    user.is_verified &&
    user.account_status === 'ACTIVE'
  )
}
```

### Pattern 2: Handling Approval Status

```javascript
// ✅ Correct
function RegistrationComplete() {
  const [status, setStatus] = useState('verifying')
  
  if (status === 'verifying') {
    return <VerificationPendingMessage />
  } else if (status === 'verified' && !user.is_approved) {
    return <ApprovalPendingMessage />
  } else if (user.account_status === 'ACTIVE') {
    return <RegistrationSuccessful />
  }
}
```

### Pattern 3: Protected API Calls

```javascript
// ✅ Correct
async function getMyPharmacy() {
  if (!user.is_verified) {
    throw new Error("Email verification required")
  }
  
  const response = await fetch('/api/pharmacy/my-pharmacy/', {
    headers: {
      'Authorization': `Bearer ${getAccessToken()}`,
      'Content-Type': 'application/json'
    }
  })
  
  if (response.status === 401) {
    await refreshToken()
    return getMyPharmacy() // Retry
  }
  
  return await response.json()
}
```

---

## Troubleshooting Guide

### Issue: "Account not verified" on login
**Solution:** 
1. Check inbox for verification email
2. Click verification link in email
3. Wait for approval (if required)
4. Try login again

### Issue: "Account is not approved"
**Solution:**
1. Admin needs to approve the account
2. User should see "Pending Approval" message
3. Wait for admin to review
4. Check email for approval notification

### Issue: 401 Unauthorized on authenticated request
**Solution:**
1. Try refreshing token using refresh_token
2. If refresh fails, redirect to login
3. Clear localStorage and request fresh login

### Issue: Permission denied error
**Solution:**
1. Check user role matches required role
2. Check user.is_approved status
3. Check user.account_status = 'ACTIVE'
4. Verify email (is_verified = True)

---

## Contact & Support

For backend API issues:
- Check this documentation first
- Review error messages and HTTP status codes
- Check permission matrix
- Contact backend team with specific endpoint and user role

---

**Documentation Version:** 1.0  
**Last Updated:** August 29, 2026  
**Next Review:** When backend changes are made
