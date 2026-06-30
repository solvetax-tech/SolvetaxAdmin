-- Remove redundant customer_id from gst_registration_persons.
-- Person rows are scoped by gst_registration_id; customer (if any) lives on gst_registration.

DROP INDEX IF EXISTS solvetax.idx_reg_person_customer;

ALTER TABLE solvetax.gst_registration_persons
    DROP COLUMN IF EXISTS customer_id;
