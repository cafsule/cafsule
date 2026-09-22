import uuid
import secrets
import string

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils import timezone

from django.conf import settings
try:
    from django.contrib.gis.db import models as gis_models
    from django.contrib.gis.geos import Point
except Exception:
    gis_models = None
    Point = None


class PharmacyBrand(models.Model):
    """A real pharmacy business/brand registered on Cafsule.

    Location is stored in PostGIS as a `Point` with SRID 4326 (WGS84), using
    `location = gis_models.PointField(geography=True, srid=4326)`.
    ``latitude`` and ``longitude`` are exposed as read-only properties that
    read from `location` for backward compatibility.
    """

    VERIFICATION_STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PENDING_VERIFICATION', 'Pending Verification'),
        ('UNDER_REVIEW', 'Under Review'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
        ('SUSPENDED', 'Suspended'),
    )

    PHARMACY_TYPE_CHOICES = (
        ('COMMUNITY_PHARMACY', 'Community Pharmacy'),
        ('HOSPITAL_PHARMACY', 'Hospital Pharmacy'),
        ('CLINIC_PHARMACY', 'Clinic Pharmacy'),
        ('WHOLESALE_PHARMACY', 'Wholesale Pharmacy'),
        ('MEDICAL_STORE', 'Medical Store'),
        ('OTHER', 'Other'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy_id = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    owner = models.OneToOneField(
        'auth_app.User',
        on_delete=models.PROTECT,
        related_name='owned_pharmacy_brand',
        limit_choices_to={'role': 'PHARMACY_OWNER'},
    )
    legal_name = models.CharField(max_length=255)
    brand_name = models.CharField(max_length=255,unique=True)
    description = models.TextField(blank=True, default='')

    business_email = models.EmailField(max_length=255, blank=True, default='')
    business_phone = models.CharField(max_length=20, blank=True, default='')

    address_line_1 = models.CharField(max_length=255, blank=True, default='')
    address_line_2 = models.CharField(max_length=255, blank=True, default='')
    city = models.CharField(max_length=100, blank=True, default='')
    state = models.CharField(max_length=100, blank=True, default='')
    lga = models.CharField(max_length=100, blank=True, default='')
    postal_code = models.CharField(max_length=20, blank=True, default='')
    country = models.CharField(max_length=100, default='Nigeria')
    opnetime=models.TimeField(default='09:00:00')
    closetime=models.TimeField(null=True, blank=True)

    # Use PostGIS PointField with geography type for coordinate storage.
    # Geography type supports proper distance calculations across the Earth's surface.
    location = gis_models.PointField(geography=True, srid=4326, null=True, blank=True)

    pharmacy_type = models.CharField(
        max_length=30,
        choices=PHARMACY_TYPE_CHOICES,
        default='COMMUNITY_PHARMACY',
    )
    years_in_operation = models.PositiveIntegerField(default=0)

    cac_registration_number = models.CharField(max_length=100, blank=True, default='')
    cac_registration_type = models.CharField(max_length=100, blank=True, default='')
    pcn_premises_registration_number = models.CharField(max_length=100, blank=True, default='')
    pcn_license_number = models.CharField(max_length=100, blank=True, default='')
    pcn_issue_date = models.DateField(null=True, blank=True)
    pcn_expiry_date = models.DateField(null=True, blank=True)
    nafdac_registration_number = models.CharField(max_length=100, blank=True, default='')
    nafdac_certificate_number = models.CharField(max_length=100, blank=True, default='')
    nafdac_expiry_date = models.DateField(null=True, blank=True)

    verification_status = models.CharField(
        max_length=30,
        choices=VERIFICATION_STATUS_CHOICES,
        default='DRAFT',
    )
    verified_by = models.ForeignKey(
        'auth_app.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_pharmacy_brands',
        limit_choices_to=(Q(role='SUPER_ADMIN') | Q(role='PLATFORM_ADMIN')),
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    review_started_by = models.ForeignKey(
        'auth_app.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='started_pharmacy_reviews',
    )
    review_started_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        'auth_app.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='rejected_pharmacy_brands',
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    suspended_by = models.ForeignKey(
        'auth_app.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='suspended_pharmacy_brands',
    )
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspension_reason = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pharmacy_brand'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner']),
            models.Index(fields=['verification_status']),
            models.Index(fields=['brand_name']),
            models.Index(fields=['cac_registration_number']),
            models.Index(fields=['pcn_license_number']),
            models.Index(fields=['nafdac_registration_number']),
        ]
        constraints = [
            models.UniqueConstraint(
                Lower(Trim('brand_name')),
                name='unique_pharmacy_brand_name_ci',
            ),
        ]

    def save(self, *args, **kwargs):
        self.brand_name = self.brand_name.strip()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_pharmacy_id():
        alphabet = string.ascii_uppercase + string.digits
        return 'CFS-PHARM-' + ''.join(secrets.choice(alphabet) for _ in range(10))

    def __str__(self):
        return self.brand_name or self.legal_name or f"PharmacyBrand {self.id}"

    @property
    def latitude(self):
        if not self.location:
            return None
        try:
            return float(self.location.y)
        except Exception:
            try:
                return float(str(self.location).split()[1])
            except (IndexError, ValueError):
                return None

    @property
    def longitude(self):
        if not self.location:
            return None
        try:
            return float(self.location.x)
        except Exception:
            try:
                return float(str(self.location).split()[0])
            except (IndexError, ValueError):
                return None

    @property
    def is_verified(self):
        return self.verification_status == 'VERIFIED'

    @property
    def is_awaiting_verification(self):
        return self.verification_status in {'PENDING_VERIFICATION', 'UNDER_REVIEW'}

    def submit_for_verification(self):
        if self.verification_status not in {'DRAFT', 'REJECTED'}:
            raise ValueError('Only draft or rejected pharmacies can be submitted')
        validate_submission(self)
        previous = self.verification_status
        self.verification_status = 'PENDING_VERIFICATION'
        self.rejection_reason = ''
        self.save(update_fields=['verification_status', 'rejection_reason', 'updated_at'])
        PharmacyVerificationHistory.objects.create(
            pharmacy_brand=self, previous_status=previous,
            new_status=self.verification_status, action='SUBMITTED',
            performed_by=self.owner,
        )


