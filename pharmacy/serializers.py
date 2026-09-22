from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.db.models.functions import Lower, Trim
from django.contrib.gis.geos import Point
from rest_framework import serializers
from .models import PharmacyBrand, PharmacyBrandImage, PharmacyMembership, PharmacyVerificationDocument

User = get_user_model()


class GeoJSONPointField(serializers.Field):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or data.get('type') != 'Point':
            raise serializers.ValidationError('Location must be a GeoJSON Point.')
        coordinates = data.get('coordinates')
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
            raise serializers.ValidationError('Location coordinates must contain longitude and latitude.')
        try:
            longitude, latitude = (float(value) for value in coordinates)
        except (TypeError, ValueError):
            raise serializers.ValidationError('Location coordinates must be numeric.')
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise serializers.ValidationError('Location coordinates are out of range.')
        return Point(longitude, latitude, srid=4326)

    def to_representation(self, value):
        if value is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [float(value.x), float(value.y)],
        }


class PharmacyBrandListSerializer(serializers.ModelSerializer):
    location = GeoJSONPointField(read_only=True)

    class Meta:
        model = PharmacyBrand
        fields = ('id', 'brand_name', 'legal_name', 'city', 'state', 'country', 'location', 'pharmacy_type')
        read_only_fields = fields


class PharmacyJoinPreviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyBrand
        fields = ('brand_name', 'city', 'state', 'country', 'pharmacy_type')
        read_only_fields = fields


class PharmacyBrandDetailSerializer(serializers.ModelSerializer):
    owner = serializers.SerializerMethodField()
    location = GeoJSONPointField(read_only=True)

    class Meta:
        model = PharmacyBrand
        fields = (
            'id', 'pharmacy_id', 'owner', 'brand_name', 'legal_name', 'description',
            'business_email', 'business_phone', 'address_line_1', 'address_line_2',
            'city', 'state', 'lga', 'postal_code', 'country', 'opnetime', 'closetime',
            'pharmacy_type', 'years_in_operation', 'cac_registration_number', 'pcn_premises_registration_number',
            'pcn_license_number', 'pcn_issue_date', 'pcn_expiry_date',
            'nafdac_registration_number', 'nafdac_certificate_number', 'nafdac_expiry_date',
            'verification_status', 'verified_by', 'verified_at', 'review_started_by',
            'review_started_at', 'rejected_by', 'rejected_at', 'suspended_by', 'suspended_at',
            'suspension_reason', 'created_at', 'updated_at', 'location'
        )
        read_only_fields = fields

    def get_owner(self, obj):
        return {'id': str(obj.owner.id), 'email': obj.owner.email, 'first_name': obj.owner.first_name, 'last_name': obj.owner.last_name}


class PharmacyBrandCreateSerializer(serializers.ModelSerializer):
    brand_name = serializers.CharField(trim_whitespace=True)
    location = GeoJSONPointField(required=False, allow_null=True)

    class Meta:
        model = PharmacyBrand
        fields = ('legal_name', 'brand_name', 'description', 'business_email', 'business_phone', 'address_line_1', 'address_line_2', 'city', 'state', 'lga', 'postal_code', 'country', 'opnetime', 'closetime', 'pharmacy_type', 'years_in_operation', 'cac_registration_number', 'pcn_premises_registration_number', 'pcn_license_number', 'pcn_issue_date', 'pcn_expiry_date', 'nafdac_registration_number', 'nafdac_certificate_number', 'nafdac_expiry_date', 'location')

    def validate_brand_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Brand name is required.')
        if PharmacyBrand.objects.annotate(_normalized=Lower(Trim('brand_name'))).filter(_normalized=value.lower()).exists():
            raise serializers.ValidationError('A pharmacy with this brand name already exists.')
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        if user.role != 'PHARMACY_OWNER':
            raise serializers.ValidationError('Only a user with role PHARMACY_OWNER can create a PharmacyBrand')
        if not user.is_active or not user.is_verified:
            raise serializers.ValidationError('Owner must be active and verified')
        return attrs

    def create(self, validated_data):
        request = self.context['request']
        from .services import create_pharmacy_brand
        try:
            return create_pharmacy_brand(request.user, **validated_data)
        except ValueError as exc:
            raise serializers.ValidationError({'detail': str(exc)}) from exc
        except IntegrityError as exc:
            if 'unique_pharmacy_brand_name_ci' in str(exc):
                raise serializers.ValidationError({'brand_name': 'A pharmacy with this brand name already exists.'}) from exc
            raise


