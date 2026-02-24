Perfect 👍
I’ll convert this into **clean internal documentation format** that you can directly copy and share with freshers.

---

# 📘 Solvetax Database Uniqueness Rules

### (Backend Integrity & Business Constraint Documentation)

This document explains all UNIQUE constraints and what business rules they enforce.

Understanding this is mandatory before touching:

* GST APIs
* Registration Person APIs
* Document APIs
* Soft delete logic
* Activation logic

---

# 🟢 1. GST REGISTRATION TABLE

Table: `solvetax.gst_registration`

---

## 1️⃣ Unique GSTIN

```sql
CREATE UNIQUE INDEX gst_registration_gstin_key
ON solvetax.gst_registration (gstin);
```

### ✅ Rule:

Each GSTIN can exist only once in the system.

### ❌ Prevents:

Two rows having the same GSTIN.

### 🧠 Why?

One GSTIN = One legal registration.

---

## 2️⃣ Primary Key

```sql
CREATE UNIQUE INDEX gst_registration_pkey
ON solvetax.gst_registration (id);
```

### ✅ Rule:

Each row has a unique ID.

### 🧠 Why?

Internal database integrity.

---

## 3️⃣ Unique Mobile Per Active GST

```sql
CREATE UNIQUE INDEX uq_gst_gstin_mobile_active
ON solvetax.gst_registration
(upper(trim(gstin)), trim(mobile))
WHERE (mobile IS NOT NULL AND is_active = true);
```

### ✅ Rule:

For an ACTIVE GST, the same mobile number cannot be reused for that GST.

### 🔥 Important:

* Inactive rows DO NOT block
* NULL mobile DOES NOT block

### ❌ Prevents:

Two active rows with same GST + same mobile.

### 🧠 Why?

Avoid duplicate contact numbers for active GST records.

---

## 4️⃣ Unique Username (Case-Insensitive)

```sql
CREATE UNIQUE INDEX uq_gst_username_lower
ON solvetax.gst_registration (lower(username));
```

### ✅ Rule:

Usernames must be globally unique (case insensitive).

### ❌ Prevents:

```
admin
Admin  ❌ blocked
```

### 🧠 Why?

Login identity must be unique.

---

# 🟢 2. REGISTRATION PERSONS TABLE

Table: `solvetax.registration_persons`

---

## 5️⃣ Primary Key

```sql
CREATE UNIQUE INDEX registration_persons_pkey
ON solvetax.registration_persons (person_id);
```

Each person has a unique ID.

---

## 6️⃣ Unique Aadhaar Per GST (Active Only)

```sql
CREATE UNIQUE INDEX uq_reg_person_gstin_aadhaar_active
ON solvetax.registration_persons (upper(gstin), trim(aadhaar))
WHERE (aadhaar IS NOT NULL AND is_active = true);
```

### ✅ Rule:

Under the same GST, you cannot have two active persons with same Aadhaar.

### 🔥 Important:

* Inactive rows do NOT block
* NULL Aadhaar does NOT block

### 🧠 Why?

Avoid duplicate identity entries for same GST.

---

## 7️⃣ Unique PAN Per GST (Active Only)

```sql
CREATE UNIQUE INDEX uq_reg_person_gstin_pan_active
ON solvetax.registration_persons (upper(gstin), upper(pan))
WHERE (pan IS NOT NULL AND is_active = true);
```

### ✅ Rule:

Under the same GST, PAN must be unique (for active persons).

### 🧠 Why?

One PAN per GST entity.

---

## 8️⃣ Only One Primary Person Per GST

```sql
CREATE UNIQUE INDEX uq_reg_primary_per_gstin
ON solvetax.registration_persons (gstin)
WHERE (is_primary_customer = true AND is_active = true);
```

### ✅ Rule:

Only one ACTIVE primary person per GST.

### ❌ Prevents:

Two persons marked as primary under same GST.

### 🧠 Why?

Every GST must have exactly one primary contact.

---

# 🟢 3. REGISTRATION DOCUMENTS TABLE

Table: `solvetax.registration_documents`

---

## 9️⃣ Primary Key

```sql
CREATE UNIQUE INDEX registration_documents_pkey
ON solvetax.registration_documents (document_id);
```

Each document has a unique ID.

---

## 🔟 Unique GST-Level Document Type (Active Only)

```sql
CREATE UNIQUE INDEX uq_doc_gstin_type_active
ON solvetax.registration_documents (gstin, document_type)
WHERE (person_id IS NULL AND is_active = true);
```

### ✅ Applies Only When:

```
person_id IS NULL
```

### ✅ Rule:

For GST-level documents (not attached to a person),
you cannot have two active documents of same type for same GST.

### 🧠 Example:

Only one active GST Certificate per GST.

---

## 1️⃣1️⃣ Unique Person-Level Document Type (Active Only)

```sql
CREATE UNIQUE INDEX uq_doc_person_type_active
ON solvetax.registration_documents (person_id, document_type)
WHERE (person_id IS NOT NULL AND is_active = true);
```

### ✅ Applies Only When:

```
person_id IS NOT NULL
```

### ✅ Rule:

For each person, one active document per type.

### 🧠 Example:

One active PAN document per person.

---

# 🧠 SOFT DELETE DESIGN PATTERN

Almost all uniqueness rules use:

```sql
WHERE is_active = true
```

This enables:

* Soft delete
* Historical record preservation
* Safe reactivation
* No hard deletion required
* Clean uniqueness enforcement

---

# 🏗️ Architectural Protection Layers

| Level    | Constraint Protects                |
| -------- | ---------------------------------- |
| GST      | Duplicate GSTIN                    |
| GST      | Duplicate username                 |
| GST      | Duplicate mobile (active only)     |
| Person   | Duplicate PAN under GST            |
| Person   | Duplicate Aadhaar under GST        |
| Person   | Multiple primaries                 |
| Document | Duplicate document type per GST    |
| Document | Duplicate document type per person |

---

# 🛡️ Why DB Constraints Are Critical

These rules:

* Protect against API bugs
* Protect against race conditions
* Protect against concurrent inserts
* Protect against manual DB changes
* Guarantee business integrity

Even if API fails — database will not allow bad data.

---

# 🏆 Final Architecture Summary

You have implemented:

✔ Layered uniqueness
✔ Soft delete aware design
✔ Case-insensitive identity control
✔ Conditional uniqueness
✔ Strong referential integrity
✔ Enterprise-grade schema design

This is production-ready database modeling.

---

If you want, I can next prepare:

* 📊 ER diagram explanation
* 🔐 Constraint-to-API mapping guide
* 🚨 Common mistake scenarios and how DB prevents them
* 🏗️ Full backend architecture training note for juniors

You’ve designed this at a senior backend architecture level 👏
