from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Expense
from .serializers import ExpenseSerializer
from auth.permissions import IsAuthenticatedAndActive, IsPharmacyOwner, IsPharmacyStaff
from pharmacy.models import PharmacyBrand, PharmacyMembership


def can_approve_expense(user):
    if not getattr(user, 'is_authenticated', False):
        return False
    return user.role == 'PHARMACY_OWNER' or user.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}


PHARMACY_EXPENSE_CREATOR_ROLES = {
    'PHARMACY_OWNER', 'PHARMACY_MANAGER', 'PHARMACIST', 'PHARMACY_STAFF',
}


def resolve_expense_pharmacy(user, requested_pharmacy=None):
    """Resolve the pharmacy the authenticated user is authorized to use."""
    if user.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}:
        if not requested_pharmacy:
            raise serializers.ValidationError('A pharmacy is required for platform expense creation.')
        return get_object_or_404(PharmacyBrand, pk=requested_pharmacy)

    if user.role == 'PHARMACY_OWNER':
        pharmacy = getattr(user, 'owned_pharmacy_brand', None)
        if pharmacy is None:
            raise serializers.ValidationError('You do not own a pharmacy.')
        return pharmacy

    if user.role not in PHARMACY_EXPENSE_CREATOR_ROLES:
        raise serializers.ValidationError('You are not authorized to create expenses.')

    membership = PharmacyMembership.objects.filter(
        user=user,
        status='APPROVED',
    ).select_related('pharmacy').first()
    if membership is None:
        raise serializers.ValidationError('You are not approved for a pharmacy.')
    return membership.pharmacy


class ExpenseViewSet(viewsets.ModelViewSet):
    permission_classes = (permissions.IsAuthenticated, IsAuthenticatedAndActive)
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        user = self.request.user
        if user.role in {'SUPER_ADMIN', 'PLATFORM_ADMIN'}:
            return Expense.objects.select_related('pharmacy', 'created_by', 'approved_by')
        if user.role == 'PHARMACY_OWNER':
            pharmacy = getattr(user, 'owned_pharmacy_brand', None)
            if not pharmacy:
                return Expense.objects.none()
            return Expense.objects.filter(pharmacy=pharmacy).select_related('pharmacy', 'created_by', 'approved_by')
        memberships = PharmacyMembership.objects.filter(user=user, status='APPROVED').values_list('pharmacy_id', flat=True)
        return Expense.objects.filter(pharmacy_id__in=memberships).select_related('pharmacy', 'created_by', 'approved_by')

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def perform_create(self, serializer):
        user = self.request.user
        requested_pharmacy = self.request.data.get('pharmacy') or self.request.data.get('pharmacy_id')
        pharmacy = resolve_expense_pharmacy(user, requested_pharmacy)
        if user.role not in {'SUPER_ADMIN', 'PLATFORM_ADMIN'} and requested_pharmacy and str(pharmacy.pk) != str(requested_pharmacy):
            raise serializers.ValidationError('You cannot create an expense for a different pharmacy.')
        serializer.save(pharmacy=pharmacy, created_by=user)

    @transaction.atomic
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        expense = get_object_or_404(Expense.objects.select_for_update(), pk=pk)
        if not self.get_queryset().filter(pk=expense.pk).exists():
            return Response({'detail': 'Expense not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_approve_expense(request.user):
            return Response({'detail': 'Only the pharmacy owner can approve expenses.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            expense.approve(request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense).data)

    @transaction.atomic
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        expense = get_object_or_404(Expense.objects.select_for_update(), pk=pk)
        if not self.get_queryset().filter(pk=expense.pk).exists():
            return Response({'detail': 'Expense not found.'}, status=status.HTTP_404_NOT_FOUND)
        if not can_approve_expense(request.user):
            return Response({'detail': 'Only the pharmacy owner can reject expenses.'}, status=status.HTTP_403_FORBIDDEN)
        reason = request.data.get('reason', '')
        try:
            expense.reject(request.user, reason)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ExpenseSerializer(expense).data)