class PharmacyBrandUpdateSerializer(serializers.ModelSerializer):
    location = GeoJSONPointField(required=False, allow_null=True)

    class Meta:
        model = PharmacyBrand
        fields = ('legal_name', 'brand_name', 'description', 'business_email', 'business_phone', 'address_line_1', 'address_line_2', 'city', 'state', 'lga', 'postal_code', 'country', 'opnetime', 'closetime', 'pharmacy_type', 'years_in_operation', 'location')

    def validate(self, attrs):
        # If brand already verified and sensitive fields change, caller must trigger re-verification.
        return super().validate(attrs)


class PharmacyBrandImageSerializer(serializers.ModelSerializer):
    brand = serializers.PrimaryKeyRelatedField(queryset=PharmacyBrand.objects.all())

    class Meta:
        model = PharmacyBrandImage
        fields = ('id', 'brand', 'image', 'image_type', 'caption', 'is_primary', 'uploaded_at')
        read_only_fields = ('id', 'uploaded_at')

    def validate_brand(self, brand):
        request = self.context['request']
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN') and brand.owner_id != request.user.id:
            raise serializers.ValidationError('You can only upload images for your own pharmacy')
        if brand.verification_status not in ('DRAFT', 'REJECTED'):
            raise serializers.ValidationError('Images can only be uploaded for draft or rejected pharmacies')
        return brand


class PharmacyVerificationDocumentSerializer(serializers.ModelSerializer):
    brand = serializers.PrimaryKeyRelatedField(queryset=PharmacyBrand.objects.all())

    class Meta:
        model = PharmacyVerificationDocument
        fields = ('id', 'brand', 'document', 'document_type', 'review_status', 'uploaded_at')
        read_only_fields = ('id', 'review_status', 'uploaded_at')

    def validate_brand(self, brand):
        request = self.context['request']
        if request.user.role not in ('SUPER_ADMIN', 'PLATFORM_ADMIN') and brand.owner_id != request.user.id:
            raise serializers.ValidationError('You can only upload documents for your own pharmacy')
        if brand.verification_status not in ('DRAFT', 'REJECTED'):
            raise serializers.ValidationError('Documents can only be uploaded for draft or rejected pharmacies')
        return brand


class PharmacyMembershipSerializer(serializers.ModelSerializer):
    user = serializers.PrimaryKeyRelatedField(read_only=True, default=serializers.CurrentUserDefault())
    user_details = serializers.SerializerMethodField()
    pharmacy = serializers.PrimaryKeyRelatedField(queryset=PharmacyBrand.objects.all())

    class Meta:
        model = PharmacyMembership
        fields = ('id', 'user', 'user_details', 'pharmacy', 'role', 'status', 'approved_by', 'approved_at', 'rejection_reason', 'created_at', 'updated_at')
        read_only_fields = ('id', 'status', 'approved_by', 'approved_at', 'rejection_reason', 'created_at', 'updated_at')

    def get_user_details(self, obj):
        return {
            'id': str(obj.user.id),
            'email': obj.user.email,
            'first_name': obj.user.first_name,
            'last_name': obj.user.last_name,
        }

    def validate_role(self, value):
        if value not in dict(PharmacyMembership.ROLE_CHOICES):
            raise serializers.ValidationError('Invalid role for membership')
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
            raise serializers.ValidationError('Platform admins cannot be pharmacy employees')
        # Ensure pharmacy is approved/verified
        pharmacy = attrs.get('pharmacy')
        if pharmacy and not pharmacy.is_verified:
            raise serializers.ValidationError('Cannot request membership for unverified pharmacy')
        return attrs

    def create(self, validated_data):
        user = self.context['request'].user
        pharmacy = validated_data['pharmacy']
        role = validated_data['role']
        # Prevent duplicates
        existing = PharmacyMembership.objects.filter(user=user, pharmacy=pharmacy).first()
        if existing:
            raise serializers.ValidationError('Membership already exists for this user and pharmacy')
        membership = PharmacyMembership.objects.create(user=user, pharmacy=pharmacy, role=role)
        return membership


class PharmacyMembershipRequestSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = PharmacyMembership
        fields = ('id', 'user', 'role', 'status', 'rejection_reason', 'created_at')
        read_only_fields = fields

    def get_user(self, obj):
        return {'id': str(obj.user.id), 'email': obj.user.email, 'first_name': obj.user.first_name, 'last_name': obj.user.last_name}


class PharmacyMembershipApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = PharmacyMembership
        fields = ('id', 'status')
        read_only_fields = ('id',)

    def validate_status(self, value):
        if value not in dict(PharmacyMembership.STATUS_CHOICES):
            raise serializers.ValidationError('Invalid membership status')
        return value
