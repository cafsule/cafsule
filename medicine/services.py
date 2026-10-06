"""Domain services for the global medicine catalog."""

import hashlib
import json
import re
import csv
from collections import Counter
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import Medicine


ADMIN_ROLES = {'SUPER_ADMIN', 'PLATFORM_ADMIN'}
PHARMACY_ROLES = {'PHARMACY_OWNER', 'PHARMACY_MANAGER'}

GREENBOOK_FIELD_ALIASES = {
    'product_name': ('product_name', 'Product Name', 'name'),
    'active_ingredients': (
        'active_ingredients', 'Active Ingredients', 'generic_name', 'ingredient_name',
        'ingredient', 'ingredients',
    ),
    'nrn': (
        'nrn', 'NRN', 'nafdac_registration', 'NAFDAC Registration Number',
        'registration_number', 'NAFDAC',
    ),
    'form': ('form', 'Form', 'dosage_form', 'form_name'),
    'route': (
        'route', 'ROA', 'Route of Administration', 'route_of_administration',
        'route_name',
    ),
    'strengths': ('strengths', 'Strengths', 'strength'),
    'applicant_name': ('applicant_name', 'Applicant Name', 'manufacturer'),
}

GREENBOOK_FORM_MAP = {
    'tablet': 'TABLET', 'caplet': 'TABLET', 'dispersible tablet': 'TABLET',
    'film coated tablet': 'TABLET', 'prolonged-release tablet': 'TABLET',
    'vaginal tablet': 'TABLET', 'chewable tablet': 'TABLET', 'capsule': 'CAPSULE',
    'syrup': 'SYRUP', 'suspension': 'SUSPENSION', 'powder for suspension': 'POWDER',
    'powder': 'POWDER', 'cream': 'CREAM', 'ointment': 'OINTMENT',
    'eye ointment': 'OINTMENT', 'lotion': 'LOTION', 'solution': 'SOLUTION',
    'solution/drops': 'SOLUTION', 'suspension/drops': 'SUSPENSION', 'drops': 'SOLUTION',
    'eye drops': 'SOLUTION', 'liquid': 'SOLUTION', 'solution for injection': 'INJECTION',
    'injection': 'INJECTION', 'powder for injection': 'POWDER',
    'powder for solution for injection/infusion': 'POWDER',
    'emulsion for injection/infusion': 'INJECTION', 'suspension for injection': 'INJECTION',
    'solution for infusion': 'SOLUTION', 'powder for solution': 'POWDER',
    'gel': 'OTHER', 'granules': 'POWDER', 'spray': 'OTHER',
    'aerosol, metered-dose': 'OTHER', 'kit': 'OTHER', 'suppository': 'OTHER',
    'lozenge': 'OTHER', 'inhalation vapour': 'OTHER',
}

GREENBOOK_ROUTE_MAP = {
    'oral': 'ORAL', 'topical': 'TOPICAL', 'cutaneous/topical': 'TOPICAL',
    'intravenous': 'INTRAVENOUS', 'intramuscular': 'INTRAMUSCULAR',
    'rectal': 'RECTAL', 'inhalation': 'INHALED', 'nasal': 'INTRANASAL',
}


@dataclass
class GreenbookImportResult:
    rows_read: int = 0
    created: int = 0
    updated: int = 0
    matched: int = 0
    skipped: int = 0
    errors: int = 0
    conflicts: int = 0
    valid_rows: int = 0
    messages: list = field(default_factory=list)
    validation_summary: dict = field(default_factory=dict)

    def as_dict(self):
        return {
            'rows_read': self.rows_read,
            'created': self.created,
            'updated': self.updated,
            'matched': self.matched,
            'skipped': self.skipped,
            'errors': self.errors,
            'conflicts': self.conflicts,
            'valid_rows': self.valid_rows,
            'messages': self.messages,
            'validation_summary': self.validation_summary,
        }


class GreenbookImportService:
    """Compatibility facade for callers that import Greenbook files in code."""

    def import_records(self, records, *, dry_run=False):
        return import_greenbook_records(records, dry_run=dry_run)

    def import_file(self, path, *, dry_run=False):
        source_path = str(path)
        with open(source_path, 'r', encoding='utf-8-sig', newline='') as source:
            if source_path.lower().endswith('.json'):
                records = json.load(source)
                if isinstance(records, dict):
                    records = records.get('records')
                if not isinstance(records, list):
                    raise ValueError('JSON input must be a list or an object with a records list.')
            else:
                records = list(csv.DictReader(source))
        return self.import_records(records, dry_run=dry_run)


