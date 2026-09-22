import django_filters
from .models import PharmacyBrand, PharmacyMembership


class PharmacyBrandFilter(django_filters.FilterSet):
    state = django_filters.CharFilter(field_name='state', lookup_expr='iexact')
    brand = django_filters.CharFilter(field_name='brand_name', lookup_expr='icontains')
    verification_status = django_filters.CharFilter(field_name='verification_status', lookup_expr='iexact')

    class Meta:
        model = PharmacyBrand
        fields = ['state', 'verification_status', 'brand']


class PharmacyMembershipFilter(django_filters.FilterSet):
    role = django_filters.CharFilter(field_name='role', lookup_expr='iexact')
    status = django_filters.CharFilter(field_name='status', lookup_expr='iexact')

    class Meta:
        model = PharmacyMembership
        fields = ['role', 'status', 'pharmacy']
