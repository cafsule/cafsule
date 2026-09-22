# PROCUREMENT SYSTEM - INSPECTION REPORT

**Date:** August 29, 2026  
**Status:** Pre-Implementation Analysis Complete

---

## EXECUTIVE SUMMARY

✅ **GOOD NEWS:** Most foundational systems are already in place.  
⚠️ **ACTION NEEDED:** Supplier, Purchase, and StockMovement models must be created.

---

## 1. EXISTING MODELS - WHAT CAN BE REUSED

### 1.1 User Model (✅ Reusable)
- **Location:** `auth/models.py`
- **Roles:** SUPER_ADMIN, PLATFORM_ADMIN, PHARMACY_OWNER, PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF
- **Use:** Track `performed_by` in stock movements and audit logs
- **Status:** Complete, no changes needed

### 1.2 PharmacyBrand Model (✅ Reusable)
- **Location:** `pharmacy/models.py`
- **Key Fields:**
  - `id` (UUID primary key)
  - `owner` (OneToOne User, PHARMACY_OWNER only)
  - `verification_status` (DRAFT, PENDING_VERIFICATION, UNDER_REVIEW, VERIFIED, REJECTED, SUSPENDED)
  - `brand_name`, `legal_name`, address fields
- **Use:** All procurement must be scoped to PharmacyBrand
- **Status:** Complete, no changes needed

### 1.3 PharmacyMembership Model (✅ Reusable)
- **Location:** `pharmacy/models.py`
- **Key Fields:**
  - `pharmacy` (FK to PharmacyBrand)
  - `user` (FK to User)
  - `role` (PHARMACY_MANAGER, PHARMACIST, PHARMACY_STAFF)
  - `status` (PENDING, APPROVED, REJECTED, SUSPENDED)
  - `approved_by`, `approved_at`
- **Use:** Verify staff member has APPROVED membership before allowing stock operations
- **Status:** Complete, no changes needed

### 1.4 PharmacyInventoryItem Model (✅ Reusable)
- **Location:** `inventory/models.py`
- **Key Fields:**
  - `pharmacy` (FK to PharmacyBrand)
  - `medicine` (FK to Medicine)
  - `selling_price` (DecimalField)
  - `status` (ACTIVE, INACTIVE)
  - `is_published` (Boolean)
  - `created_by` (FK to User)
- **Use:** PurchaseItem links to this; stock receiving increases batch quantities for this item
- **Important:** Selling price MUST NOT be overwritten when receiving stock
- **Status:** Complete, no changes needed

### 1.5 InventoryBatch Model (✅ Reusable)
- **Location:** `inventory/models.py`
- **Key Fields:**
  - `inventory_item` (FK to PharmacyInventoryItem)
  - `batch_number` (CharField, max_length=100)
  - `quantity` (PositiveIntegerField)
  - `expiry_date` (DateField)
  - `cost_per_unit` (DecimalField, nullable)
  - Unique constraint: `(inventory_item, batch_number)`
  - Properties: `is_expired`, `days_until_expiry`
- **Use:** Stock receiving updates existing batch or creates new batch
- **Status:** Complete, no changes needed

### 1.6 UserActivityLog Model (✅ Reusable - Can be extended)
- **Location:** `auth/models.py`
- **Key Fields:**
  - `user` (FK to User)
  - `action` (CharField with choices)
  - `ip_address`, `user_agent`
  - `details` (JSONField)
  - `created_at`
- **Current Actions:** LOGIN, LOGOUT, TOKEN_REFRESH, PASSWORD_RESET, EMAIL_VERIFICATION, PROFILE_UPDATE, REGISTRATION
- **Use:** Can log procurement actions (SUPPLIER_CREATED, PURCHASE_CREATED, STOCK_RECEIVED, etc.)
- **Extension Needed:** Add procurement action types to ACTION_CHOICES
- **Status:** Exists but needs action types added

### 1.7 Permissions Classes (✅ Reusable)
- **Location:** `inventory/permissions.py`
- **Existing Classes:**
  - `CanManagePharmacyInventory`: Checks pharmacy ownership/membership approval
  - `CanPublishInventory`: Requires VERIFIED pharmacy
