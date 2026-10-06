import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase

from .models import Medicine
from .services import import_greenbook_records, normalize_greenbook_record


GREENBOOK_RECORD = {
    'product_name': 'Synthetic Product',
    'active_ingredients': 'Synthetic Ingredient',
    'form': 'TABLET',
    'route': 'ORAL',
    'strengths': '500 mg',
    'applicant_name': 'Synthetic Applicant',
    'nrn': 'TEST-NRN-001',
}

LONG_GREENBOOK_RECORD = {
    'product_id': 10785,
    'product_name': 'Mestymin Syrup 200 mL_',
    'ingredient_name': (
        'L-Leucine; L-Isoleucine; L-Lysine Hydrochloride; L-Methionine; '
        'L-Phenylalanine; L-Threonine; L-Tryptophan; L-Valine; Vitamin A; '
        'Cholecalciferol; Alpha Tocopheryl Acetate; Thiamine Hydrochloride; '
        'Riboflavin; Nicotinamide; Calcium Pantothenate; Pyridoxine Hydrochloride; '
        'Cyanocobalamin; Ascorbic Acid; Folic Acid'
    ),
    'form_name': 'Syrup',
    'route_name': 'Oral',
    'strength': (
        '18.3 mg; 5.9 mg; 25 mg; 5 mg; 4.2 mg; 6.7 mg; 5 mg;18.4 mg; '
        '2500iu; 200iu; 5 mg; 3 mg;  25 mg;  1.5 mg;  0.75 mg;  5 mg, '
        '2.5 mg; 40 mg; 7.5iu'
    ),
    'applicant_name': 'MUCHIS HEALTHCARE LIMITED',
    'NAFDAC': 'A11-100661',
}


