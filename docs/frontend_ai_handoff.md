# Frontend AI Handoff — Current Backend Only

## Purpose and scope

Build a web frontend for the currently implemented Django REST API. The product is a pharmacy platform (the code refers to **Cafsule** and **Smart Medicine Finder**) with account management, pharmacy onboarding/verification, staff memberships, a global medicine catalog, and pharmacy-specific inventory.

This document is intentionally limited to functionality that exists in the backend as of this handoff. Do not assume checkout, customer medicine discovery by stock, orders, sales, payments, notifications, analytics, a public inventory search, or a public pharmacy-nearby route: none is currently exposed through the URL configuration.

## API integration conventions

- Base URL is environment-specific. Configure it as `VITE_API_BASE_URL` (or equivalent); all paths below start with `/api/`.
- Use JSON by default. Use `multipart/form-data` only for verification-document uploads.
- Protected requests require `Authorization: Bearer <access-token>`.
- Login returns an access token (30 minutes by default) and refresh token (7 days by default). Refresh tokens rotate, so overwrite the saved refresh token with the response’s new `refresh` value when supplied.
- On an expired access token, call `POST /api/auth/token/refresh/` with `{ "refresh": "..." }`, retry once, and otherwise sign the user out.
- UUIDs identify users, pharmacies, medicines, inventory items, memberships, and batches.
- Typical errors are `{ "detail": "..." }`, `{ "error": "..." }`, or field-level validation objects. Render the returned message rather than inventing one.
- CORS currently permits local Vite origins and all origins in development. Do not hard-code credentials/cookies; the API uses bearer JWTs.

## Roles and account state

Roles returned in `user.role`:

| Role | Current frontend capability |
| --- | --- |
| `SUPER_ADMIN`, `PLATFORM_ADMIN` | Administer medicine catalogue; review/approve/reject/suspend pharmacies; view all memberships and inventory. |
| `PHARMACY_OWNER` | Create and manage one owned pharmacy, submit it for verification, view membership requests, and manage its inventory. |
| `PHARMACY_MANAGER`, `PHARMACIST`, `PHARMACY_STAFF` | Register against a verified pharmacy, then use inventory once their pharmacy membership is approved. |

Account statuses are `UNVERIFIED`, `ACTIVE`, `PENDING_APPROVAL`, `SUSPENDED`, `DEACTIVATED`, and `REJECTED`. Registration creates an unverified account. Email verification makes it active. A staff member also needs an `APPROVED` membership for the target pharmacy before pharmacy access is granted.

Do not rely only on `user.role` for dashboard access. Load `GET /api/auth/me/` and, for pharmacy staff, `GET /api/pharmacy/my-memberships/`; gate actions based on the API responses and handle `403` cleanly.

## Suggested information architecture

Use these screens/routes; hide or disable actions the signed-in user cannot perform.

1. Public: pharmacy search/listing, sign in, registration, email verification, password reset.
2. Signed-in account: profile and change-password.
3. Pharmacy owner: create/edit pharmacy, verification status and submission, document upload, membership requests, inventory.
4. Pharmacy employee: membership status, medicine lookup, inventory (only after approved membership).
5. Platform admin: pending pharmacy-verification queue, pharmacy review actions, medicine management, all inventory and memberships.

There is no current dashboard-summary API. Build any dashboard counts from the list endpoints only if needed, or show simple navigation/status cards instead.

## Authentication endpoints

### Registration and sign-in

| Request | Body / result |
| --- | --- |
| `POST /api/auth/register/` | Required: `email`, `first_name`, `last_name`, `password`, `password_confirm`. Optional: `phone_number`, `role`, `pharmacy_brand` (verified pharmacy UUID). Staff roles (`PHARMACY_MANAGER`, `PHARMACIST`, `PHARMACY_STAFF`) require `pharmacy_brand`; `PHARMACY_OWNER` must not send it. Returns `message`, `user`, `requires_approval`. |
| `POST /api/auth/login/` | `{ "email": "...", "password": "..." }` → `{ "access", "refresh", "user" }`. |
| `POST /api/auth/logout/` | Authenticated. `{ "refresh": "..." }` → success message. Clear local auth state even if the request cannot complete. |
| `POST /api/auth/token/refresh/` | `{ "refresh": "..." }` → new `access` and, with rotation, new `refresh`. |
| `GET /api/auth/me/` | Authenticated current-user object. `PUT`/`PATCH` is technically supported by the same endpoint, but use the dedicated profile endpoint below. |