- **Use:** Apply same permission patterns to supplier/purchase operations
- **Status:** Good foundation, extend for procurement

---

## 2. MISSING MODELS - WHAT MUST BE CREATED

### 2.1 Supplier Model (❌ MISSING)
**Purpose:** Track suppliers a pharmacy procures from

**Should Be Created In:** `pharmacy/models.py` (or new `procurement/models.py`)

**Required Fields:**
```
- id (UUIDField, primary key)
- pharmacy (FK to PharmacyBrand, CASCADE)
- name (CharField)
- business_email (EmailField)
- phone (CharField)
- address (TextField)
- contact_person (CharField)
- status (CharField: ACTIVE, INACTIVE)
- created_at (DateTimeField, auto_now_add)
- updated_at (DateTimeField, auto_now)
```

**Constraints:**
- `UniqueConstraint(['pharmacy', 'name'])`: Each pharmacy has unique supplier names
- Index on `(pharmacy, status)`

**Cross-Pharmacy Isolation:** Must enforce `pharmacy = current_user_pharmacy`

**Status:** MUST CREATE

### 2.2 Purchase/StockReceipt Model (❌ MISSING)
**Purpose:** Represent stock receipt from supplier

**Should Be Created In:** `pharmacy/models.py` (or new `procurement/models.py`)

**Required Fields:**
```
- id (UUIDField, primary key)
- pharmacy (FK to PharmacyBrand, CASCADE)
- supplier (FK to Supplier, PROTECT)
- reference_number (CharField): Unique reference like "PUR-2026-000001"
- purchase_date (DateField)
- received_date (DateField, nullable): When stock was physically received
- status (CharField): DRAFT, RECEIVED, CANCELLED
- notes (TextField, blank=True)
- created_by (FK to User)
- created_at (DateTimeField, auto_now_add)
- updated_at (DateTimeField, auto_now)
```

**Constraints:**
- `UniqueConstraint(['pharmacy', 'reference_number'])`: Reference unique per pharmacy
- FK constraint on supplier must ensure supplier belongs to same pharmacy
- received_date can only be set when status=RECEIVED

**Status:** MUST CREATE

### 2.3 PurchaseItem Model (❌ MISSING)
**Purpose:** Line items within a purchase

**Should Be Created In:** `pharmacy/models.py` (or new `procurement/models.py`)

**Required Fields:**
```
- id (UUIDField, primary key)
- purchase (FK to Purchase, CASCADE)
- inventory_item (FK to PharmacyInventoryItem, PROTECT)
- quantity (PositiveIntegerField): Quantity received
- unit_cost (DecimalField): Cost per unit from supplier
- batch_number (CharField)
- expiry_date (DateField)
- created_at (DateTimeField, auto_now_add)
- updated_at (DateTimeField, auto_now)
```

**Constraints:**
- `CheckConstraint(['quantity > 0'])`
- `CheckConstraint(['unit_cost >= 0'])`
- `UniqueConstraint(['purchase', 'inventory_item', 'batch_number'])`: One batch per item per purchase

**Validation Logic:**
- expiry_date must not be in the past (unless business rules allow)
- inventory_item must belong to same pharmacy as purchase
- quantity must be positive

**Status:** MUST CREATE

### 2.4 StockMovement Model (❌ MISSING)
**Purpose:** Immutable audit log of all stock changes

**Should Be Created In:** `inventory/models.py` (or new `procurement/models.py`)

**Required Fields:**
```
- id (UUIDField, primary key)
- pharmacy (FK to PharmacyBrand, CASCADE)
- inventory_item (FK to PharmacyInventoryItem, CASCADE)
- batch (FK to InventoryBatch, PROTECT)
- movement_type (CharField): PURCHASE_RECEIPT (only for this task)
- quantity (IntegerField): Quantity moved (can be negative in future)
- reference (CharField, blank=True): Links to Purchase ID or other reference
- performed_by (FK to User, PROTECT)
- notes (TextField, blank=True)
- created_at (DateTimeField, auto_now_add)
```

