from django.db import IntegrityError, transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from .models import PharmacyBrand, PharmacyMembership, PharmacyVerificationHistory


@transaction.atomic
def repair_missing_pharmacy_ids(brand=None):
    queryset = PharmacyBrand.objects.filter(verification_status='VERIFIED', pharmacy_id__isnull=True)
    if brand is not None:
        queryset = queryset.filter(pk=brand.pk)

    brands = list(queryset.select_for_update())
    repaired = []

    for existing_brand in brands:
        for _ in range(5):
            existing_brand.pharmacy_id = PharmacyBrand.generate_pharmacy_id()
            try:
                with transaction.atomic():
                    existing_brand.save(update_fields=['pharmacy_id', 'updated_at'])
                repaired.append(existing_brand)
                break
            except IntegrityError:
                existing_brand.pharmacy_id = None
        else:
            raise ValueError('Unable to generate a unique Pharmacy ID')

    return repaired


def create_pharmacy_brand(owner, **data):
    # Owner must be a PHARMACY_OWNER and active/verified
    if owner.role != 'PHARMACY_OWNER':
        raise ValueError('Only a user with role PHARMACY_OWNER can create a PharmacyBrand')
    if not owner.is_active or not owner.is_verified:
        raise ValueError('Owner must be active and verified')
    if PharmacyBrand.objects.filter(owner=owner).exists():
        raise ValueError('This owner already has a pharmacy brand. Please resume or manage the existing registration.')
    data['brand_name'] = data['brand_name'].strip()
    with transaction.atomic():
        return PharmacyBrand.objects.create(owner=owner, **data)


@transaction.atomic
def submit_pharmacy_brand(brand, owner):
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.owner_id != owner.id:
        raise ValueError('You can only submit your own pharmacy')
    brand.submit_for_verification()
    return brand


@transaction.atomic
def start_pharmacy_review(brand, reviewer):
    if reviewer.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
        raise ValueError('Only platform admins can start a pharmacy review')
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.verification_status != 'PENDING_VERIFICATION':
        raise ValueError('Only pending pharmacies can start review')
    now = timezone.now()
    previous = brand.verification_status
    brand.verification_status = 'UNDER_REVIEW'
    brand.review_started_by = reviewer
    brand.review_started_at = now
    brand.save(update_fields=['verification_status', 'review_started_by', 'review_started_at', 'updated_at'])
    PharmacyVerificationHistory.objects.create(
        pharmacy_brand=brand, previous_status=previous, new_status=brand.verification_status,
        action='REVIEW_STARTED', performed_by=reviewer,
    )
    return brand


@transaction.atomic
def approve_pharmacy_brand(brand, approver):
    if approver.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
        raise ValueError('Only platform admins can approve a pharmacy')
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.verification_status not in ('PENDING_VERIFICATION', 'UNDER_REVIEW'):
        raise ValueError('Only pharmacies under verification review can be approved')
    previous = brand.verification_status
    now = timezone.now()
    brand.verification_status = 'VERIFIED'
    brand.verified_by = approver
    brand.verified_at = now
    if not brand.pharmacy_id:
        for _ in range(5):
            brand.pharmacy_id = PharmacyBrand.generate_pharmacy_id()
            try:
                with transaction.atomic():
                    brand.save(update_fields=['verification_status', 'verified_by', 'verified_at', 'pharmacy_id', 'updated_at'])
                break
            except IntegrityError:
                brand.pharmacy_id = None
        else:
            raise ValueError('Unable to generate a unique Pharmacy ID')
    else:
        brand.save(update_fields=['verification_status', 'verified_by', 'verified_at', 'updated_at'])
    PharmacyVerificationHistory.objects.create(
        pharmacy_brand=brand, previous_status=previous, new_status='VERIFIED',
        action='APPROVED', performed_by=approver,
    )
    return brand


@transaction.atomic
def reject_pharmacy_brand(brand, approver, reason=''):
    if approver.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
        raise ValueError('Only platform admins can reject a pharmacy')
    if not reason or not reason.strip():
        raise ValueError('A rejection reason is required')
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.verification_status not in ('PENDING_VERIFICATION', 'UNDER_REVIEW'):
        raise ValueError('Only pharmacies under verification review can be rejected')
    previous = brand.verification_status
    now = timezone.now()
    brand.verification_status = 'REJECTED'
    brand.rejected_by = approver
    brand.rejected_at = now
    brand.rejection_reason = reason.strip()
    brand.save(update_fields=['verification_status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at'])
    PharmacyVerificationHistory.objects.create(
        pharmacy_brand=brand, previous_status=previous, new_status='REJECTED',
        action='REJECTED', performed_by=approver, reason=reason.strip(),
    )
    return brand


