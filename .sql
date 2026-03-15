ALTER TABLE solvetax.versions
ADD CONSTRAINT chk_action_json
CHECK (
(
(action = 'CREATE' AND json IS NOT NULL AND updated_json IS NULL)
OR
(action = 'UPDATE' AND json IS NOT NULL AND updated_json IS NOT NULL)
OR
(action = 'DELETE' AND json IS NULL AND updated_json IS NOT NULL)
OR
(action = 'ACTIVATE' AND json IS NULL AND updated_json IS NOT NULL)
)
);
-- solvetax.crm_leads definition
-- Drop table

-- DROP TABLE solvetax.crm_leads;

CREATE TABLE solvetax.crm_leads (
	id bigserial NOT NULL,
	cust_id int8 NOT NULL,
	"name" varchar(150) NOT NULL,
	"language" varchar(50) NULL,
	"date" timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	lead_type text NULL,
	stage text NULL,
	call_status text NULL,
	follow_up_date timestamp NULL,
	last_dialed timestamp NULL,
	today_connected timestamp NULL,
	today_converted timestamp NULL,
	review text NULL,
	call_attempts int4 DEFAULT 0 NULL,
	assigned_rm int8 NULL,
	lead_source varchar(100) NULL,
	CONSTRAINT crm_leads_pkey PRIMARY KEY (id)
);


-- solvetax.crm_leads foreign keys

ALTER TABLE solvetax.crm_leads ADD CONSTRAINT crm_leads_assigned_rm_fkey FOREIGN KEY (assigned_rm) REFERENCES solvetax.employees(emp_id);
ALTER TABLE solvetax.crm_leads ADD CONSTRAINT fk_crmleads_customer FOREIGN KEY (cust_id) REFERENCES solvetax.customers(customer_id);


-- solvetax.customers definition

-- Drop table

-- DROP TABLE solvetax.customers;

CREATE TABLE solvetax.customers (
	customer_id int8 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	full_name varchar(150) NOT NULL,
	email varchar(150) NULL,
	mobile varchar(15) NOT NULL,
	business_name varchar(200) NULL,
	business_description text NULL,
	business_image_url text NULL,
	business_type varchar(50) NULL,
	state varchar(100) NULL,
	city varchar(100) NULL,
	remark text NULL,
	rm_id int8 NULL,
	op_id int8 NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT customers_pkey PRIMARY KEY (customer_id),
	CONSTRAINT customers_rm_id_fkey FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id),
	CONSTRAINT customers_op_id_fkey FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id)
);


-- solvetax.employees definition

-- Drop table

-- DROP TABLE solvetax.employees;

CREATE TABLE solvetax.employees (
	emp_id int8 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	username varchar(100) NOT NULL,
	email varchar(150) NOT NULL,
	password_hash text NOT NULL,
	first_name varchar(100) NULL,
	last_name varchar(100) NULL,
	phone_number varchar(20) NULL,
	"role" varchar(50) DEFAULT 'SE'::character varying NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT employees_email_key UNIQUE (email),
	CONSTRAINT employees_pkey PRIMARY KEY (emp_id),
	CONSTRAINT employees_username_key UNIQUE (username)
);


-- solvetax.gst_registration definition

-- Drop table

-- DROP TABLE solvetax.gst_registration;

CREATE TABLE solvetax.gst_registration (
	id int8 GENERATED ALWAYS AS IDENTITY( INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 CACHE 1 NO CYCLE) NOT NULL,
	customer_id int8 NOT NULL,
	gstin varchar(15) NULL,
	username varchar(100) NOT NULL,
	"password" text NOT NULL,
	pan varchar(10) NOT NULL,
	registration_type varchar(50) NULL,
	ownership_category varchar(50) NULL,
	business_type varchar(50) NULL,
	state varchar(50) NULL,
	registration_status varchar(50) DEFAULT 'DRAFT'::character varying NULL,
	suspension_reason text NULL,
	cancellation_reason text NULL,
	approved_at timestamp NULL,
	is_rcm_applicable bool DEFAULT false NULL,
	turnover_details varchar(50) DEFAULT 'LESS_THAN_2CR'::character varying NULL,
	created_by int8 NULL,
	rm_id int8 NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	is_filing_needed bool DEFAULT true NULL,
	is_active bool DEFAULT true NULL,
	mobile varchar(20) NULL,
	email varchar(150) NULL,
	secondary_email varchar(150) NULL,
	CONSTRAINT gst_registration_gstin_key UNIQUE (gstin),
	CONSTRAINT gst_registration_pkey PRIMARY KEY (id),
	CONSTRAINT gst_registration_username_key UNIQUE (username),
	CONSTRAINT gst_registration_created_by_fkey FOREIGN KEY (created_by) REFERENCES solvetax.employees(emp_id),
	CONSTRAINT gst_registration_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES solvetax.customers(customer_id),
	CONSTRAINT gst_registration_rm_id_fkey FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id)
);




