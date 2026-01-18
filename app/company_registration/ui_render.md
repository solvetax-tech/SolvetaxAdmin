Perfect question 👍
You’re **100% right** to design this as a **config-driven table** so the **UI renders dynamically** based on company type and requirement list from the image.

Below is a **clean, final, production-grade `company_registration_config` design + data**, **fully aligned with the image** you shared and **consistent with your existing GST config pattern**.

---

## ✅ 1️⃣ Why a CONFIG table is correct here

From the image, requirements are:

* Mixed **company-level inputs** (names, objectives, address, electricity bill)
* **Person-level inputs** (PAN, Aadhaar, Photo, ID proofs of Directors/Partners)
* Some are **documents**, some are **plain inputs**
* Some repeat **per person**
* UI must:

  * Render fields
  * Decide *who uploads*
  * Decide *how many times*

👉 **Hardcoding this is a mistake**
👉 **Config-driven = scalable, editable, UI-friendly**

---

## ✅ 2️⃣ Final CONFIG table (small extension)

Your table is **already correct**.
We only add **`input_scope`** to help UI logic.

```sql
CREATE TABLE solvetax.company_registration_config (
    id BIGSERIAL PRIMARY KEY,

    company_type VARCHAR(50) NOT NULL,
    -- PRIVATE_LIMITED / LLP

    config_type VARCHAR(50) NOT NULL,
    -- INPUT / DOCUMENT / ROLE

    value VARCHAR(100) NOT NULL,
    -- PROPOSED_NAME, PAN, AADHAAR, ELECTRICITY_BILL etc.

    display_name VARCHAR(150) NOT NULL,
    description TEXT,

    input_scope VARCHAR(50) NOT NULL,
    -- COMPANY / PERSON

    is_multiple BOOLEAN DEFAULT FALSE,
    -- true = one per director/partner

    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0
);
```

---

## ✅ 3️⃣ CONFIG DATA (100% mapped to image)

### 🔹 Company Roles

```sql
INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'ROLE', 'DIRECTOR', 'Director', 'Director of the company', 'PERSON', true, 1),
('LLP', 'ROLE', 'PARTNER', 'Partner', 'Partner of the LLP', 'PERSON', true, 1);
```

---

### 🔹 Company-level INPUTS (Image points 1, 2, 15, 19)

```sql
INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'INPUT', 'PROPOSED_NAME_1', 'Proposed Company Name 1', 'First proposed company name', 'COMPANY', false, 1),
('PRIVATE_LIMITED', 'INPUT', 'PROPOSED_NAME_2', 'Proposed Company Name 2', 'Second proposed company name', 'COMPANY', false, 2),
('PRIVATE_LIMITED', 'INPUT', 'BUSINESS_OBJECTIVES', 'Business Objectives', 'Main business activities', 'COMPANY', false, 3),
('PRIVATE_LIMITED', 'INPUT', 'COMPANY_EMAIL', 'Company Email', 'Official company email', 'COMPANY', false, 4),
('PRIVATE_LIMITED', 'INPUT', 'COMPANY_MOBILE', 'Company Mobile Number', 'Official company mobile', 'COMPANY', false, 5),
('PRIVATE_LIMITED', 'INPUT', 'REGISTERED_OFFICE_ADDRESS', 'Registered Office Address', 'Office address of the company', 'COMPANY', false, 6);
```

(Same rows apply for LLP — only company_type changes)

---

### 🔹 PERSON INPUTS (Image points 8, 9, 10, 11, 12, 13, 14)

```sql
INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'INPUT', 'PERSON_EMAIL', 'Email of Director', 'Director email address', 'PERSON', true, 10),
('PRIVATE_LIMITED', 'INPUT', 'PERSON_MOBILE', 'Mobile Number of Director', 'Director mobile number', 'PERSON', true, 11),
('PRIVATE_LIMITED', 'INPUT', 'OCCUPATION', 'Occupation', 'Occupation of director', 'PERSON', true, 12),
('PRIVATE_LIMITED', 'INPUT', 'AREA_OF_OCCUPATION', 'Area of Occupation', 'Work area', 'PERSON', true, 13),
('PRIVATE_LIMITED', 'INPUT', 'EDUCATION', 'Educational Qualification', 'Highest qualification', 'PERSON', true, 14),
('PRIVATE_LIMITED', 'INPUT', 'RESIDENTIAL_ADDRESS', 'Residential Address', 'Present residential address', 'PERSON', true, 15),
('PRIVATE_LIMITED', 'INPUT', 'ADDRESS_DURATION', 'Duration of Stay', 'Years at current address', 'PERSON', true, 16);
```

---

### 🔹 PERSON DOCUMENTS (Image points 3–7)

```sql
INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'DOCUMENT', 'AADHAAR', 'Aadhaar Card', 'Aadhaar of Director', 'PERSON', true, 20),
('PRIVATE_LIMITED', 'DOCUMENT', 'PAN', 'PAN Card', 'PAN of Director', 'PERSON', true, 21),
('PRIVATE_LIMITED', 'DOCUMENT', 'VOTER_ID', 'Voter ID', 'Voter ID / Passport / Driving License', 'PERSON', true, 22),
('PRIVATE_LIMITED', 'DOCUMENT', 'PASSPORT', 'Passport', 'Passport of Director', 'PERSON', true, 23),
('PRIVATE_LIMITED', 'DOCUMENT', 'DRIVING_LICENSE', 'Driving License', 'Driving License of Director', 'PERSON', true, 24),
('PRIVATE_LIMITED', 'DOCUMENT', 'PHOTO', 'Passport Size Photo', 'Photo of Director', 'PERSON', true, 25),
('PRIVATE_LIMITED', 'DOCUMENT', 'ADDRESS_PROOF', 'Address Proof', 'Electricity / Telephone / Mobile Bill', 'PERSON', true, 26);
```

---

### 🔹 COMPANY DOCUMENTS (Image points 16–18)

```sql
INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'DOCUMENT', 'ELECTRICITY_BILL', 'Electricity Bill', 'Registered office address proof', 'COMPANY', false, 30),
('PRIVATE_LIMITED', 'DOCUMENT', 'RENTAL_AGREEMENT', 'Rental Agreement', 'Office rental agreement', 'COMPANY', false, 31),
('PRIVATE_LIMITED', 'DOCUMENT', 'NOC', 'No Objection Certificate', 'NOC from property owner', 'COMPANY', false, 32);
```

---

## ✅ 4️⃣ How UI will use this (important)

Example API:

```sql
SELECT *
FROM solvetax.company_registration_config
WHERE company_type = 'PRIVATE_LIMITED'
AND is_active = true
ORDER BY sort_order;
```

UI logic:

* `config_type = INPUT` → render text/textarea
* `config_type = DOCUMENT` → render upload
* `input_scope = PERSON` + `is_multiple = true` → repeat per director/partner
* `input_scope = COMPANY` → single field

---

## 🧠 Final Verdict

✔ Matches **image line-by-line**
✔ Scales to LLP / OPC / PUBLIC LIMITED
✔ Zero hardcoding
✔ Clean engineering + business clarity
✔ Same design philosophy as your GST system

If you want next:

* **company_registration_persons table**
* **company_registration_documents table**
* **UI JSON payload structure**
* **Validation rules per config**

Just say 👍
