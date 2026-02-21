Perfect Bhanu 👍
Below is a **clean, structured, production-grade Markdown (.md) document** version.

You can directly copy this into:

```
GST_REGISTRATION_ARCHITECTURE.md
```

---

# 📘 GST Registration – Production Architecture Document

**Schema:** `solvetax`
**Table:** `gst_registration`
**Purpose:** Stores GST registrations for customers with strict business validation, lifecycle control, audit consistency, and performance optimization.

---

# 1️⃣ Objective of This Table

This table is designed to:

* Maintain GST registrations per customer
* Enforce GST–PAN legal consistency
* Control lifecycle states (Draft → Approved → Suspended → Cancelled)
* Ensure database-level business rule enforcement
* Support scalable filtering & reporting
* Maintain enterprise-grade integrity

---

# 2️⃣ Core Identity Structure

| Column        | Description                            |
| ------------- | -------------------------------------- |
| `id`          | Internal primary key (BIGSERIAL)       |
| `customer_id` | Links GST to platform customer         |
| `gstin`       | Official 15-digit GST number (Unique)  |
| `pan`         | PAN number associated with GST         |
| `username`    | Unique login username                  |
| `password`    | Application-managed encrypted password |

---

## ✅ Enforced Constraints

### ✔ GST Format Validation

```sql
CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$')
```

Ensures valid GSTIN structure.

---

### ✔ PAN Format Validation

```sql
CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$')
```

Ensures valid PAN structure.

---

### ✔ PAN–GST Matching Rule (Legal Consistency)

```sql
CHECK (
  upper(trim(pan)) =
  substring(upper(trim(gstin)) from 3 for 10)
)
```

Ensures:

* PAN inside GSTIN matches PAN column.
* Prevents PAN mismatch fraud.
* Maintains legal integrity.

---

### ✔ Unique Constraints

* `gstin` → Unique
* `username` → Unique (case insensitive index recommended)

---

# 3️⃣ Business Classification Fields

| Column               | Purpose                             |
| -------------------- | ----------------------------------- |
| `registration_type`  | NORMAL / COMPOSITION                |
| `ownership_category` | PROPRIETARY / PARTNERSHIP / COMPANY |
| `business_type`      | Manufacturer / Trader / etc         |
| `turnover_details`   | Revenue bracket                     |
| `state`              | GST State                           |
| `is_rcm_applicable`  | Reverse charge applicability        |

⚠ These are controlled using configuration table `gst_registration_config`.

UI dropdowns must read from config table.

---

# 4️⃣ Registration Lifecycle Management

| Column                | Purpose                                  |
| --------------------- | ---------------------------------------- |
| `registration_status` | DRAFT / APPROVED / SUSPENDED / CANCELLED |
| `approved_at`         | Timestamp of approval                    |
| `suspension_reason`   | If suspended                             |
| `cancellation_reason` | If cancelled                             |

---

## ✅ Business Rule: Approval Consistency

```sql
CHECK (
    (registration_status = 'APPROVED' AND approved_at IS NOT NULL)
    OR
    (registration_status <> 'APPROVED' AND approved_at IS NULL)
)
```

This guarantees:

* If status = APPROVED → approved_at must exist.
* If status ≠ APPROVED → approved_at must be NULL.

---

## ✅ Automatic Timestamp Management

Trigger: `trg_set_approved_timestamp`

Logic:

* When status changes to APPROVED → sets `approved_at = NOW()`
* When status changes from APPROVED → clears `approved_at`

This ensures:

* No manual mistakes
* DB-level lifecycle enforcement
* Audit reliability

---

# 5️⃣ Contact Information Logic

| Column            | Rule                        |
| ----------------- | --------------------------- |
| `mobile`          | Optional, must be 10 digits |
| `email`           | Case-insensitive indexed    |
| `secondary_email` | Case-insensitive indexed    |

---

## ✔ Mobile Validation

```sql
CHECK (mobile IS NULL OR mobile ~ '^[0-9]{10}$')
```

---

## ✔ Unique Mobile Per GST (Active Only)

```sql
UNIQUE (
  upper(trim(gstin)),
  trim(mobile)
)
WHERE mobile IS NOT NULL AND is_active = true
```

Meaning:

* Same mobile can exist across different GSTs
* Same GST cannot reuse same mobile while active

---

# 6️⃣ Activity & Soft Delete Model

| Column       | Purpose            |
| ------------ | ------------------ |
| `is_active`  | Soft delete flag   |
| `created_at` | Creation timestamp |
| `updated_at` | Update timestamp   |

System does NOT hard delete records.

Soft delete ensures:

* Historical audit safety
* Referential safety
* Legal traceability

---

# 7️⃣ Performance & Indexing Strategy

Indexes are aligned with API filtering logic.

---

## 🔹 Search Indexes

| Index                         | Purpose                        |
| ----------------------------- | ------------------------------ |
| `idx_gst_customer_id`         | Filter by customer             |
| `idx_gst_rm_id`               | Filter by relationship manager |
| `idx_gst_registration_status` | Filter by status               |
| `idx_gst_is_active`           | Active filtering               |
| `idx_gst_created_at`          | Sorting                        |
| `idx_gst_email_lower`         | Case-insensitive email search  |
| `idx_gst_gstin_upper`         | Case-insensitive GST search    |

---

## 🔹 Composite Performance Indexes

Optimized for dynamic filtering:

* `(customer_id, is_active, created_at DESC)`
* `(rm_id, registration_status, is_active, created_at DESC)`
* `(business_type, is_active, created_at DESC)`
* `(registration_status, is_active, created_at DESC)`

These match API WHERE clauses.

---

# 8️⃣ Foreign Key Integrity

```sql
customer_id → solvetax.customers(customer_id)
created_by → solvetax.employees(emp_id)
rm_id → solvetax.employees(emp_id)
```

Ensures:

* No orphan GST entries
* Proper employee tracking
* Operational accountability

---

# 9️⃣ What This Architecture Guarantees

✅ GST–PAN legal consistency
✅ No invalid GSTIN entry
✅ No incorrect lifecycle state
✅ Automatic approval timestamp handling
✅ Soft deletion support
✅ Controlled uniqueness logic
✅ Case-insensitive search support
✅ Query optimization
✅ Audit safety
✅ Enterprise-grade integrity

---

# 🔟 Architectural Quality Level

This table now qualifies as:

* ✔ Financial-grade schema
* ✔ Audit-ready
* ✔ GST-compliant
* ✔ Scalable
* ✔ Production-ready
* ✔ Startup → Enterprise scalable design

---

# 🏁 Final Conclusion

The `gst_registration` table now:

* Enforces legal GST consistency
* Enforces lifecycle correctness
* Enforces data format correctness
* Optimizes performance
* Protects against invalid state transitions
* Supports scalable API filtering
* Maintains clean separation of business configuration

This is a **proper production-grade GST registration design.**

---

If you want, I can next give:

* 📊 ER Diagram documentation (Markdown)
* 🧠 Full GST lifecycle explanation doc
* 🏦 Audit explanation version for CA
* 📈 Investor-ready architecture explanation version

You’ve designed this correctly now, Bhanu.
This is clean engineering. 👏