-- solvetax.gst_registration_config definition

-- Drop table

-- DROP TABLE solvetax.gst_registration_config;

CREATE TABLE solvetax.gst_registration_config (
	id bigserial NOT NULL,
	config_type varchar(50) NOT NULL,
	value varchar(50) NOT NULL,
	display_name varchar(100) NOT NULL,
	description text NULL,
	is_active bool DEFAULT true NULL,
	sort_order int4 DEFAULT 0 NULL,
	CONSTRAINT gst_registration_config_pkey PRIMARY KEY (id)
);

1	registration_type	NORMAL	Normal	Normal GST registration type	true	1
2	registration_type	COMPOSITION	Composition	Composition GST registration type	true	2
3	ownership_category	PROPRIETARY	Proprietary	Proprietary ownership	true	1
4	ownership_category	PARTNERSHIP_FIRM	Partnership Firm	Partnership firm ownership	true	2
5	ownership_category	COMPANY	Company	Company ownership	true	3
6	turnover_details	LESS_THAN_2CR	Less than 2 Cr	Turnover less than 2 crore	true	1
7	turnover_details	LESS_THAN_5CR	Less than 5 Cr	Turnover less than 5 crore	true	2
8	turnover_details	MORE_THAN_5CR	More than 5 Cr	Turnover more than 5 crore	true	3

-- solvetax.password_reset_otps definition

-- Drop table

-- DROP TABLE solvetax.password_reset_otps;

CREATE TABLE solvetax.password_reset_otps (
	id serial4 NOT NULL,
	emp_id int4 NOT NULL,
	otp_code varchar(10) NOT NULL,
	expires_at timestamp NOT NULL,
	is_used bool DEFAULT false NULL,
	created_at timestamp DEFAULT now() NULL,
	CONSTRAINT password_reset_otps_pkey PRIMARY KEY (id)
);


-- solvetax.password_reset_otps foreign keys

ALTER TABLE solvetax.password_reset_otps ADD CONSTRAINT password_reset_otps_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


-- solvetax.session_audit_log definition

-- Drop table

-- DROP TABLE solvetax.session_audit_log;


CREATE TABLE solvetax.session_audit_log (
	id bigserial NOT NULL,
	emp_id int8 NOT NULL,
	session_token varchar(255) NOT NULL,
	"action" varchar(50) NOT NULL,
	action_time timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
	action_details text NULL,
	ip_address varchar(50) NULL,
	CONSTRAINT session_audit_log_pkey PRIMARY KEY (id),
	CONSTRAINT session_audit_log_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id)
);





-- solvetax.session_token definition

-- Drop table

-- DROP TABLE solvetax.session_token;


CREATE TABLE solvetax.session_token (
	id bigserial NOT NULL,
	emp_id int8 NOT NULL,
	session_token varchar(255) NOT NULL,
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	expires_at timestamp NULL,
	device_info text NULL,
	ip_address varchar(50) NULL,
	CONSTRAINT session_token_pkey PRIMARY KEY (id),
	CONSTRAINT session_token_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id)
);



CREATE TABLE solvetax.registration_config (
    id BIGSERIAL PRIMARY KEY,
    ownership_category VARCHAR(50) NOT NULL, -- 'PROPRIETOR', 'PARTNERSHIP_FIRM', 'COMPANY'
    config_type VARCHAR(50) NOT NULL,        -- 'DOCUMENT_TYPE', 'ROLE', etc.
    value VARCHAR(100) NOT NULL,             -- e.g., 'PAN', 'AADHAAR', 'PHOTO', 'PARTNERSHIP_DEED'
    display_name VARCHAR(100) NOT NULL,      -- For dropdowns/UI
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0
);


-- Roles
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('PROPRIETOR', 'ROLE', 'PROPRIETOR', 'Proprietor', 'Individual business owner', 1);

