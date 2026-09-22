from django.core.exceptions import ValidationError


def validate_latitude(value):
    try:
        v = float(value)
    except Exception:
        raise ValidationError('Invalid latitude')
    if v < -90 or v > 90:
        raise ValidationError('Latitude must be between -90 and 90')


def validate_longitude(value):
    try:
        v = float(value)
    except Exception:
        raise ValidationError('Invalid longitude')
    if v < -180 or v > 180:
        raise ValidationError('Longitude must be between -180 and 180')


def validate_radius_km(value):
    try:
        v = float(value)
    except Exception:
        raise ValidationError('Invalid radius')
    if v <= 0 or v > 500:
        raise ValidationError('Radius must be between 0 and 500 km')