@transaction.atomic
def suspend_pharmacy_brand(brand, approver, reason=''):
    if approver.role != 'SUPER_ADMIN':
        raise ValueError('Only super admins can suspend a pharmacy')
    if not reason or not reason.strip():
        raise ValueError('A suspension reason is required')
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.verification_status != 'VERIFIED':
        raise ValueError('Only verified pharmacies can be suspended')
    previous = brand.verification_status
    now = timezone.now()
    brand.verification_status = 'SUSPENDED'
    brand.suspended_by = approver
    brand.suspended_at = now
    brand.suspension_reason = reason.strip()
    brand.save(update_fields=['verification_status', 'suspended_by', 'suspended_at', 'suspension_reason', 'updated_at'])
    PharmacyVerificationHistory.objects.create(
        pharmacy_brand=brand, previous_status=previous, new_status='SUSPENDED',
        action='SUSPENDED', performed_by=approver, reason=reason.strip(),
    )
    return brand


def create_membership_request(user, pharmacy, role):
    if user.role not in dict(PharmacyMembership.ROLE_CHOICES):
        raise ValueError('Only pharmacy employees can request membership')
    if not user.is_active or not user.is_verified or user.account_status != 'ACTIVE':
        raise ValueError('Your account must be active and verified before requesting membership')
    if not pharmacy.is_verified:
        raise ValueError('Cannot request membership for unverified pharmacy')
    if role != user.role:
        raise ValueError('Requested role must match the authenticated user role')
    existing = PharmacyMembership.objects.filter(user=user, pharmacy=pharmacy).first()
    if existing:
        if existing.status == 'PENDING':
            raise ValueError('You already have a pending request to join this pharmacy')
        if existing.status == 'APPROVED':
            raise ValueError('You are already a member of this pharmacy')
        raise ValueError('A membership request already exists for this pharmacy')
    membership = PharmacyMembership.objects.create(user=user, pharmacy=pharmacy, role=role)
    return membership


@transaction.atomic
def regenerate_pharmacy_id(brand, owner):
    brand = PharmacyBrand.objects.select_for_update().get(pk=brand.pk)
    if brand.owner_id != owner.id:
        raise ValueError('You can only regenerate your own Pharmacy ID')
    if not brand.is_verified:
        raise ValueError('Only approved pharmacies can regenerate a Pharmacy ID')
    for _ in range(5):
        brand.pharmacy_id = PharmacyBrand.generate_pharmacy_id()
        try:
            with transaction.atomic():
                brand.save(update_fields=['pharmacy_id', 'updated_at'])
            return brand
        except IntegrityError:
            brand.pharmacy_id = None
    raise ValueError('Unable to generate a unique Pharmacy ID')


@transaction.atomic
def approve_membership(membership, approver):
    # Only owner or platform admins
    if approver.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER'):
        raise ValueError('Only owner or platform admins can approve membership')
    if approver == membership.user:
        raise ValueError('User cannot approve their own membership')
    # If approver is owner ensure they own the pharmacy
    if approver.role == 'PHARMACY_OWNER' and getattr(membership.pharmacy, 'owner_id', None) != approver.id:
        raise ValueError('Only the owning pharmacy owner can approve this membership')
    membership = PharmacyMembership.objects.select_for_update().select_related('pharmacy').get(pk=membership.pk)
    pharmacy = PharmacyBrand.objects.select_for_update().get(pk=membership.pharmacy_id)
    if membership.status != 'PENDING':
        raise ValueError('Only pending membership requests can be approved')
    if not pharmacy.is_verified:
        raise ValueError('The pharmacy is no longer available for membership approval')
    membership.approve(approver)
    return membership


@transaction.atomic
def reject_membership(membership, approver, reason=''):
    if approver.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER'):
        raise ValueError('Only owner or platform admins can reject membership')
    if approver == membership.user:
        raise ValueError('User cannot reject their own membership')
    if not reason or not reason.strip():
        raise ValueError('Rejection reason is required')
    if approver.role == 'PHARMACY_OWNER' and getattr(membership.pharmacy, 'owner_id', None) != approver.id:
        raise ValueError('Only the owning pharmacy owner can reject this membership')
    membership = PharmacyMembership.objects.select_for_update().get(pk=membership.pk)
    membership.reject(approver, reason=reason)
    return membership


@transaction.atomic
def suspend_membership(membership, approver):
    if approver.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN', 'PHARMACY_OWNER'):
        raise ValueError('Only owner or platform admins can suspend membership')
    if approver.role == 'PHARMACY_OWNER' and getattr(membership.pharmacy, 'owner_id', None) != approver.id:
        raise ValueError('Only the owning pharmacy owner can suspend this membership')
    membership = PharmacyMembership.objects.select_for_update().get(pk=membership.pk)
    membership.status = 'SUSPENDED'
    membership.approved_by = approver
    membership.approved_at = timezone.now()
    membership.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
    return membership