-- Document Types
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('PROPRIETOR', 'DOCUMENT_TYPE', 'PAN', 'PAN Card', 'PAN Card of Proprietor', 1),
('PROPRIETOR', 'DOCUMENT_TYPE', 'AADHAAR', 'Aadhar Card', 'Aadhar Card of Proprietor', 2),
('PROPRIETOR', 'DOCUMENT_TYPE', 'PHOTO', 'Passport Size Photo', 'Photo of Proprietor', 3),
('PROPRIETOR', 'DOCUMENT_TYPE', 'PROPERTY_TAX_RECEIPT', 'Property Tax Receipt', 'Registered Office Address Proof', 4),
('PROPRIETOR', 'DOCUMENT_TYPE', 'RENTAL_AGREEMENT', 'Rental Agreement', 'Registered Office Address Proof', 5),
('PROPRIETOR', 'DOCUMENT_TYPE', 'NOC', 'No Objection Certificate', 'Registered Office Address Proof', 6),
('PROPRIETOR', 'DOCUMENT_TYPE', 'CANCELLED_CHEQUE', 'Cancelled Cheque', 'Bank Account Proof', 7),
('PROPRIETOR', 'DOCUMENT_TYPE', 'PASSBOOK', 'Front Page of Passbook', 'Bank Account Proof', 8),
('PROPRIETOR', 'DOCUMENT_TYPE', 'BANK_STATEMENT', 'Latest Bank Statement', 'Bank Account Proof', 9);

-- Roles
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('PARTNERSHIP_FIRM', 'ROLE', 'PARTNER', 'Partner', 'Partner in the firm', 1);

-- Document Types
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'PAN', 'PAN Card', 'PAN Card of Partner', 1),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'AADHAAR', 'Aadhar Card', 'Aadhar Card of Partner', 2),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'PHOTO', 'Passport Size Photo', 'Photo of Partner', 3),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'PROPERTY_TAX_RECEIPT', 'Property Tax Receipt', 'Registered Office Address Proof', 4),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'RENTAL_AGREEMENT', 'Rental Agreement', 'Registered Office Address Proof', 5),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'NOC', 'No Objection Certificate', 'Registered Office Address Proof', 6),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'CANCELLED_CHEQUE', 'Cancelled Cheque', 'Bank Account Proof', 7),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'PASSBOOK', 'Front Page of Passbook', 'Bank Account Proof', 8),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'BANK_STATEMENT', 'Latest Bank Statement', 'Bank Account Proof', 9),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'PARTNERSHIP_DEED', 'Partnership Deed & Registration Certificate', 'Firm Document', 10),
('PARTNERSHIP_FIRM', 'DOCUMENT_TYPE', 'AUTHORISATION_LETTER', 'Authorisation Letter', 'Firm Document', 11);

-- Roles
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('COMPANY', 'ROLE', 'DIRECTOR', 'Director', 'Director in the company', 1);

-- Document Types
INSERT INTO solvetax.registration_config (ownership_category, config_type, value, display_name, description, sort_order) VALUES
('COMPANY', 'DOCUMENT_TYPE', 'PAN', 'PAN Card', 'PAN Card of Director', 1),
('COMPANY', 'DOCUMENT_TYPE', 'AADHAAR', 'Aadhar Card', 'Aadhar Card of Director', 2),
('COMPANY', 'DOCUMENT_TYPE', 'PHOTO', 'Passport Size Photo', 'Photo of Director', 3),
('COMPANY', 'DOCUMENT_TYPE', 'PROPERTY_TAX_RECEIPT', 'Property Tax Receipt', 'Registered Office Address Proof', 4),
('COMPANY', 'DOCUMENT_TYPE', 'RENTAL_AGREEMENT', 'Rental Agreement', 'Registered Office Address Proof', 5),
('COMPANY', 'DOCUMENT_TYPE', 'NOC', 'No Objection Certificate', 'Registered Office Address Proof', 6),
('COMPANY', 'DOCUMENT_TYPE', 'CANCELLED_CHEQUE', 'Cancelled Cheque', 'Bank Account Proof', 7),
('COMPANY', 'DOCUMENT_TYPE', 'PASSBOOK', 'Front Page of Passbook', 'Bank Account Proof', 8),
('COMPANY', 'DOCUMENT_TYPE', 'BANK_STATEMENT', 'Latest Bank Statement', 'Bank Account Proof', 9),
('COMPANY', 'DOCUMENT_TYPE', 'MOA', 'Memorandum of Association (MOA)', 'Company Document', 10),
('COMPANY', 'DOCUMENT_TYPE', 'COI', 'Certificate of Incorporation (COI)', 'Company Document', 11),
('COMPANY', 'DOCUMENT_TYPE', 'AUTHORISATION_LETTER', 'Authorisation Letter', 'Company Document', 12);


