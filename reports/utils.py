from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.utils import timezone

BUSINESS_TIMEZONE = ZoneInfo('Africa/Lagos')


def get_business_now():
    return timezone.now().astimezone(BUSINESS_TIMEZONE)


def get_default_report_window(request):
    """Returns a business-day window for the current Nigeria date."""
    now = get_business_now()
    start = datetime.combine(now.date(), time.min, tzinfo=BUSINESS_TIMEZONE)
    end = datetime.combine(now.date(), time.max, tzinfo=BUSINESS_TIMEZONE)

    if request.query_params.get('date_from') or request.query_params.get('date_to'):
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        if date_from:
            start = datetime.combine(datetime.fromisoformat(date_from).date(), time.min, tzinfo=BUSINESS_TIMEZONE)
        if date_to:
            end = datetime.combine(datetime.fromisoformat(date_to).date(), time.max, tzinfo=BUSINESS_TIMEZONE)

    return start, end


def resolve_user_pharmacy(request):
    user = request.user

    if user.role in ('SUPER_ADMIN', 'PLATFORM_ADMIN'):
        return None

    if user.role == 'PHARMACY_OWNER':
        try:
            return user.owned_pharmacy_brand
        except Exception:
            return None

    membership = user.pharmacy_memberships.filter(status='APPROVED').select_related('pharmacy').first()
    if membership:
        return membership.pharmacy
    return None
