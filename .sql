
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
	is_active bool DEFAULT true NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	CONSTRAINT customers_pkey PRIMARY KEY (customer_id)
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
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	is_filing_needed bool DEFAULT true NULL,
	mobile varchar(20) NULL,
	CONSTRAINT gst_registration_gstin_key UNIQUE (gstin),
	CONSTRAINT gst_registration_pkey PRIMARY KEY (id),
	CONSTRAINT gst_registration_username_key UNIQUE (username)
);


-- solvetax.gst_registration foreign keys

ALTER TABLE solvetax.gst_registration ADD CONSTRAINT gst_registration_created_by_fkey FOREIGN KEY (created_by) REFERENCES solvetax.employees(emp_id);
ALTER TABLE solvetax.gst_registration ADD CONSTRAINT gst_registration_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES solvetax.customers(customer_id);


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
	CONSTRAINT session_audit_log_pkey PRIMARY KEY (id)
);


-- solvetax.session_audit_log foreign keys

ALTER TABLE solvetax.session_audit_log ADD CONSTRAINT session_audit_log_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


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
	CONSTRAINT session_token_pkey PRIMARY KEY (id)
);


-- solvetax.session_token foreign keys

ALTER TABLE solvetax.session_token ADD CONSTRAINT session_token_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


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