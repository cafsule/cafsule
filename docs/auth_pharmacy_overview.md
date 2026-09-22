# Auth and Pharmacy Overview

## Auth app (auth/)
- Responsible for user identity and authentication only. Key pieces:
  - `User` (custom `AbstractBaseUser`): email-based auth, roles, account status, verification and approval flags. Authentication, JWT/OAuth, password reset, OTP, and email verification remain unchanged.
  - Token and audit models: `EmailVerificationToken`, `PasswordResetToken`, `OTPVerification`, `UserActivityLog`.
  - Views/serializers/permissions that handle registration, login, social auth, and account lifecycle.
- Important rule: authentication is independent from pharmacy/business data. The `User` model no longer contains a direct `pharmacy_brand` FK — pharmacy relationships are handled by the `pharmacy` app via memberships.

## Pharmacy app (pharmacy/)
- Responsible for pharmacy/business domain and membership-based authorization. Key pieces:
  - `PharmacyBrand`: business entity (name, contact, CAC/PCN/NAFDAC fields, verification status), `owner` (linked to `User`, `on_delete=PROTECT`), and PostGIS-aware `location` (`PointField`, SRID=4326) for geospatial features.
  - `PharmacyBrandImage`: media for brand (front/interior/document images).
  - `PharmacyMembership`: NEW model representing a `User`'s relationship to a `PharmacyBrand` (role, membership `status`, `approved_by`, timestamps). Enforces a unique `(user, pharmacy)` constraint and separates pharmacy-specific approval/authorization from the `User` record.
- Approval model: `PharmacyBrand` has a verification/approval workflow (e.g., `PENDING_VERIFICATION` → `VERIFIED`), and `PharmacyMembership` has explicit statuses (`PENDING`, `APPROVED`, `REJECTED`, `SUSPENDED`).

## Authorization guidance
- Do not rely solely on `user.role` for pharmacy access. To grant pharmacy dashboard access, require:
  - `request.user` is active/verified,
  - an `APPROVED` `PharmacyMembership` for the target `PharmacyBrand`, and
  - the `PharmacyBrand` itself is `VERIFIED`/`APPROVED`.

This separation preserves the existing auth system while moving pharmacy/business concerns into the `pharmacy` domain.
