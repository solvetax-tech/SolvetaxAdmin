📘 SolveTax – GST Registration Module
Database Design & Business Logic Documentation

Schema: solvetax
Table: gst_registration

1️⃣ Introduction

The gst_registration table is the core table that manages:

GST registrations obtained from the GST portal

Registration lifecycle

Customer ownership

Contact details

Compliance status

Assignment to relationship managers (RM)

Each row in this table represents:

🔹 One GSTIN
🔹 Belonging to one customer
🔹 With one portal username
🔹 Managed by one RM
🔹 Following a lifecycle

This table is designed to be:

Production-ready

Audit-safe

Indian GST compliant

Scalable

Reactivation-friendly

2️⃣ High-Level Business Model
Relationship Overview
A Customer Can Have:

Multiple GST Registrations

Different GSTINs across states

A GST Registration:

Belongs to exactly one customer

Has one GSTIN

Has one PAN

Has one portal username

Can have multiple registration persons (in another table)

Logical Representation
Customer (1) -------- (Many) GST Registrations
GST Registration (1) -------- (Many) Registration Persons
3️⃣ Core Identity Rules
✅ Rule 1: GSTIN Must Be Globally Unique
Why?

A GSTIN represents a legally registered GST entity.
Two records with the same GSTIN cannot exist.

Enforced By:
CONSTRAINT gst_registration_gstin_key UNIQUE (gstin)
Business Meaning:
Scenario	Allowed?
Create duplicate GSTIN	❌ No
Deactivate and recreate same GSTIN	❌ No
Reactivate existing GSTIN	✅ Yes

We never create duplicate GSTIN records.
We reactivate the existing one.

✅ Rule 2: PAN Can Have Multiple GSTINs
Important Indian GST Rule

One PAN → Multiple GSTINs (one per state)

So:

❌ PAN cannot be globally unique
✅ PAN + GSTIN combination must be unique

Enforced By:
CREATE UNIQUE INDEX uq_gst_pan_gstin
ON solvetax.gst_registration
(upper(trim(pan)), upper(trim(gstin)));
Business Meaning:
PAN	GSTIN	Allowed?
ABCDE1234F	GSTIN1	✅
ABCDE1234F	GSTIN2	✅
ABCDE1234F	GSTIN1 (again)	❌
4️⃣ Contact Management Rules
✅ Rule 3: Mobile Number Unique Among Active Records
Why?

Two active GST registrations cannot share the same mobile number.
But after deactivation, the number can be reused.

Enforced By:
CREATE UNIQUE INDEX uq_gst_mobile_active
ON solvetax.gst_registration (trim(mobile))
WHERE mobile IS NOT NULL AND is_active = true;
Meaning:
Case	Allowed?
Same mobile, both active	❌
Old inactive, new active	✅
Null mobile	✅

This supports:

Customer number changes

Reassignment of number

Reactivation flexibility

✅ Rule 4: Secondary Email Unique Among Active Records

Secondary email represents customer’s real email.

Enforced by:

CREATE UNIQUE INDEX uq_gst_secondary_email_active
ON solvetax.gst_registration (lower(trim(secondary_email)))
WHERE secondary_email IS NOT NULL AND is_active = true;
Meaning:

Only one active GST per secondary email

Reusable after deactivation

✅ Rule 5: Primary Email Can Repeat

Primary email field:

Often system-generated

May be reused across 10–15 GSTINs

Therefore:

✔ No unique constraint
✔ Fully repeatable

✅ Rule 6: Username Must Be Globally Unique

Portal username must never duplicate.

CONSTRAINT gst_registration_username_key UNIQUE (username)
5️⃣ Data Validation Rules (DB-Level Protection)

We enforce format validation at database level so:

No bad data enters system

APIs cannot bypass validation

DB remains clean

🔹 GSTIN Format Check
CONSTRAINT chk_gst_format CHECK (
gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'
)

Ensures valid Indian GST format.

🔹 PAN Format Check
CONSTRAINT chk_pan_format CHECK (
pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
)
🔹 Mobile Format Check
CONSTRAINT chk_mobile_format CHECK (
mobile IS NULL OR mobile ~ '^[0-9]{10}$'
)
🔹 Secondary Email Format Check
CONSTRAINT chk_secondary_email_format CHECK (
secondary_email IS NULL OR secondary_email ~* 'email-regex'
)
6️⃣ Lifecycle Management

A GST registration passes through lifecycle states:

Status	Description
DRAFT	Created but not submitted
APPROVED	GST activated
SUSPENDED	Suspended by authority
CANCELLED	Cancelled
INACTIVE	Soft deleted internally

Controlled by:

registration_status

approved_at

is_active

7️⃣ Soft Delete Strategy

We DO NOT hard delete records.

Instead:

is_active = false
Why?

Audit safety

Historical preservation

Reactivation possible

Contact reuse possible

8️⃣ Index Strategy (Performance Design)

Indexes created for:

Index	Purpose
idx_gst_customer_id	Filter by customer
idx_gst_is_active	Filter active
idx_gst_registration_status	Dashboard status
idx_gst_rm_id	RM-based filtering
idx_gst_created_at	Sorting
idx_gst_active_created_at	Active timeline
9️⃣ Foreign Key Integrity
customer_id → customers(customer_id)
created_by → employees(emp_id)
rm_id → employees(emp_id)

Ensures:

No orphan records

Valid ownership

Valid RM assignment

🔟 API Design Guidelines for Developers

When building APIs:

Always Normalize Before Insert:

gstin = upper(trim(gstin))

pan = upper(trim(pan))

secondary_email = lower(trim(secondary_email))

mobile = trim(mobile)

Insert Flow Should:

Check if GSTIN exists

If exists and inactive → reactivate

Validate mobile uniqueness

Validate secondary email uniqueness

Insert inside transaction

1️⃣1️⃣ Architectural Strength

This design ensures:

✔ Indian GST compliant
✔ Multi-state PAN supported
✔ No duplicate active contacts
✔ Reactivation-friendly
✔ Soft delete safe
✔ Performance optimized
✔ Database-level validation
✔ Enterprise-grade data integrity

1️⃣2️⃣ Final System Philosophy

This table is designed using:

Partial unique indexes

Soft delete strategy

Composite uniqueness

Database-level validation

Active-only uniqueness enforcement

Real Indian business compliance