class PharmacyMembership(models.Model):
    """Represents a user's relationship with a PharmacyBrand.

    Memberships capture pharmacy-specific role, approval state and audit
    information. This decouples user authentication from pharmacy
    authorization.
    """

    ROLE_CHOICES = (
        ('PHARMACY_MANAGER', 'Pharmacy Manager'),
        ('PHARMACIST', 'Pharmacist'),
        ('PHARMACY_STAFF', 'Pharmacy Staff'),
    )

    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SUSPENDED', 'Suspended'),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    pharmacy = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    user = models.ForeignKey(
        'auth_app.User',
        on_delete=models.CASCADE,
        related_name='pharmacy_memberships',
    )
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey(
        'auth_app.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_pharmacy_memberships',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'pharmacy_membership'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'pharmacy'], name='unique_user_pharmacy_membership')
        ]

    def __str__(self):
        return f"{self.user.email} -> {self.pharmacy.brand_name} ({self.role}) [{self.status}]"

    def approve(self, approver):
        if approver == self.user:
            raise ValueError('Users cannot approve their own membership')
        if approver.role != 'PHARMACY_OWNER' and approver.role not in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}:
            raise ValueError('Only a pharmacy owner or platform admin can approve memberships')
        self.status = 'APPROVED'
        self.approved_by = approver
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def reject(self, approver, reason=''):
        if approver == self.user:
            raise ValueError('Users cannot reject their own membership')
        if approver.role != 'PHARMACY_OWNER' and approver.role not in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}:
            raise ValueError('Only a pharmacy owner or platform admin can reject memberships')
        if not reason or not reason.strip():
            raise ValueError('Rejection reason is required')
        self.status = 'REJECTED'
        self.approved_by = approver
        self.approved_at = timezone.now()
        self.rejection_reason = reason.strip()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at'])

class PharmacyVerificationDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = (
        ('CAC_DOCUMENT', 'CAC Document'), ('PCN_DOCUMENT', 'PCN Document'),
        ('NAFDAC_DOCUMENT', 'NAFDAC Document'),
    )
    STATUS_CHOICES = (
        ('PENDING_REVIEW', 'Pending Review'), ('ACCEPTED', 'Accepted'),
        ('REJECTED', 'Rejected'),
    )
    brand = models.ForeignKey(PharmacyBrand, on_delete=models.CASCADE, related_name='verification_documents')
    document = models.FileField(upload_to='pharmacy/verification/%Y/%m/%d/')
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    review_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING_REVIEW')
    uploaded_at = models.DateTimeField(auto_now_add=True)


class PharmacyVerificationHistory(models.Model):
    ACTION_CHOICES = (
        ('SUBMITTED', 'Submitted'), ('REVIEW_STARTED', 'Review Started'),
        ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'),
        ('SUSPENDED', 'Suspended'), ('REINSTATED', 'Reinstated'),
    )
    pharmacy_brand = models.ForeignKey(PharmacyBrand, on_delete=models.CASCADE, related_name='verification_history')
    previous_status = models.CharField(max_length=30)
    new_status = models.CharField(max_length=30)
    action = models.CharField(max_length=30, choices=ACTION_CHOICES)
    performed_by = models.ForeignKey('auth_app.User', on_delete=models.PROTECT)
    reason = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)


def validate_submission(brand):
    missing = []
    for field, label in (
        ('brand_name', 'pharmacy name'), ('owner_id', 'owner'),
        ('address_line_1', 'address'), ('state', 'state'),
        ('cac_registration_number', 'CAC registration number'),
        ('pcn_premises_registration_number', 'PCN premises registration information'),
    ):
        if not getattr(brand, field, None):
            missing.append(label)
    if brand.latitude is None or brand.longitude is None:
        missing.append('latitude and longitude')
    if brand.images.filter(image_type='EXTERIOR').count() < 2:
        missing.append('at least 2 exterior images')
    if brand.images.filter(image_type='INTERIOR').count() < 2:
        missing.append('at least 2 interior images')
    if missing:
        raise ValueError('Missing required information: ' + ', '.join(missing))


class PharmacyBrandImage(models.Model):
    """Photographs and supporting media for a pharmacy brand."""

    IMAGE_TYPE_CHOICES = (
        ('EXTERIOR', 'Exterior'),
        ('FRONT_VIEW', 'Front View'),
        ('INTERIOR', 'Interior'),
        ('PHARMACY_SIGN', 'Pharmacy Sign'),
        ('COUNTER', 'Counter'),
        ('DOCUMENT', 'Document'),
        ('OTHER', 'Other'),
    )

    brand = models.ForeignKey(
        PharmacyBrand,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(upload_to='pharmacy/brands/%Y/%m/%d/', blank=True, default='')
    image_type = models.CharField(max_length=30, choices=IMAGE_TYPE_CHOICES, default='FRONT_VIEW')
    caption = models.CharField(max_length=255, blank=True, default='')
    is_primary = models.BooleanField(default=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pharmacy_brand_image'
        ordering = ['-is_primary', '-uploaded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['brand', 'image_type'],
                condition=Q(is_primary=True),
                name='unique_primary_brand_image_per_type',
            )
        ]

    def __str__(self):
        return f'{self.brand.brand_name} - {self.image_type}'