The user object is:

```ts
type User = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  phone_number: string;
  role: string;
  account_status: string;
  is_verified: boolean;
  is_active: boolean;
  date_joined: string;
  last_login: string | null;
};
```

Normalize Nigerian phone input in the UI if helpful, but send an E.164 value such as `+234XXXXXXXXXX` (the backend also normalizes common Nigerian formats).

### Profile, password, verification, and recovery

| Request | Body / result |
| --- | --- |
| `PATCH /api/auth/profile/` | Authenticated. Any of `first_name`, `last_name`, `phone_number` → `{ message, user }`. |
| `POST /api/auth/change-password/` | Authenticated. `current_password`, `new_password`, `new_password_confirm`. |
| `POST /api/auth/verify-email/` | `{ "token": "..." }` → success message. Use this for token links received by email. |
| `POST /api/auth/resend-verification/` | `{ "email": "..." }`. |
| `POST /api/auth/password/reset/` | `{ "email": "..." }`; response is deliberately non-enumerating. |
| `POST /api/auth/password/reset/confirm/` | `token`, `new_password`, `new_password_confirm`. |
| `POST /api/auth/otp/request/` | `email`, `otp_type`, optional `send_via` (`EMAIL`, `SMS`, `BOTH`). OTP types: `EMAIL_VERIFICATION`, `PASSWORD_RESET`, `LOGIN`, `PHONE_VERIFICATION`, `TWO_FACTOR`. |
| `POST /api/auth/otp/verify/` | `email`, six-character `otp_code`, `otp_type`. Email-verification and login OTP flows can return JWT tokens; password-reset returns `reset_token` for the confirm endpoint. |
| `POST /api/auth/oauth/` | `provider` (`GOOGLE`, `FACEBOOK`, `APPLE`), `provider_user_id`, optional `email`, `first_name`, `last_name`. This endpoint currently trusts provider data supplied by the frontend; do not present it as a hardened OAuth implementation. |

## Pharmacy APIs

### Public pharmacy discovery

`GET /api/pharmacy/brands/` and `GET /api/pharmacy/brands/search/?q=<text>` are public and return verified pharmacies only. The list item shape is:

```ts
type PharmacyListItem = {
  id: string;
  brand_name: string;
  legal_name: string;
  city: string;
  state: string;
  country: string;
  location: string | null;
  pharmacy_type: 'COMMUNITY_PHARMACY' | 'HOSPITAL_PHARMACY' | 'CLINIC_PHARMACY' |
                 'WHOLESALE_PHARMACY' | 'MEDICAL_STORE' | 'OTHER';
};
```

`location` represents a geographic point (PostGIS/WGS84); treat it as display/map data only. A nearby-search view exists in code but is **not wired to a URL**, so do not call it.

### Pharmacy owner onboarding and verification

| Request | Purpose |
| --- | --- |
| `POST /api/pharmacy/brands/` | Authenticated. Create a pharmacy owned by the current user. The backend requires an active, verified `PHARMACY_OWNER`. |
| `GET /api/pharmacy/my-pharmacy/` | Authenticated. Retrieve the pharmacy owned by the current user; `404` when none exists. |
| `GET /api/pharmacy/brands/{id}/` | Public users receive the limited list shape. Owners and platform admins receive full detail. |
| `PATCH /api/pharmacy/brands/{id}/` | Owner of the pharmacy or platform admin. Update business/address/basic fields. |
| `POST /api/pharmacy/brands/{id}/submit-for-verification/` | Owner submits a draft or rejected pharmacy. |
| `GET/POST /api/pharmacy/verification-documents/` | Authenticated document list/upload; owners see only their own documents, admins see all. |

Create payload fields:

