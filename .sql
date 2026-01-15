CREATE TABLE gst_documents (
    document_id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    customer_id BIGINT NOT NULL
        REFERENCES customers(customer_id),
    gstin BIGINT NOT NULL
        REFERENCES gst_registration(gstin)
        ON DELETE CASCADE,
    ownership_category VARCHAR(50)
    CHECK(ownership_category in ('PROPRIETARY','PARTNERSHIP_FIRM','COMPANY')),
    document_type VARCHAR(50)
        CHECK (document_type IN (
            'PAN','AADHAAR','PHOTO',
            'RENT_AGREEMENT','NOC',
            'BANK_PROOF','PARTNERSHIP_DEED',
            'MOA','AOA','COI','ELECTICITY_BILL',
            'MUNICIPAL_TAX_RECIEPT','AUTHORISATION_LETTER',
        )),
    document_url TEXT NOT NULL,
    verified BOOLEAN DEFAULT FALSE,
    verified_by BIGINT REFERENCES users(user_id),
    verified_at TIMESTAMP,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
	business_image text NULL,
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
	applied_date date NULL,
	approval_date date NULL,
	is_rcm_applicable bool DEFAULT false NULL,
	turnover_details varchar(50) DEFAULT 'LESS_THAN_2CR'::character varying NULL,
	created_by int8 NULL,
	created_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
	updated_at timestamp DEFAULT CURRENT_TIMESTAMP NULL,
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