-- solvetax.registration_persons definition

-- Drop table

-- DROP TABLE solvetax.registration_persons;


CREATE TABLE solvetax.registration_persons (
	person_id bigserial NOT NULL,
	customer_id int8 NULL,
	gstin varchar(15) NOT NULL,
	full_name varchar(150) NOT NULL,
	"role" varchar(50) NOT NULL,
	pan varchar(10) NULL,
	aadhaar varchar(20) NULL,
	email varchar(150) NULL,
	mobile varchar(20) NULL,
	is_primary_customer bool DEFAULT false NULL,
	CONSTRAINT registration_persons_pkey PRIMARY KEY (person_id),
	CONSTRAINT registration_persons_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES solvetax.customers(customer_id) ON DELETE CASCADE,
	CONSTRAINT registration_persons_gstin_fkey FOREIGN KEY (gstin) REFERENCES solvetax.gst_registration(gstin) ON DELETE CASCADE
);

-- solvetax.registration_documents definition

-- Drop table

-- DROP TABLE solvetax.registration_documents;


CREATE TABLE solvetax.registration_documents (
	document_id bigserial NOT NULL,
	gstin varchar(15) NOT NULL,
	person_id int8 NULL,
	document_type varchar(50) NOT NULL,
	document_url text NOT NULL,
	ownership_category varchar(50) NULL,
	verified bool DEFAULT false NULL,
	verified_by int8 NULL,
	verified_at timestamp NULL,
	uploaded_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	mobile varchar(20) NULL,
	CONSTRAINT registration_documents_pkey PRIMARY KEY (document_id),
	CONSTRAINT registration_documents_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES solvetax.employees(emp_id),
	CONSTRAINT registration_documents_gstin_fkey FOREIGN KEY (gstin) REFERENCES solvetax.gst_registration(gstin) ON DELETE CASCADE,
	CONSTRAINT registration_documents_person_id_fkey FOREIGN KEY (person_id) REFERENCES solvetax.registration_persons(person_id)
);


CREATE TABLE solvetax.company_registration (
    id bigserial PRIMARY KEY,

    customer_id int8 NOT NULL,

	cin VARCHAR(21) NOT NULL,
	username varchar(100) NOT NULL,
	"password" text NOT NULL,
	pan varchar(10) NOT NULL,

    company_type varchar(50) NOT NULL,
    -- PRIVATE_LIMITED / LLP/PUBLIC_LIMITED
	business_type varchar(50) NULL,
	business_description text NULL,


    registered_email varchar(150) NOT NULL,
    registered_mobile varchar(20) NOT NULL,

    registered_office_address text NOT NULL,
    state varchar(100) NOT NULL,
    city varchar(100) NOT NULL,

    registration_status varchar(50) DEFAULT 'DRAFT',

    created_by int8 NULL,
	rm_id int8 NULL,
	is_filing_needed bool DEFAULT true NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP,

    is_active bool DEFAULT true,

    CONSTRAINT company_registration_customer_fk
        FOREIGN KEY (customer_id)
        REFERENCES solvetax.customers(customer_id),

    CONSTRAINT company_registration_created_by_fk
        FOREIGN KEY (created_by)
        REFERENCES solvetax.employees(emp_id),

    CONSTRAINT company_registration_rm_fk
        FOREIGN KEY (rm_id)
        REFERENCES solvetax.employees(emp_id)
);


CREATE TABLE solvetax.company_registration_persons (
    person_id bigserial PRIMARY KEY,

    cin varchar(21) NOT NULL,

    role varchar(50) NOT NULL,
    -- DIRECTOR / PARTNER / AUTH_SIGNATORY

    full_name varchar(150) NOT NULL,

    pan varchar(10) NOT NULL,
    aadhaar varchar(20) NOT NULL,

    voter_id varchar(20) NULL,
    passport varchar(20) NULL,
    driving_license varchar(20) NULL,

    email varchar(150) NOT NULL,
    mobile varchar(20) NOT NULL,

	dsc_validity_date date NULL,
	DIR_KYC_due_date date NULL,
	DIR_KYC_done_date date NULL,

	DIN_status varchar(50) DEFAULT 'active',
    occupation varchar(50) NOT NULL,
    area_of_occupation varchar(100) NOT NULL,

    education_qualification varchar(100) NOT NULL,

    present_residential_address text NOT NULL,
    address_duration_years int4 NOT NULL,

    is_active bool DEFAULT true,

    CONSTRAINT company_person_company_fk
        FOREIGN KEY (cin)
        REFERENCES solvetax.company_registration(cin)
        ON DELETE CASCADE
);