**Constraints:**
- Immutable: No updates or deletes allowed through API
- Unique on nothing (multiple movements allowed)
- Index on `(pharmacy, created_at)` for efficient history queries
- Index on `(inventory_item, created_at)` for batch history

**Behavior:**
- Read-only in API
- Created automatically when stock changes
- Sole source of truth for stock change audit trail

**Status:** MUST CREATE

---

## 3. EXISTING ARCHITECTURE REVIEW

### 3.1 API Structure (✅ Good)
- Base URL: `/api/`
- Apps have URL routers: `/api/inventory/`, `/api/pharmacy/`, `/api/auth/`
- ViewSets follow DRF conventions
- **Findings:** All routing patterns established, will follow existing conventions

### 3.2 Permission System (✅ Solid)
- `IsAuthenticated`
- `CanManagePharmacyInventory`: Checks pharmacy owner or approved membership
- `CanPublishInventory`: Checks VERIFIED pharmacy + manage permission
- **Findings:** Will extend with procurement-specific permissions

### 3.3 Serializer Pattern (✅ Established)
- Separate serializers for list/detail/create/update
- `SerializerMethodField` for read-only computed fields
- **Findings:** Will follow existing patterns

### 3.4 Transaction Safety (⚠️ Partial)
- `@transaction.atomic` decorator used in views
- **Findings:** Will need `select_for_update()` for concurrent stock receiving

### 3.5 Audit Logging (✅ Exists)
- `UserActivityLog` model with action choices
- Used in auth views (LOGIN, REGISTRATION, PASSWORD_RESET, etc.)
- **Findings:** Can extend with procurement actions (PURCHASE_CREATED, STOCK_RECEIVED, etc.)

### 3.6 Database (✅ SQLite with GIS support option)
- Primary DB: SQLite (development)
- GIS support: PostGIS optional (for location)
- **Findings:** Will use standard Django ORM, compatible with both

---

## 4. IMPLEMENTATION PLAN

### Phase 1: Database Models
1. Create Supplier model with pharmacy FK and uniqueness
2. Create Purchase model with reference generation
3. Create PurchaseItem model with validation
4. Create StockMovement model (immutable)
5. Create migrations for all new models

### Phase 2: Permissions
1. Add procurement action types to UserActivityLog
2. Create permission classes for supplier/purchase management
3. Create permission classes for stock receiving

### Phase 3: Serializers & Validation
1. Create SupplierSerializer (list, detail, create, update)
2. Create PurchaseSerializer (list, detail, create)
3. Create PurchaseItemSerializer (list, detail, create)
4. Create StockMovementSerializer (read-only)
5. Implement nested serializers for purchase items

### Phase 4: ViewSets & Views
1. Create SupplierViewSet (list, create, retrieve, update, partial_update)
2. Create PurchaseViewSet (list, create, retrieve)
3. Create custom action: Purchase.receive() 
4. Create StockMovementViewSet (list, retrieve - read-only)

### Phase 5: Business Logic
1. Implement atomic stock receiving:
   - Update purchase status to RECEIVED
   - Create/update batch
   - Increase batch quantity
   - Create StockMovement record
   - All within transaction.atomic()
2. Implement reference number generation
3. Implement validation before receiving

### Phase 6: Admin Interface
1. Add Supplier to Django admin
2. Add Purchase to Django admin with PurchaseItem inline
3. Add StockMovement to Django admin (read-only)

### Phase 7: URLs & Routing
1. Add supplier endpoints to pharmacy.urls
2. Add purchase endpoints to pharmacy.urls
3. Add stock movement endpoints to inventory.urls

### Phase 8: Tests
1. Test supplier creation and ownership
2. Test purchase creation and items
3. Test stock receiving (atomic transaction)
4. Test cross-pharmacy isolation
5. Test permissions
6. Test concurrent receiving
7. Test edge cases (expired stock, invalid dates, etc.)

---

