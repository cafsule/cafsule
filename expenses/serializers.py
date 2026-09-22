from decimal import Decimal

from rest_framework import serializers

from .models import Expense


class ExpenseSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = (
            'id', 'pharmacy', 'category', 'amount', 'expense_date', 'description',
            'reference', 'payment_method', 'notes', 'status', 'created_by',
            'created_by_name', 'approved_by', 'approved_by_name', 'approved_at',
            'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'pharmacy', 'created_by', 'approved_by', 'approved_at', 'created_at', 'updated_at')

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else None

    def get_approved_by_name(self, obj):
        return obj.approved_by.get_full_name() if obj.approved_by else None

    def validate_amount(self, value):
        if value <= Decimal('0.00'):
            raise serializers.ValidationError('Expense amount must be greater than zero.')
        return value

    def validate_expense_date(self, value):
        if value is None:
            raise serializers.ValidationError('Expense date is required.')
        return value