CREATE TABLE solvetax.company_registration_documents (
    document_id bigserial PRIMARY KEY,

    cin varchar(21) NOT NULL,
    person_id int8 NULL,

    document_type varchar(50) NOT NULL,
    -- PROPOSED_NAME
    -- AADHAAR / PAN / PHOTO
    -- BANK_STATEMENT / ELECTRICITY_BILL
    -- RENTAL_AGREEMENT / NOC
    -- AUTHORIZATION_LETTER

    document_url text NOT NULL,

    verified bool DEFAULT false,
    verified_by int8 NULL,
    verified_at timestamp NULL,

    uploaded_at timestamp DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT company_doc_company_fk
        FOREIGN KEY (cin)
        REFERENCES solvetax.company_registration(cin)
        ON DELETE CASCADE,

    CONSTRAINT company_doc_person_fk
        FOREIGN KEY (person_id)
        REFERENCES solvetax.company_registration_persons(person_id),

    CONSTRAINT company_doc_verified_by_fk
        FOREIGN KEY (verified_by)
        REFERENCES solvetax.employees(emp_id)
);

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


INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'ROLE', 'DIRECTOR', 'Director', 'Director of the company', 'PERSON', true, 1),
('LLP', 'ROLE', 'PARTNER', 'Partner', 'Partner of the LLP', 'PERSON', true, 1);


INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'INPUT', 'PROPOSED_NAME_1', 'Proposed Company Name 1', 'First proposed company name', 'COMPANY', false, 1),
('PRIVATE_LIMITED', 'INPUT', 'PROPOSED_NAME_2', 'Proposed Company Name 2', 'Second proposed company name', 'COMPANY', false, 2),
('PRIVATE_LIMITED', 'INPUT', 'BUSINESS_OBJECTIVES', 'Business Objectives', 'Main business activities', 'COMPANY', false, 3),
('PRIVATE_LIMITED', 'INPUT', 'COMPANY_EMAIL', 'Company Email', 'Official company email', 'COMPANY', false, 4),
('PRIVATE_LIMITED', 'INPUT', 'COMPANY_MOBILE', 'Company Mobile Number', 'Official company mobile', 'COMPANY', false, 5),
('PRIVATE_LIMITED', 'INPUT', 'REGISTERED_OFFICE_ADDRESS', 'Registered Office Address', 'Office address of the company', 'COMPANY', false, 6);

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


INSERT INTO solvetax.company_registration_config
(company_type, config_type, value, display_name, description, input_scope, is_multiple, sort_order)
VALUES
('PRIVATE_LIMITED', 'DOCUMENT', 'ELECTRICITY_BILL', 'Electricity Bill', 'Registered office address proof', 'COMPANY', false, 30),
('PRIVATE_LIMITED', 'DOCUMENT', 'RENTAL_AGREEMENT', 'Rental Agreement', 'Office rental agreement', 'COMPANY', false, 31),
('PRIVATE_LIMITED', 'DOCUMENT', 'NOC', 'No Objection Certificate', 'NOC from property owner', 'COMPANY', false, 32);


