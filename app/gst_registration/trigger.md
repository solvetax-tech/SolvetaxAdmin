# SolveTax Database Trigger Documentation
**Schema:** solvetax  
**Author:** Backend Team  
**Purpose:** Enforce business rules and maintain data integrity automatically  

---

# 1️⃣ Overview

This document explains the database triggers implemented in the `solvetax` schema.

These triggers ensure:

- A document cannot be activated if the person is inactive
- When a person is deactivated, all related documents are deactivated
- Verification timestamps are automatically recorded
- GST approval timestamps are automatically recorded

All logic is enforced at the database level to maintain strict data consistency.

---

# 2️⃣ Trigger Architecture Summary

| Table | Trigger | Purpose |
|-------|---------|----------|
| gst_registration | trg_set_approved_timestamp | Sets approval timestamp automatically |
| registration_documents | trg_prevent_doc_activation | Prevents activating doc if person inactive |
| registration_documents | trg_set_verified_timestamp | Sets verified timestamp automatically |
| registration_persons | trg_sync_docs_on_person_deactivate | Deactivates docs when person deactivated |

---

# 3️⃣ Detailed Trigger Documentation

---

## 🔹 3.1 GST Approval Timestamp Trigger

### Trigger Name:
`trg_set_approved_timestamp`

### Table:
`solvetax.gst_registration`

### Trigger Type:
BEFORE UPDATE

### Purpose:
Automatically sets `approved_at` when a GST registration is approved.

### Business Rule:
If `approved = TRUE`, system records current timestamp.

### Why This Exists:
- Prevents manual timestamp errors
- Ensures audit reliability
- Maintains compliance tracking

---

## 🔹 3.2 Prevent Document Activation Trigger

### Trigger Name:
`trg_prevent_doc_activation`

### Table:
`solvetax.registration_documents`

### Trigger Type:
BEFORE UPDATE OF is_active

### Purpose:
Prevents activating a document if its parent person is inactive.

### Business Rule:
A document cannot be active if its related person is inactive.

### What It Does:
When:
```
is_active changes from FALSE → TRUE
```

It checks:
```
registration_persons.is_active
```

If person is inactive:
```
ERROR: Cannot activate document. Person is inactive.
```

### Why This Exists:
- Prevents inconsistent data
- Maintains parent-child integrity
- Enforces business hierarchy rules

---

## 🔹 3.3 Verified Timestamp Trigger

### Trigger Name:
`trg_set_verified_timestamp`

### Table:
`solvetax.registration_documents`

### Trigger Type:
BEFORE UPDATE OF verified

### Purpose:
Automatically sets `verified_at` when document is verified.

### Business Rule:
When:
```
verified changes from FALSE/NULL → TRUE
```

System sets:
```
verified_at = NOW()
```

### Why This Exists:
- Prevents manual timestamp tampering
- Ensures audit traceability
- Maintains compliance standards

---

## 🔹 3.4 Sync Documents on Person Deactivation

### Trigger Name:
`trg_sync_docs_on_person_deactivate`

### Table:
`solvetax.registration_persons`

### Trigger Type:
AFTER UPDATE OF is_active

### Purpose:
When a person becomes inactive, all related documents are automatically deactivated.

### Business Rule:
If:
```
person.is_active changes from TRUE → FALSE
```

Then:
```
All registration_documents for that person:
    - is_active = FALSE
    - verified = FALSE
    - verified_at = NULL
    - verified_by = NULL
```

### Why This Exists:
- Maintains business consistency
- Prevents verified but inactive documents
- Avoids constraint violations
- Keeps system logically correct

---

# 4️⃣ Business Integrity Flow

### Person Active → Documents Can Be Active

### Person Inactive →
- Documents automatically deactivated
- Verification removed
- Activation attempts blocked

This ensures:
- No orphan active documents
- No invalid verified states
- Clean enterprise-grade logic

---

# 5️⃣ Why Triggers Are Used (Architectural Decision)

Triggers are implemented to:

- Enforce business rules at database level
- Prevent frontend or API bypass
- Maintain centralized validation
- Ensure audit reliability
- Protect data integrity in multi-service environments

This design follows enterprise database best practices.

---

# 6️⃣ Important Notes for Developers

- Do NOT manually set timestamp columns.
- Do NOT attempt to activate documents for inactive persons.
- Always understand parent-child relationships before updating records.
- Business rules are enforced at DB level and cannot be bypassed.

---

# 7️⃣ Conclusion

These triggers ensure:

✔ Hierarchical integrity  
✔ Automated auditing  
✔ Compliance safety  
✔ Enterprise-grade data consistency  

The `solvetax` schema is designed with strict relational governance to prevent logical corruption of business data.

---

**End of Document**

SELECT 
    n.nspname      AS schema_name,
    c.relname      AS table_name,
    t.tgname       AS trigger_name,
    pg_get_triggerdef(t.oid) AS trigger_definition
FROM pg_trigger t
JOIN pg_class c ON t.tgrelid = c.oid
JOIN pg_namespace n ON c.relnamespace = n.oid
WHERE n.nspname = 'solvetax'
  AND NOT t.tgisinternal
ORDER BY table_name, trigger_name;