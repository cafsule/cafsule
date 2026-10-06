from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class MediaStorageConfigTests(SimpleTestCase):
    def test_default_media_root_matches_uploaded_project_files(self):
        uploaded_file = Path(settings.MEDIA_ROOT) / 'pharmacy' / 'brands' / '2026' / '09' / '18' / 'linuxb.png'
        self.assertTrue(uploaded_file.exists(), f'Media root is misconfigured; expected uploaded file at {uploaded_file}')