```ts
type PharmacyCreate = {
  legal_name: string; brand_name: string; description?: string;
  business_email?: string; business_phone?: string;
  address_line_1?: string; address_line_2?: string;
  city?: string; state?: string; lga?: string; postal_code?: string;
  country?: string; // defaults to Nigeria
  pharmacy_type?: string; years_in_operation?: number;
  cac_registration_number?: string;
  pcn_premises_registration_number?: string;
  pcn_license_number?: string; pcn_issue_date?: string; pcn_expiry_date?: string;
  nafdac_registration_number?: string; nafdac_certificate_number?: string;
  nafdac_expiry_date?: string;
  location?: string; // backend PointField-compatible WGS84 value
};
```

The submission checklist enforced by the backend is: pharmacy name, address, state, CAC registration number, PCN premises registration information, latitude/longitude in `location`, at least two `EXTERIOR` images, and at least two `INTERIOR` images.

Important current limitation: there is a `PharmacyBrandImage` model/serializer, but no brand-image endpoint is routed. Therefore, the frontend cannot currently upload the required images through this API. Show the verification checklist/status, but make the blocked image requirement explicit instead of pretending it is completable.

For document upload, send `multipart/form-data` with `brand` (UUID), `document` (file), and `document_type` (`CAC_DOCUMENT`, `PCN_DOCUMENT`, or `NAFDAC_DOCUMENT`). Documents can only be uploaded while the pharmacy is `DRAFT` or `REJECTED`.

Verification statuses: `DRAFT`, `PENDING_VERIFICATION`, `UNDER_REVIEW`, `VERIFIED`, `REJECTED`, `SUSPENDED`. The detail endpoint intentionally omits `rejection_reason`; do not expect it in frontend data.

### Platform-admin pharmacy review

| Request | Purpose |
| --- | --- |
| `GET /api/pharmacy/brands/pending-verification/` | Pending and under-review pharmacy details. |
| `POST /api/pharmacy/brands/{id}/start-review/` | Move into review. |
| `POST /api/pharmacy/brands/{id}/approve/` | Verify/approve the pharmacy. |
| `POST /api/pharmacy/brands/{id}/reject/` | Body: `{ "reason": "..." }`; reason is required by the service. |
| `POST /api/pharmacy/brands/{id}/suspend/` | Super-admin only. Body requires `{ "reason": "..." }`. |

### Memberships and staff approval

A membership is the pharmacy-specific link between a user and pharmacy. Its role is `PHARMACY_MANAGER`, `PHARMACIST`, or `PHARMACY_STAFF`; its status is `PENDING`, `APPROVED`, `REJECTED`, or `SUSPENDED`.

| Request | Purpose |
| --- | --- |
| `GET /api/pharmacy/my-memberships/` | Authenticated user’s memberships. |
| `GET /api/pharmacy/memberships/` | Own memberships, or all memberships for platform admins. |
| `POST /api/pharmacy/memberships/` | Request membership: `{ "pharmacy": "<verified pharmacy UUID>", "role": "..." }`. |
| `GET /api/pharmacy/brands/{id}/membership-requests/` | Pending requests for an owned pharmacy (or admin). |
| `POST /api/pharmacy/memberships/{id}/approve/` | Owner/admin approves. |
| `POST /api/pharmacy/memberships/{id}/reject/` | Owner/admin; body requires `{ "reason": "..." }`. |
| `POST /api/pharmacy/memberships/{id}/suspend/` | Owner/admin suspends. |

Membership responses contain `id`, `user`, `pharmacy`, `role`, `status`, `approved_by`, `approved_at`, `rejection_reason`, `created_at`, and `updated_at`. The membership-requests route replaces `user` with a compact user object.

There are older owner staff endpoints under `/api/auth/` (`pending-users/`, `approve-user/`, `my-staff/`), but they are not reliably scoped to a pharmacy. Prefer the pharmacy membership endpoints above for all new UI.

## Medicine catalogue APIs

All medicine routes require authentication.

| Request | Purpose |
| --- | --- |
| `GET /api/medicine/medicines/?search=<text>` | List and optional generic/brand/strength search. |
| `GET /api/medicine/medicines/search/?q=<text>` | Search endpoint; query must be at least 2 characters; returns up to 50 results. |
| `GET /api/medicine/medicines/{id}/` | Full medicine detail. |
| `POST /api/medicine/medicines/` | Platform/super admin only. Create a global medicine. |
| `PATCH /api/medicine/medicines/{id}/` or `DELETE` | Platform/super admin only. |