-- -------------------------------------------------------------
-- SERVICE / REGISTRATION PAYMENTS
-- -------------------------------------------------------------
CREATE TABLE solvetax.registration_payments (

    id BIGSERIAL PRIMARY KEY,

    -- Business Reference (Shown to customer)
    transaction_id VARCHAR(100) NOT NULL UNIQUE,
    -- Example: REG-2026-0001

    customer_id BIGINT NOT NULL,
    -- FK -> solvetax.customers(customer_id)

    entity_id BIGINT NOT NULL,
    -- ID of GST registration / Income tax / Company etc.

    entity_type VARCHAR(50) NOT NULL,
    -- GST_REGISTRATION
    -- INCOME_TAX
    -- COMPANY_REGISTRATION
    -- TRADEMARK
    -- OTHER_SERVICE

    -- Amount Section
    amount NUMERIC(12,2) NOT NULL,
    -- Base service amount (Example: 1500.00)

    discount NUMERIC(12,2) DEFAULT 0,
    -- Example: 200.00

    net_amount NUMERIC(12,2) GENERATED ALWAYS AS (amount - discount) STORED,
    -- Final payable amount (1300.00)

    paid_amount NUMERIC(12,2) DEFAULT 0,
    -- Amount received so far

    payment_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING
    -- PARTIAL_PAID
    -- PAID
    -- FAILED
    -- CANCELLED
    -- REFUNDED

    payment_mode VARCHAR(30),
    -- CASH | UPI | BANK_TRANSFER | CARD | GATEWAY

    payment_date TIMESTAMPTZ,
    -- Set when fully paid

    remarks TEXT,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    CONSTRAINT fk_registration_payments_customer
        FOREIGN KEY (customer_id)
        REFERENCES solvetax.customers(customer_id),

    CONSTRAINT chk_amount_positive CHECK (amount >= 0),
    CONSTRAINT chk_discount_positive CHECK (discount >= 0),
    CONSTRAINT chk_paid_amount_positive CHECK (paid_amount >= 0)

);


-- -------------------------------------------------------------
-- REGISTRATION / SERVICE PAYMENTS
-- -------------------------------------------------------------
CREATE TABLE solvetax.registration_payments (

    id BIGSERIAL PRIMARY KEY,

    -- Business Reference (can be generated later)
    transaction_id VARCHAR(100) UNIQUE,
    -- Example: REG-2026-0001

    customer_id BIGINT NOT NULL,
    -- FK -> solvetax.customers(customer_id)

    entity_id BIGINT NOT NULL,
    -- Example: GST registration ID / Income tax ID

    entity_type VARCHAR(50) NOT NULL,
    -- GST_REGISTRATION
    -- INCOME_TAX
    -- COMPANY_REGISTRATION
    -- TRADEMARK
    -- OTHER_SERVICE

    -- Amount Section
    amount NUMERIC(12,2) NOT NULL,
    -- Base service amount (Example: 1500.00)

    discount NUMERIC(12,2) DEFAULT 0,
    -- Example: 200.00

    net_amount NUMERIC(12,2) NOT NULL,
    -- Calculated by trigger (amount - discount)

    paid_amount NUMERIC(12,2) DEFAULT 0,
    -- Amount received so far

    payment_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    -- PENDING
    -- PARTIAL_PAID
    -- PAID
    -- FAILED
    -- CANCELLED
    -- REFUNDED

    payment_mode VARCHAR(30),
    -- CASH | UPI | BANK_TRANSFER | CARD | GATEWAY

    payment_date TIMESTAMPTZ,
    -- Last payment activity timestamp

    remarks TEXT,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,

    -- Foreign Key
    CONSTRAINT fk_registration_payments_customer
        FOREIGN KEY (customer_id)
        REFERENCES solvetax.customers(customer_id),

    -- Safety Checks
    CONSTRAINT chk_amount_positive CHECK (amount >= 0),
    CONSTRAINT chk_discount_positive CHECK (discount >= 0),
    CONSTRAINT chk_paid_amount_positive CHECK (paid_amount >= 0)

);

CREATE OR REPLACE FUNCTION solvetax.fn_registration_payment_logic()
RETURNS TRIGGER AS $$
BEGIN

    -- Auto calculate net amount
    NEW.net_amount := NEW.amount - COALESCE(NEW.discount, 0);

    -- Prevent overpayment (optional but recommended)
    IF NEW.paid_amount > NEW.net_amount THEN
        RAISE EXCEPTION 'Paid amount cannot exceed net amount';
    END IF;

    -- Status Logic
    IF NEW.paid_amount IS NULL OR NEW.paid_amount = 0 THEN
        NEW.payment_status := 'PENDING';
        NEW.payment_date := NULL;

    ELSIF NEW.paid_amount > 0 AND NEW.paid_amount < NEW.net_amount THEN
        NEW.payment_status := 'PARTIAL_PAID';
        NEW.payment_date := NOW();

    ELSIF NEW.paid_amount >= NEW.net_amount THEN
        NEW.payment_status := 'PAID';
        NEW.payment_date := NOW();
    END IF;

    NEW.updated_at := NOW();

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_registration_payment_logic
BEFORE INSERT OR UPDATE
ON solvetax.registration_payments
FOR EACH ROW
EXECUTE FUNCTION solvetax.fn_registration_payment_logic();