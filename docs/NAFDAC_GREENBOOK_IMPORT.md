# NAFDAC Greenbook Import

The Greenbook integration is a local CSV/JSON import. Cafsule medicine search reads the local `Medicine` catalog and never calls Greenbook at runtime. The scraper's raw JSON is a top-level list of product objects; it is normalized before validation.

## Mapping

| Greenbook field | Medicine field | Behavior |
| --- | --- | --- |
| `name` / Product Name | `brand_name` | Required product label |
| `generic_name` / Active Ingredients | `generic_name` | Required; semicolon-separated combinations are preserved |
| `dosage_form` / Form | `dosage_form` | Required; mapped through an explicit form map, with unrepresentable forms mapped to `OTHER` and the raw value retained in `description` |
| `route_of_administration` / Route | `route` | Single supported routes are mapped; combined or uncommon routes use `OTHER` and the raw value is retained |
| `strength` / Strengths | `strength` | Required; spacing is normalized without collapsing combinations |
| `applicant_name` / Applicant Name | `manufacturer` | Optional applicant/manufacturer data |
| `registration_number` / NRN | `nafdac_registration` | Optional NAFDAC registration number |
| `source_id` | `source_product_id` | Required for raw Greenbook synchronization and unique per public source |
| `composition` and `description` | `description` | Preserved as source text where supplied |

Product Category, ATC code, source URLs, approval/expiry dates, and status are not separate `Medicine` fields; they are not treated as verification evidence. Imported records use `source=PUBLIC_DATABASE` and retain `verification_status=UNVERIFIED`. The source product ID is persisted so later batches can update the same row even when its name or strength changes.

## Input and command

CSV headers may use the normalized names shown below (the importer also accepts the legacy controlled-export aliases used in the service):

```text
product_name,active_ingredients,form,route,strengths,applicant_name,nrn
```

JSON is a list of objects, or an object containing a `records` list.

```bash
python manage.py import_greenbook greenbook.csv --dry-run
python manage.py import_greenbook greenbook.csv
python manage.py import_greenbook greenbook.json
```

The importer validates rows, reports valid rows and grouped error reasons, detects duplicate source IDs, matches raw Greenbook rows by `source_product_id` before falling back to the canonical medicine identity key, preserves existing UUIDs and provenance, and is idempotent. It does not scrape Greenbook, call an external endpoint, delete inventory, or modify batches or sales.

The command is server-side and not exposed to pharmacy users; administrative access is controlled by deployment access and the existing platform admin permissions for catalog management.