List responses include `id`, `generic_name`, `brand_name`, `strength`, `dosage_form`, and `route`. Detail/create fields additionally include `manufacturer`, `pack_size`, `pack_size_unit`, `description`, and `nafdac_registration` (plus read-only audit fields on detail).

Use API enum values in forms: dosage forms `TABLET`, `CAPSULE`, `SYRUP`, `INJECTION`, `CREAM`, `OINTMENT`, `LOTION`, `SUSPENSION`, `SOLUTION`, `POWDER`, `PATCH`, `OTHER`; routes `ORAL`, `INTRAVENOUS`, `INTRAMUSCULAR`, `SUBCUTANEOUS`, `TOPICAL`, `RECTAL`, `INHALED`, `INTRANASAL`, `OTHER`; pack units `UNIT`, `STRIP`, `PACK`, `BOTTLE`, `VIAL`, `TUBE`, `JAR`, `ML`, `L`, `G`, `KG`, `MG`.

## Inventory APIs

All inventory endpoints are authenticated and role/membership scoped. A pharmacy owner gets their owned pharmacy’s items; an approved staff member gets items for their approved memberships; platform admins get all items.

| Request | Purpose |
| --- | --- |
| `GET /api/inventory/items/` | Inventory list. |
| `POST /api/inventory/items/` | Create `{ "medicine": "<UUID>", "selling_price": "1200.00", "status": "ACTIVE" }`. The backend derives the pharmacy from the caller. |
| `GET /api/inventory/items/{id}/` | Detail, including batches. |
| `PATCH /api/inventory/items/{id}/` | Update `selling_price` and/or `status` (`ACTIVE`/`INACTIVE`). |
| `POST /api/inventory/items/{id}/publish/` | Publish an item. Pharmacy must be verified, item active, price positive, and total non-expired stock positive. |
| `POST /api/inventory/items/{id}/unpublish/` | Unpublish an item. |
| `GET /api/inventory/items/{id}/batches/` | Item batches ordered by expiry. |
| `GET /api/inventory/batches/` | Batches user can access. |
| `POST /api/inventory/batches/` | Create a batch. Include `inventory_item_id` plus `batch_number`, `quantity`, `expiry_date`, optional `cost_per_unit`. |
| `PATCH /api/inventory/batches/{id}/` | Update batch data. |
| `DELETE /api/inventory/batches/{id}/` | Delete a batch. |

Inventory list item: `id`, `medicine_display`, `selling_price`, `status`, `is_published`, `total_quantity`, `created_at`.

Inventory detail additionally contains pharmacy and medicine UUIDs, `published_at`, `published_by`, `published_by_name`, `has_expired_stock`, `batches`, and timestamps. A batch has `id`, `batch_number`, `quantity`, `expiry_date`, `is_expired`, `days_until_expiry`, `cost_per_unit`, and `created_at`.

Use the returned `total_quantity`, `is_expired`, `days_until_expiry`, and `has_expired_stock` rather than independently calculating availability. Price is a decimal string; display it as Nigerian naira only if that matches the product decision—the model labels it NGN, but no currency-formatting API is supplied.

## UI states to support

- Loading, empty, validation-error, `401` re-authentication, and `403` no-access states for every protected resource.
- A registration completion state that prompts for email verification; registration does not return JWT tokens.
- Membership status cards: pending, approved, rejected (show `rejection_reason`), suspended.
- Pharmacy status badges: draft, pending verification, under review, verified, rejected, suspended.
- Inventory publish readiness: attempt publish only after at least one valid batch is present; surface backend failure reasons as the canonical result.
- Expiry warnings for expired batches and items with expired stock.

## Explicitly out of scope today

- Sales app UI/API (the app exists but has no project URL routes).
- Customer purchase, cart, order, reservation, delivery, payment, prescription, and payment history.
- Public medicine/inventory availability search and pharmacy-nearby search.
- Pharmacy image upload/management, despite image data being required by verification submission.
- Email/SMS delivery status, real-time notifications, analytics, audit-log screens, pagination contract, and a formal OpenAPI schema.

When an API behavior is uncertain, favor the backend response and avoid creating fictional endpoints or data fields.