class GreenbookImportTests(TestCase):
    def test_real_greenbook_fields_are_normalized(self):
        normalized = normalize_greenbook_record({
            'source_id': '8875',
            'name': '10% Dextrose',
            'generic_name': 'Glucose',
            'dosage_form': 'Solution for infusion',
            'route_of_administration': 'Intravenous',
            'strength': '10%',
            'applicant_name': 'Dana Pharmaceuticals Limited',
            'registration_number': '04-0858',
            'composition': 'Dextrose Monohydrate BP 10 g w/v',
        })

        self.assertEqual(normalized['brand_name'], '10% Dextrose')
        self.assertEqual(normalized['generic_name'], 'Glucose')
        self.assertEqual(normalized['dosage_form'], 'SOLUTION')
        self.assertEqual(normalized['route'], 'INTRAVENOUS')
        self.assertEqual(normalized['source_product_id'], '8875')
        self.assertIn('Composition:', normalized['description'])

    def test_multiple_active_ingredients_are_preserved(self):
        normalized = normalize_greenbook_record({
            'applicant_name': 'Applicant',
            'generic_name': 'Glucose; Sodium Chloride',
            'name': 'Combination infusion',
            'source_id': 'combo-1',
            'dosage_form': 'Solution for infusion',
            'route_of_administration': 'Intravenous; Intramuscular',
            'strength': '5%; 0.9%',
        })

        self.assertEqual(normalized['generic_name'], 'Glucose; Sodium Chloride')
        self.assertEqual(normalized['strength'], '5%; 0.9%')
        self.assertEqual(normalized['route'], 'OTHER')

    def test_batch_schema_maps_flattened_ingredient_and_form_fields(self):
        normalized = normalize_greenbook_record({
            'product_id': 8875,
            'product_name': '10% Dextrose',
            'ingredient_name': 'Glucose',
            'form_name': 'Solution for infusion',
            'route_name': 'Intravenous',
            'strength': '10%',
            'NAFDAC': '04-0858',
        })

        self.assertEqual(normalized['generic_name'], 'Glucose')
        self.assertEqual(normalized['dosage_form'], 'SOLUTION')
        self.assertEqual(normalized['source_product_id'], '8875')
        self.assertEqual(normalized['nafdac_registration'], '04-0858')

    def test_nested_ingredients_and_form_are_coerced_to_scalars(self):
        normalized = normalize_greenbook_record({
            'source_id': 'nested-1',
            'name': 'Combination tablet',
            'ingredient': [
                {'ingredient_name': 'Paracetamol'},
                {'name': 'Caffeine'},
            ],
            'form': {'name': 'Tablet'},
            'route': {'name': 'Oral'},
            'strength': '500 mg; 30 mg',
        })

        self.assertEqual(normalized['generic_name'], 'Paracetamol; Caffeine')
        self.assertEqual(normalized['dosage_form'], 'TABLET')
        self.assertEqual(normalized['route'], 'ORAL')

    def test_missing_batch_ingredient_and_form_remain_invalid(self):
        result = import_greenbook_records([{
            'product_id': 99,
            'product_name': 'Incomplete batch product',
            'strength': '10 mg',
        }])

        self.assertEqual(result.valid_rows, 0)
        self.assertEqual(result.errors, 1)
        self.assertIn('active_ingredients', result.messages[0])
        self.assertIn('form', result.messages[0])

    def test_import_creates_public_database_record(self):
        result = import_greenbook_records([GREENBOOK_RECORD])

        self.assertEqual(result.created, 1)
        medicine = Medicine.objects.get()
        self.assertEqual(medicine.source, 'PUBLIC_DATABASE')
        self.assertEqual(medicine.nafdac_registration, 'TEST-NRN-001')
        self.assertIsNone(medicine.created_by_id)
        self.assertIsNone(medicine.created_by_pharmacy_id)

    def test_actual_long_greenbook_values_import_without_truncation_and_are_idempotent(self):
        normalized = normalize_greenbook_record(LONG_GREENBOOK_RECORD)
        self.assertGreater(len(normalized['generic_name']), 255)
        self.assertGreater(len(normalized['strength']), 100)

        first = import_greenbook_records([LONG_GREENBOOK_RECORD])
        medicine = Medicine.objects.get(source_product_id='10785')
        medicine_id = medicine.pk

        self.assertEqual(first.created, 1)
        self.assertEqual(medicine.generic_name, LONG_GREENBOOK_RECORD['ingredient_name'])
        self.assertEqual(medicine.strength, normalized['strength'])

        second = import_greenbook_records([LONG_GREENBOOK_RECORD])

        self.assertEqual(second.created, 0)
        self.assertEqual(second.matched, 1)
        self.assertEqual(Medicine.objects.count(), 1)
        self.assertEqual(Medicine.objects.get().pk, medicine_id)

    def test_second_import_is_idempotent_and_preserves_uuid(self):
        first = import_greenbook_records([GREENBOOK_RECORD])
        medicine_id = Medicine.objects.get().pk

        second = import_greenbook_records([GREENBOOK_RECORD])

        self.assertEqual(first.created, 1)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.matched, 1)
        self.assertEqual(Medicine.objects.get().pk, medicine_id)
        self.assertEqual(Medicine.objects.count(), 1)

    def test_medicine_created_by_pharmacy_is_matched_and_not_reprovenanced(self):
        medicine = Medicine.objects.create(
            generic_name='Synthetic Ingredient',
            brand_name='Synthetic Product',
            strength='500mg',
            dosage_form='TABLET',
            route='ORAL',
            manufacturer='Synthetic Applicant',
            source='PHARMACY',
            nafdac_registration='',
        )
        medicine_id = medicine.pk

        result = import_greenbook_records([GREENBOOK_RECORD])

        medicine.refresh_from_db()
        self.assertEqual(result.created, 0)
        self.assertEqual(result.matched, 1)
        self.assertEqual(medicine.pk, medicine_id)
        self.assertEqual(medicine.source, 'PHARMACY')
        self.assertEqual(medicine.nafdac_registration, 'TEST-NRN-001')
        self.assertIsNone(medicine.created_by_id)

    def test_missing_required_fields_are_reported_without_writes(self):
        result = import_greenbook_records([{'product_name': 'Incomplete'}])

        self.assertEqual(result.errors, 1)
        self.assertEqual(result.created, 0)
        self.assertEqual(Medicine.objects.count(), 0)
        self.assertIn('missing required fields', result.messages[0])

    def test_dry_run_does_not_modify_database(self):
        result = import_greenbook_records([GREENBOOK_RECORD], dry_run=True)

        self.assertEqual(result.created, 1)
        self.assertEqual(Medicine.objects.count(), 0)

    def test_source_product_id_matches_and_updates_existing_record(self):
        source_record = {
            'source_id': 'sync-1', 'name': 'Source Product', 'generic_name': 'Ingredient',
            'dosage_form': 'Tablet', 'route_of_administration': 'Oral', 'strength': '10 mg',
            'applicant_name': 'Applicant', 'registration_number': 'REG-1',
        }
        first = import_greenbook_records([source_record])
        source_record['name'] = 'Updated Product'
        second = import_greenbook_records([source_record])

        medicine = Medicine.objects.get()
        self.assertEqual(first.created, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(second.matched, 0)
        self.assertEqual(medicine.brand_name, 'Updated Product')
        self.assertEqual(medicine.source_product_id, 'sync-1')

    def test_duplicate_source_product_id_is_reported_as_conflict(self):
        record = {
            'source_id': 'duplicate-1', 'name': 'Product', 'generic_name': 'Ingredient',
            'dosage_form': 'Tablet', 'route_of_administration': 'Oral', 'strength': '10 mg',
        }

        result = import_greenbook_records([record, record])

        self.assertEqual(result.created, 1)
        self.assertEqual(result.conflicts, 1)
        self.assertEqual(result.validation_summary['duplicate source product ID'], 1)

    def test_json_management_command_imports_controlled_records(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'greenbook.json'
            path.write_text(json.dumps([GREENBOOK_RECORD]), encoding='utf-8')

            call_command('import_greenbook', str(path))

        self.assertEqual(Medicine.objects.count(), 1)
        self.assertEqual(Medicine.objects.get().source, 'PUBLIC_DATABASE')

    def test_csv_management_command_imports_controlled_records(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'greenbook.csv'
            path.write_text(
                'product_name,active_ingredients,form,route,strengths,applicant_name,nrn\n'
                'Synthetic Product,Synthetic Ingredient,TABLET,ORAL,500 mg,Synthetic Applicant,TEST-NRN-001\n',
                encoding='utf-8',
            )

            call_command('import_greenbook', str(path))

        self.assertEqual(Medicine.objects.count(), 1)
        self.assertEqual(Medicine.objects.get().nafdac_registration, 'TEST-NRN-001')
