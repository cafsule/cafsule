import csv
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from medicine.services import import_greenbook_records


class Command(BaseCommand):
    help = 'Import a controlled Greenbook CSV or JSON export into the global medicine catalog.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=Path, help='Path to the local CSV or JSON input file.')
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Validate and report changes without modifying the database.',
        )
        parser.add_argument(
            '--format',
            choices=('csv', 'json'),
            dest='file_format',
            help='Override format detection based on the file extension.',
        )

    def handle(self, *args, **options):
        path = options['file']
        if not path.is_file():
            raise CommandError(f'Input file does not exist: {path}')

        file_format = options['file_format'] or path.suffix.lower().lstrip('.')
        if file_format not in {'csv', 'json'}:
            raise CommandError('Input format must be CSV or JSON (use --format to override).')

        try:
            records = self._read_records(path, file_format)
        except (OSError, UnicodeDecodeError, ValueError, csv.Error) as error:
            raise CommandError(f'Unable to read {path}: {error}') from error

        result = import_greenbook_records(records, dry_run=options['dry_run'])
        mode = ' (dry run)' if options['dry_run'] else ''
        self.stdout.write(f'Greenbook import{mode}')
        self.stdout.write('-' * (17 + len(mode)))
        self.stdout.write(f'Input: {path}')
        for label, value in (
            ('Rows read', result.rows_read),
            ('Valid rows', result.valid_rows),
            ('Created', result.created),
            ('Updated', result.updated),
            ('Matched existing', result.matched),
            ('Skipped', result.skipped),
            ('Errors', result.errors),
            ('Conflicts', result.conflicts),
        ):
            self.stdout.write(f'{label}: {value}')
        if result.validation_summary:
            self.stdout.write('Validation summary')
            self.stdout.write('------------------')
            for reason, count in result.validation_summary.items():
                self.stdout.write(f'{reason}: {count}')
        for message in result.messages:
            self.stdout.write(self.style.WARNING(message))

    @staticmethod
    def _read_records(path, file_format):
        with path.open('r', encoding='utf-8-sig', newline='') as source:
            if file_format == 'json':
                payload = json.load(source)
                if isinstance(payload, dict):
                    payload = payload.get('records')
                if not isinstance(payload, list):
                    raise ValueError('JSON input must be a list or an object with a records list.')
                if not all(isinstance(record, dict) for record in payload):
                    raise ValueError('Each JSON record must be an object.')
                return payload

            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise ValueError('CSV input must include a header row.')
            return list(reader)