def _collapse_whitespace(value):
    return ' '.join((value or '').split())


def _normalize_strength(value):
    strength = _collapse_whitespace(value)
    strength = re.sub(r'(?<=\d)\s+(?=[A-Za-z%]|\u00b5|\u03bc)', '', strength)
    strength = re.sub(r'\s*/\s*', '/', strength)
    return strength


def normalize_medicine_fields(fields):
    """Normalize identity fields without removing meaningful distinctions."""
    normalized = dict(fields)
    for field in ('generic_name', 'brand_name', 'manufacturer'):
        if field in normalized:
            normalized[field] = _collapse_whitespace(normalized[field])
    if 'strength' in normalized:
        normalized['strength'] = _normalize_strength(normalized['strength'])
    if normalized.get('dosage_form'):
        normalized['dosage_form'] = normalized['dosage_form'].strip().upper()
    normalized['route'] = (normalized.get('route') or 'ORAL').strip().upper()
    normalized['pack_size'] = int(normalized.get('pack_size') or 1)
    normalized['pack_size_unit'] = (normalized.get('pack_size_unit') or 'UNIT').strip().upper()
    return normalized


def medicine_identity_key(fields):
    """Return a deterministic key for a complete product identity."""
    normalized = normalize_medicine_fields(fields)
    identity = (
        normalized.get('generic_name', '').casefold(),
        normalized.get('brand_name', '').casefold(),
        normalized.get('strength', '').casefold(),
        (normalized.get('dosage_form') or '').casefold(),
        normalized.get('route', 'ORAL').casefold(),
        normalized.get('manufacturer', '').casefold(),
        normalized.get('pack_size', 1),
        normalized.get('pack_size_unit', 'UNIT').casefold(),
    )
    encoded = json.dumps(identity, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _validate_provenance(source, created_by, created_by_pharmacy):
    if source not in dict(Medicine.SOURCE_CHOICES):
        raise ValidationError({'source': 'A valid catalog source is required.'})
    if source == 'ADMIN' and (created_by is None or created_by.role not in ADMIN_ROLES):
        raise ValidationError({'source': 'Admin catalog records require a platform administrator.'})
    if source == 'PHARMACY':
        if created_by is None or created_by.role not in PHARMACY_ROLES:
            raise ValidationError({'created_by': 'Pharmacy catalog records require a pharmacy owner or manager.'})
        if created_by_pharmacy is None:
            raise ValidationError({'created_by_pharmacy': 'Pharmacy provenance is required.'})
    if source == 'PUBLIC_DATABASE' and created_by_pharmacy is not None:
        raise ValidationError({'created_by_pharmacy': 'Public database records cannot have creator-pharmacy provenance.'})


def _first_value(record, field):
    for alias in GREENBOOK_FIELD_ALIASES[field]:
        if alias in record and record[alias] not in (None, ''):
            return _coerce_greenbook_value(field, record[alias])
    return ''


def _coerce_greenbook_value(field, value):
    if isinstance(value, list):
        values = [_coerce_greenbook_value(field, item) for item in value]
        return '; '.join(str(item).strip() for item in values if str(item).strip())
    if not isinstance(value, dict):
        return value
    nested_aliases = {
        'active_ingredients': ('name', 'ingredient_name', 'active_ingredient', 'active_ingredients'),
        'form': ('name', 'form_name'),
        'route': ('name', 'route_name'),
    }
    for alias in nested_aliases.get(field, ()):
        if alias in value and value[alias] not in (None, ''):
            return _coerce_greenbook_value(field, value[alias])
    return ''


def normalize_greenbook_record(record, row_number=None):
    """Map a raw Greenbook row to fields supported by Medicine."""
    product_name = str(_first_value(record, 'product_name')).strip()
    active_ingredients = str(_first_value(record, 'active_ingredients')).strip()
    strength = str(_first_value(record, 'strengths')).strip()
    raw_form = str(_first_value(record, 'form')).strip()
    dosage_form = GREENBOOK_FORM_MAP.get(raw_form.casefold())
    source_product_id = str(record.get('source_id') or record.get('product_id') or '').strip()

    missing = [
        name for name, value in (
            ('product_name', product_name),
            ('active_ingredients', active_ingredients),
            ('strengths', strength),
            ('form', dosage_form),
        ) if not value
    ]
    if (record.get('source') == 'greenbook' or 'source_id' in record) and not source_product_id:
        missing.append('source_id')
    if missing:
        raise ValidationError(
            f"Row {row_number or '?'} is missing required fields: {', '.join(missing)}"
        )
    if dosage_form is None:
        raise ValidationError(f"Row {row_number or '?'} has unsupported form: {raw_form}")

    raw_route = str(_first_value(record, 'route')).strip()
    route = GREENBOOK_ROUTE_MAP.get(raw_route.casefold(), 'OTHER')
    description_parts = [
        str(record.get('description') or record.get('product_description') or '').strip()
    ]
    composition = str(record.get('composition') or '').strip()
    if composition:
        description_parts.append(f'Composition: {composition}')
    if raw_form and raw_form.casefold() not in GREENBOOK_FORM_MAP:
        description_parts.append(f'Greenbook dosage form: {raw_form}')
    if raw_route and raw_route.casefold() not in GREENBOOK_ROUTE_MAP:
        description_parts.append(f'Greenbook route: {raw_route}')

    return {
        'generic_name': _collapse_whitespace(active_ingredients),
        'brand_name': _collapse_whitespace(product_name),
        'strength': _normalize_strength(strength),
        'dosage_form': dosage_form,
        'route': route,
        'manufacturer': _collapse_whitespace(str(_first_value(record, 'applicant_name')).strip()),
        'pack_size': 1,
        'pack_size_unit': 'UNIT',
        'nafdac_registration': str(_first_value(record, 'nrn')).strip(),
        'description': '\n'.join(part for part in description_parts if part),
        'source_product_id': source_product_id,
    }


def _apply_greenbook_enrichment(medicine, normalized):
    """Only add non-conflicting regulatory data; never replace provenance."""
    imported_nrn = normalized.get('nafdac_registration', '')
    if not imported_nrn:
        return False, None
    if medicine.nafdac_registration and medicine.nafdac_registration != imported_nrn:
        return False, 'Existing NAFDAC registration differs from imported NRN.'
    if medicine.nafdac_registration:
        return False, None
    medicine.nafdac_registration = imported_nrn
    medicine.save(update_fields=['nafdac_registration', 'updated_at'])
    return True, None


def _greenbook_validation_message(error):
    message = error.messages[0] if getattr(error, 'messages', None) else str(error)
    return re.sub(r'^Row \d+ is ', 'is ', message)


def _apply_greenbook_update(medicine, normalized):
    changed_fields = _greenbook_changed_fields(medicine, normalized)
    if not changed_fields:
        return False
    for field in changed_fields:
        setattr(medicine, field, normalized[field])
    medicine.save()
    return True


def _greenbook_changed_fields(medicine, normalized):
    return [
        field for field, value in normalized.items()
        if getattr(medicine, field) != value
    ]


def import_greenbook_records(records, *, dry_run=False):
    """Import normalized Greenbook rows without replacing user provenance."""
    result = GreenbookImportResult()
    normalized_records = []
    validation_summary = Counter()
    representative_messages = {}

    for row_number, record in enumerate(records, start=1):
        result.rows_read += 1
        try:
            normalized = normalize_greenbook_record(record, row_number=row_number)
            normalized_records.append((row_number, normalized, medicine_identity_key(normalized)))
        except ValidationError as error:
            result.errors += 1
            reason = _greenbook_validation_message(error)
            validation_summary[reason] += 1
            representative_messages.setdefault(reason, f'Row {row_number}: {error}')
        except (TypeError, ValueError, KeyError) as error:
            result.errors += 1
            reason = str(error)
            validation_summary[reason] += 1
            representative_messages.setdefault(reason, f'Row {row_number}: {error}')

    result.valid_rows = len(normalized_records)
    seen_source_ids = set()
    unique_records = []
    for row_number, normalized, identity_key in normalized_records:
        source_product_id = normalized['source_product_id']
        if source_product_id and source_product_id in seen_source_ids:
            result.conflicts += 1
            reason = 'duplicate source product ID'
            validation_summary[reason] += 1
            representative_messages.setdefault(
                reason, f'Row {row_number}: duplicate source product ID {source_product_id}.'
            )
            continue
        if source_product_id:
            seen_source_ids.add(source_product_id)
        unique_records.append((row_number, normalized, identity_key))
    normalized_records = unique_records

    identity_keys = {identity_key for _, _, identity_key in normalized_records}
    source_product_ids = {
        normalized['source_product_id']
        for _, normalized, _ in normalized_records
        if normalized['source_product_id']
    }
    identity_cache = {
        medicine.identity_key: medicine
        for medicine in Medicine.objects.filter(identity_key__in=identity_keys).only(
            'id', 'identity_key', 'source', 'nafdac_registration', 'source_product_id',
        )
    }
    source_id_cache = {
        medicine.source_product_id: medicine
        for medicine in Medicine.objects.filter(
            source='PUBLIC_DATABASE', source_product_id__in=source_product_ids
        )
    }

    for row_number, normalized, identity_key in normalized_records:
        existing = source_id_cache.get(normalized['source_product_id']) or identity_cache.get(identity_key)
        if existing is None:
            existing = Medicine.objects.filter(
                generic_name=normalized['generic_name'],
                brand_name=normalized['brand_name'],
                strength=normalized['strength'],
                dosage_form=normalized['dosage_form'],
                route=normalized['route'],
                pack_size=normalized['pack_size'],
                pack_size_unit=normalized['pack_size_unit'],
            ).first()
        try:
            if existing is not None:
                if existing.source == 'PUBLIC_DATABASE' and normalized['source_product_id']:
                    if (
                        existing.source_product_id
                        and existing.source_product_id != normalized['source_product_id']
                    ):
                        result.conflicts += 1
                        reason = 'Source product ID conflicts with an existing medicine identity.'
                        validation_summary[reason] += 1
                        representative_messages.setdefault(
                            reason,
                            f'Row {row_number}: {reason}',
                        )
                    elif dry_run:
                        if _greenbook_changed_fields(existing, normalized):
                            result.updated += 1
                        else:
                            result.matched += 1
                    elif _apply_greenbook_update(existing, normalized):
                        result.updated += 1
                    else:
                        result.matched += 1
                elif normalized['nafdac_registration'] and not existing.nafdac_registration:
                    result.matched += 1
                    result.updated += 1
                    if not dry_run:
                        with transaction.atomic():
                            _apply_greenbook_enrichment(existing, normalized)
                elif (
                    normalized['nafdac_registration']
                    and existing.nafdac_registration
                    and existing.nafdac_registration != normalized['nafdac_registration']
                ):
                    result.conflicts += 1
                    reason = 'Existing NAFDAC registration differs from imported NRN.'
                    validation_summary[reason] += 1
                    representative_messages.setdefault(reason, f'Row {row_number}: {reason}')
                else:
                    result.matched += 1
                continue

            if dry_run:
                identity_cache[identity_key] = Medicine(
                    **normalized,
                    identity_key=identity_key,
                    source='PUBLIC_DATABASE',
                )
                result.created += 1
                continue

            with transaction.atomic():
                medicine, created = create_or_get_global_medicine(
                    fields=normalized,
                    source='PUBLIC_DATABASE',
                )
            identity_cache[identity_key] = medicine
            if normalized['source_product_id']:
                source_id_cache[normalized['source_product_id']] = medicine
            if created:
                result.created += 1
            else:
                result.matched += 1
        except (IntegrityError, TypeError, ValueError, KeyError) as error:
            result.errors += 1
            reason = str(error)
            validation_summary[reason] += 1
            representative_messages.setdefault(reason, f'Row {row_number}: {error}')

    result.skipped = result.errors + result.conflicts
    result.validation_summary = dict(validation_summary)
    result.messages = list(representative_messages.values())
    return result


@transaction.atomic
def create_or_get_global_medicine(*, fields, source, created_by=None, created_by_pharmacy=None):
    """Validate provenance and create or reuse the canonical global medicine."""
    _validate_provenance(source, created_by, created_by_pharmacy)
    normalized = normalize_medicine_fields(fields)
    identity_key = medicine_identity_key(normalized)
    medicine = Medicine(
        **normalized,
        identity_key=identity_key,
        source=source,
        created_by=created_by,
        created_by_pharmacy=created_by_pharmacy,
    )
    medicine.full_clean(validate_unique=False, validate_constraints=False)

    existing = Medicine.objects.filter(identity_key=identity_key).first()
    if existing is not None:
        return existing, False

    try:
        with transaction.atomic():
            medicine.save(force_insert=True)
    except IntegrityError:
        existing = Medicine.objects.filter(identity_key=identity_key).first()
        if existing is None:
            raise
        return existing, False

    return medicine, True