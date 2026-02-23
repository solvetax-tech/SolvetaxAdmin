solvetax	gst_registration	chk_gstin_pan_match	CHECK	CHECK ((upper(TRIM(BOTH FROM pan)) = SUBSTRING(upper(TRIM(BOTH FROM gstin)) FROM 3 FOR 10)))
solvetax	gst_registration	chk_pan_format	CHECK	CHECK (((pan IS NULL) OR ((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text)))
solvetax	gst_registration	chk_pan_format	CHECK	CHECK (((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text))
solvetax	gst_registration	chk_gst_format	CHECK	CHECK (((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))
solvetax	gst_registration	chk_mobile_format	CHECK	CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text)))
solvetax	gst_registration	chk_secondary_email_format	CHECK	CHECK (((secondary_email IS NULL) OR ((secondary_email)::text ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'::text)))
solvetax	gst_registration	chk_approved_logic	CHECK	CHECK (((((registration_status)::text = 'APPROVED'::text) AND (approved_at IS NOT NULL)) OR (((registration_status)::text <> 'APPROVED'::text) AND (approved_at IS NULL))))
solvetax	gst_registration	gst_registration_created_by_fkey	FOREIGN KEY	FOREIGN KEY (created_by) REFERENCES employees(emp_id)
solvetax	gst_registration	gst_registration_customer_id_fkey	FOREIGN KEY	FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
solvetax	gst_registration	gst_registration_rm_id_fkey	FOREIGN KEY	FOREIGN KEY (rm_id) REFERENCES employees(emp_id)
solvetax	gst_registration	gst_registration_pkey	PRIMARY KEY	PRIMARY KEY (id)
solvetax	gst_registration	gst_registration_gstin_key	UNIQUE	UNIQUE (gstin)
solvetax	registration_documents	chk_doc_gst_format	CHECK	CHECK (((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))
solvetax	registration_documents	chk_doc_mobile_format	CHECK	CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text)))
solvetax	registration_documents	chk_verified_by_logic	CHECK	CHECK ((((verified = true) AND (verified_by IS NOT NULL)) OR (verified = false)))
solvetax	registration_documents	chk_verified_timestamp	CHECK	CHECK ((((verified = true) AND (verified_at IS NOT NULL)) OR (verified = false)))
solvetax	registration_documents	registration_documents_verified_by_fkey	FOREIGN KEY	FOREIGN KEY (verified_by) REFERENCES employees(emp_id)
solvetax	registration_documents	registration_documents_gstin_fkey	FOREIGN KEY	FOREIGN KEY (gstin) REFERENCES gst_registration(gstin) ON DELETE CASCADE
solvetax	registration_documents	registration_documents_person_id_fkey	FOREIGN KEY	FOREIGN KEY (person_id) REFERENCES registration_persons(person_id) ON DELETE CASCADE
solvetax	registration_documents	registration_documents_pkey	PRIMARY KEY	PRIMARY KEY (document_id)
solvetax	registration_persons	chk_person_aadhaar_format	CHECK	CHECK (((aadhaar IS NULL) OR ((aadhaar)::text ~ '^[0-9]{12}$'::text)))
solvetax	registration_persons	chk_pan_format	CHECK	CHECK (((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text))
solvetax	registration_persons	chk_person_mobile_format	CHECK	CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text)))
solvetax	registration_persons	chk_pan_format	CHECK	CHECK (((pan IS NULL) OR ((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text)))
solvetax	registration_persons	chk_person_gst_format	CHECK	CHECK (((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))
solvetax	registration_persons	registration_persons_gstin_fkey	FOREIGN KEY	FOREIGN KEY (gstin) REFERENCES gst_registration(gstin) ON DELETE CASCADE
solvetax	registration_persons	registration_persons_customer_id_fkey	FOREIGN KEY	FOREIGN KEY (customer_id) REFERENCES customers(customer_id) ON DELETE CASCADE
solvetax	registration_persons	registration_persons_pkey	PRIMARY KEY	PRIMARY KEY (person_id)


SELECT
    tc.table_schema,
    tc.table_name,
    tc.constraint_name,
    tc.constraint_type,
    pg_get_constraintdef(c.oid) AS definition
FROM information_schema.table_constraints tc
JOIN pg_constraint c
    ON c.conname = tc.constraint_name
WHERE tc.table_schema = 'solvetax'
  AND tc.table_name IN (
        'gst_registration',
        'registration_documents',
        'registration_persons'
  )
ORDER BY tc.table_name, tc.constraint_type;