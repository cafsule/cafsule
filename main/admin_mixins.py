"""Reusable admin mixins for enterprise-grade Django admin UX.

This module intentionally keeps the logic framework-agnostic so it can be reused
across apps without touching each model admin manually.
"""

from __future__ import annotations

from typing import Iterable

from django import forms
from django.db import models
from django.template.defaultfilters import truncatechars
from django.utils.html import format_html


class GlassAdminImagePreviewMixin:
    """Inject image preview columns into any admin model automatically.

    Any admin class inheriting from this mixin will automatically inspect the
    model's fields, detect all ImageField definitions, and dynamically add
    thumbnail preview methods to list_display. This makes a mature admin UI
    scale without hand-writing preview methods for every model.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._inject_image_preview_columns()

    def _get_image_fields(self) -> Iterable[models.Field]:
        """Return the model's image fields in a deterministic order."""
        if not getattr(self, 'model', None):
            return []
        return [
            field
            for field in self.model._meta.fields
            if isinstance(field, models.ImageField)
        ]

    def _build_image_preview_method(self, field_name: str, label: str):
        """Create a dynamic preview method for a single ImageField."""

        def preview_image(obj):
            value = getattr(obj, field_name, None)
            if not value:
                return format_html(
                    '<span style="display:inline-flex;align-items:center;justify-content:center;'
                    'width:50px;height:50px;border-radius:8px;border:1px solid rgba(255,255,255,0.22);'
                    'background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.68);'
                    'font-size:10px;letter-spacing:0.08em;text-transform:uppercase;">'
                    'No image'
                    '</span>'
                )

            url = value.url if hasattr(value, 'url') else value
            if not url:
                return format_html(
                    '<span style="display:inline-flex;align-items:center;justify-content:center;'
                    'width:50px;height:50px;border-radius:8px;border:1px solid rgba(255,255,255,0.22);'
                    'background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.68);'
                    'font-size:10px;letter-spacing:0.08em;text-transform:uppercase;">'
                    'No image'
                    '</span>'
                )

            return format_html(
                '<span class="glass-thumb-wrap" style="display:inline-flex;align-items:center;'
                'justify-content:center;width:50px;height:50px;padding:0;border-radius:8px;'
                'background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.18);'
                'overflow:hidden;box-shadow:0 8px 20px rgba(15,23,42,0.18);">'
                '<img src="{url}" alt="{label}" style="display:block;width:50px;height:50px;'
                'object-fit:cover;border-radius:8px;filter:saturate(1.10) contrast(1.04);" />'
                '</span>',
                url=url,
                label=label,
            )

        preview_image.short_description = label
        preview_image.admin_order_field = field_name
        preview_image.allow_tags = True
        return preview_image

    def _inject_image_preview_columns(self):
        """Attach preview methods to list_display in place."""
        image_fields = self._get_image_fields()
        if not image_fields:
            return

        # Ensure list_display exists and is mutable.
        current_display = list(getattr(self, 'list_display', []) or [])

        for field in image_fields:
            method_name = f'preview_{field.name}'
            if method_name in current_display:
                continue

            preview_method = self._build_image_preview_method(field.name, field.verbose_name)
            setattr(self, method_name, preview_method)
            current_display.append(method_name)

        self.list_display = tuple(current_display)


__all__ = ["GlassAdminImagePreviewMixin"]