## 5. FILES TO BE CREATED/MODIFIED

### To Create:
- `pharmacy/models_procurement.py` (optional: or add to models.py)
- `inventory/serializers_procurement.py` (or add to serializers.py)
- `pharmacy/serializers_procurement.py` (or add to serializers.py)
- `inventory/permissions_procurement.py` (or add to permissions.py)
- `pharmacy/views_procurement.py` (or add to views.py)
- `pharmacy/urls_procurement.py` (or extend urls.py)
- New migration files for all new models
- `procurement/tests.py` or extend existing tests

### To Modify:
- `auth/models.py` - Add procurement actions to UserActivityLog.ACTION_CHOICES
- `inventory/permissions.py` - Add procurement-specific permissions (or new file)
- `pharmacy/urls.py` - Add supplier, purchase endpoints
- `inventory/urls.py` - Add stock movement endpoints

### Migration Strategy:
- Create individual migrations for each model
- Ensure no conflicts with existing migrations
- Test migrations on development database

---

## 6. ARCHITECTURAL DECISIONS NEEDED

### A. Where to place Supplier & Purchase models?
**Option 1:** Add to `pharmacy/models.py` (RECOMMENDED)
- Reason: These are pharmacy-domain concepts
- Keeps related models together
- Consistent with PharmacyBrand, PharmacyMembership location

**Option 2:** Create new `procurement/models.py`
- Reason: Cleaner separation of concerns
- More modular as procurement grows
- Requires new Django app

**Recommendation:** Option 1 (add to pharmacy/models.py)

### B. Reference Number Generation Strategy
**Option 1:** Database sequence-based (e.g., PUR-2026-0001)
**Option 2:** UUID-based (simple but less human-readable)
**Option 3:** Timestamp-based (e.g., PUR-20260829-123456)

**Recommendation:** Option 1 with format: `PUR-YYYY-NNNNN` where NNNNN is incremental per pharmacy per year

### C. Stock Quantity Source of Truth
Currently:
- `InventoryBatch.quantity` field stores current quantity
- Existing models support updating this field directly

For Procurement:
- When purchase status → RECEIVED, update InventoryBatch.quantity
- Create StockMovement as audit trail
- Both must happen atomically

**Decision:** `InventoryBatch.quantity` remains source of truth (updated transactionally)

### D. StockMovement Immutability
- API should not allow PATCH/PUT on StockMovement
- Database constraints optional (but good practice)
- Delete should be prevented

**Implementation:** Read-only serializer, no update/delete actions in ViewSet

---

## 7. RISKS & MITIGATIONS

| Risk | Mitigation |
|------|-----------|
| Race condition in concurrent stock receiving | Use `select_for_update()` on batch row |
| StockMovement accidentally edited | Implement read-only API + document immutability |
| Cross-pharmacy data leak | Explicitly check pharmacy ownership in all queries |
| Inventory batch data inconsistency | Use `transaction.atomic()` + atomic database operations |
| Reference number collision | Use database uniqueness constraint + format per pharmacy per year |
| Expired stock accepted | Validate expiry_date >= today in serializer + model validation |

---

## 8. TESTING STRATEGY

### Unit Tests:
- Model validations
- Permission checks
- Serializer validations

### Integration Tests:
- Supplier CRUD (each permission level)
- Purchase creation (draft → received workflow)
- Stock receiving (atomic transaction behavior)
- Concurrent receiving (race condition test)
- Cross-pharmacy isolation (verify users can't access other pharmacies)

### End-to-End Tests:
- Complete flow: Supplier → Purchase → Items → Receive → Stock Updated
- Verify StockMovement created
- Verify audit log recorded

---

## NEXT STEPS

1. **Approval:** Confirm architectural decisions (especially model location and reference generation)
2. **Implementation:** Begin Phase 1 - Database Models
3. **Testing:** Run migrations and verify schema
4. **Review:** Check model relationships and constraints before APIs

---

**Status:** Ready for Implementation Approval  
**Estimated Duration:** 2-3 hours for full implementation + testing
