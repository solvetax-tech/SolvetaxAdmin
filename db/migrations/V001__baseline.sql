--
-- PostgreSQL database dump
--


-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: solvetax; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS solvetax;


--
-- Name: fn_crm_leads_set_assigned_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_crm_leads_set_assigned_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    -- INSERT logic

    IF TG_OP = 'INSERT' THEN

        IF NEW.rm_id IS NOT NULL AND NEW.rm_assigned_at IS NULL THEN

            NEW.rm_assigned_at := now();

        END IF;



        IF NEW.op_id IS NOT NULL AND NEW.op_assigned_at IS NULL THEN

            NEW.op_assigned_at := now();

        END IF;



        RETURN NEW;

    END IF;



    -- UPDATE logic (only when ids change)

    IF NEW.rm_id IS DISTINCT FROM OLD.rm_id THEN

        IF NEW.rm_id IS NULL THEN

            NEW.rm_assigned_at := NULL;   -- unassigned

        ELSE

            NEW.rm_assigned_at := now();  -- newly assigned / reassigned

        END IF;

    END IF;



    IF NEW.op_id IS DISTINCT FROM OLD.op_id THEN

        IF NEW.op_id IS NULL THEN

            NEW.op_assigned_at := NULL;   -- unassigned

        ELSE

            NEW.op_assigned_at := now();  -- newly assigned / reassigned

        END IF;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_crm_leads_touch_dial_on_milestone_stage(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_crm_leads_touch_dial_on_milestone_stage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  IF TG_OP = 'INSERT' THEN

    IF NEW.stage IN ('GST_REGISTRATION_DONE', 'ITR_DONE', 'SUBSCRIBED') THEN

      NEW.last_dailed_at := NOW();

      NEW.last_connected_at := NOW();

    END IF;

    RETURN NEW;

  END IF;



  IF TG_OP = 'UPDATE' THEN

    IF NEW.stage IS DISTINCT FROM OLD.stage

       AND NEW.stage IN ('GST_REGISTRATION_DONE', 'ITR_DONE', 'SUBSCRIBED') THEN

      NEW.last_dailed_at := NOW();

      NEW.last_connected_at := NOW();

    END IF;

    RETURN NEW;

  END IF;



  RETURN NEW;

END;

$$;


--
-- Name: fn_on_filing_completed(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_on_filing_completed() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.status = 'FILED'

       AND OLD.status IS DISTINCT FROM 'FILED'

       AND NEW.filed_at IS NULL THEN

        NEW.filed_at := NOW();

    END IF;

    RETURN NEW;

END;

$$;


--
-- Name: fn_payments_followup_completed_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_payments_followup_completed_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.followup_status IS NOT DISTINCT FROM 'COMPLETED' THEN

        IF TG_OP = 'INSERT' THEN

            NEW.completed_at := COALESCE(NEW.completed_at, NOW());

        ELSIF OLD.followup_status IS DISTINCT FROM 'COMPLETED' THEN

            NEW.completed_at := COALESCE(NEW.completed_at, NOW());

        END IF;

    ELSIF TG_OP = 'UPDATE' AND OLD.followup_status IS NOT DISTINCT FROM 'COMPLETED' THEN

        NEW.completed_at := NULL;

    END IF;

    RETURN NEW;

END;

$$;


--
-- Name: fn_propagate_gst_registration_status_to_filings(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_propagate_gst_registration_status_to_filings() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.registration_status IS DISTINCT FROM OLD.registration_status THEN

        UPDATE solvetax.gst_filings f

        SET gst_reg_status = NEW.registration_status,

            updated_at = NOW()

        WHERE f.gst_registration_id = NEW.id

          AND f.gst_registration_id IS NOT NULL

          AND f.gst_reg_status IS DISTINCT FROM NEW.registration_status;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_registration_payment_logic(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_registration_payment_logic() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

DECLARE

    total_paid numeric := 0;

BEGIN

    NEW.discount := COALESCE(NEW.discount, 0);

    NEW.paid_amount := COALESCE(NEW.paid_amount, 0);

    NEW.net_amount := NEW.amount - NEW.discount;



    IF NEW.net_amount < 0 THEN

        RAISE EXCEPTION 'Net amount cannot be negative';

    END IF;



    SELECT COALESCE(SUM(paid_amount), 0)

    INTO total_paid

    FROM solvetax.payments

    WHERE customer_id = NEW.customer_id

      AND entity_id = NEW.entity_id

      AND entity_type = NEW.entity_type

      AND is_active = TRUE

      AND payment_status <> 'CANCELLED'

      AND id <> NEW.id;



    total_paid := total_paid + NEW.paid_amount;



    IF total_paid > NEW.net_amount THEN

        RAISE EXCEPTION

            'Total payment %.2f exceeds payable amount %.2f',

            total_paid, NEW.net_amount;

    END IF;



    IF total_paid = NEW.net_amount THEN

        NEW.payment_status := 'PAID';

        NEW.payment_date := COALESCE(NEW.payment_date, NOW());

    ELSIF total_paid > 0 AND total_paid < NEW.net_amount THEN

        NEW.payment_status := 'PENDING';

        NEW.payment_date := COALESCE(NEW.payment_date, NOW());

    ELSE

        NEW.payment_status := 'PENDING';

        NEW.payment_date := NULL;

    END IF;



    NEW.updated_at := NOW();

    RETURN NEW;

END;

$$;


--
-- Name: fn_set_data_received_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_set_data_received_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.status = 'DATA_RECEIVED'

       AND OLD.status IS DISTINCT FROM 'DATA_RECEIVED' THEN

        NEW.data_received_at := NOW();

    END IF;

    RETURN NEW;

END;

$$;


--
-- Name: fn_set_filed_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_set_filed_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.status = 'FILED'

       AND OLD.status IS DISTINCT FROM 'FILED' THEN

        NEW.filed_at = NOW();

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_set_income_tax_filing_date(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_set_income_tax_filing_date() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    -- On INSERT: if FILED and filing_date missing, stamp NOW()

    IF TG_OP = 'INSERT' THEN

        IF NEW.filed_status = 'FILED' AND NEW.filing_date IS NULL THEN

            NEW.filing_date := NOW();

        END IF;

        IF NEW.filed_status = 'NOT_FILED' THEN

            NEW.filing_date := NULL;

        END IF;

        RETURN NEW;

    END IF;



    -- On UPDATE: transition logic

    IF TG_OP = 'UPDATE' THEN

        -- NOT_FILED -> FILED : stamp now when empty

        IF OLD.filed_status = 'NOT_FILED' AND NEW.filed_status = 'FILED' AND NEW.filing_date IS NULL THEN

            NEW.filing_date := NOW();

        END IF;



        -- FILED -> NOT_FILED : clear filing_date

        IF NEW.filed_status = 'NOT_FILED' THEN

            NEW.filing_date := NULL;

        END IF;



        RETURN NEW;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_set_updated_at_doc(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_set_updated_at_doc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    NEW.updated_at := NOW();

    RETURN NEW;

END;

$$;


--
-- Name: fn_set_verified_fields_doc(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_set_verified_fields_doc() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.verified = TRUE AND (OLD.verified IS DISTINCT FROM TRUE) THEN

        NEW.verified_at := NOW();

        IF NEW.verified_by IS NULL THEN

            NEW.verified_by := OLD.verified_by;

        END IF;

    END IF;



    IF NEW.verified = FALSE AND OLD.verified = TRUE THEN

        NEW.verified_at := NULL;

        NEW.verified_by := NULL;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_sync_crm_lead_from_gst_registration(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_sync_crm_lead_from_gst_registration() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

DECLARE

    v_lead_id   BIGINT;

    v_old_stage VARCHAR(40);

    v_new_stage VARCHAR(40);

    v_approved  BOOLEAN;

BEGIN

    v_approved := upper(trim(COALESCE(NEW.registration_status::text, ''))) = 'APPROVED';



    SELECT l.id, l.stage

      INTO v_lead_id, v_old_stage

      FROM solvetax.crm_leads l

     WHERE l.entity_type = 'GST_REGISTRATION'

       AND l.entity_id = NEW.id

       AND l.is_active = TRUE

     ORDER BY l.id DESC

     LIMIT 1

     FOR UPDATE;



    IF v_lead_id IS NULL THEN

        RETURN NEW;

    END IF;



    -- Only SUBSCRIBED is a true end stage; NOT_INTERESTED may still move forward.

    IF v_old_stage = 'SUBSCRIBED' THEN

        RETURN NEW;

    END IF;



    IF v_approved THEN

        v_new_stage := 'GST_REGISTRATION_DONE';

    ELSE

        v_new_stage := v_old_stage;

    END IF;



    UPDATE solvetax.crm_leads l

       SET mobile = NEW.mobile,

           entity_id = NEW.id,

           entity_type = 'GST_REGISTRATION',

           is_active = NEW.is_active,

           stage = CASE

                     WHEN l.stage = 'SUBSCRIBED' THEN l.stage

                     ELSE v_new_stage

                   END,

           updated_at = NOW()

     WHERE l.id = v_lead_id

     RETURNING l.stage INTO v_new_stage;



    IF v_old_stage IS DISTINCT FROM v_new_stage THEN

        INSERT INTO solvetax.crm_activities (

            lead_id,

            entity_type,

            activity_type,

            old_stage,

            new_stage,

            remarks,

            performed_by,

            performed_at,

            created_at

        )

        VALUES (

            v_lead_id,

            'GST_REGISTRATION',

            'SYSTEM',

            v_old_stage,

            v_new_stage,

            'Auto stage sync from GST registration update',

            NULL,

            NOW(),

            NOW()

        );

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_sync_gst_reg_status_to_filings(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_sync_gst_reg_status_to_filings() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.gst_registration_id IS NOT NULL THEN

        SELECT g.registration_status

        INTO NEW.gst_reg_status

        FROM solvetax.gst_registration g

        WHERE g.id = NEW.gst_registration_id;

    ELSE

        NEW.gst_reg_status := NULL;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: fn_update_parent_filing_status(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_update_parent_filing_status() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    RETURN COALESCE(NEW, OLD);

END;

$$;


--
-- Name: fn_update_remaining_amount(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.fn_update_remaining_amount() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    NEW.remaining_amount := NEW.net_amount - COALESCE(NEW.paid_amount, 0);



    IF NEW.remaining_amount < 0 THEN

        RAISE EXCEPTION

            'Remaining amount cannot be negative. Paid amount exceeds net amount.';

    END IF;



    IF NEW.remaining_amount = 0 AND NEW.payment_status <> 'PAID' THEN

        NEW.payment_status := 'PAID';

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: normalize_gst_fields(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.normalize_gst_fields() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.pan IS NOT NULL THEN

        NEW.pan := UPPER(TRIM(NEW.pan));

    END IF;



    IF NEW.gstin IS NOT NULL THEN

        NEW.gstin := UPPER(TRIM(NEW.gstin));

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: set_approved_timestamp(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.set_approved_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.registration_status = 'APPROVED'

       AND OLD.registration_status IS DISTINCT FROM 'APPROVED'

       AND NEW.approved_at IS NULL THEN

        NEW.approved_at := NOW();

    END IF;



    IF NEW.registration_status <> 'APPROVED' THEN

        NEW.approved_at := NULL;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: set_followup_completed_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.set_followup_completed_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  IF NEW.followup_status IS NOT NULL

     AND NEW.followup_status::text = 'COMPLETED'

     AND NEW.completed_at IS NULL THEN

    NEW.completed_at := now();

  END IF;

  RETURN NEW;

END;

$$;


--
-- Name: set_provided_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.set_provided_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  IF NEW.service_status IS NOT NULL

     AND NEW.service_status::text = 'PROVIDED'

     AND NEW.provided_at IS NULL THEN

    NEW.provided_at := now();

  END IF;

  RETURN NEW;

END;

$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  NEW.updated_at = now();

  RETURN NEW;

END;

$$;


--
-- Name: set_verified_timestamp(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.set_verified_timestamp() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.verified = TRUE

       AND OLD.verified IS DISTINCT FROM TRUE THEN

        NEW.verified_at := NOW();

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: sync_customer_services(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.sync_customer_services() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN



    -- Create ONLY generic services (no entity)

    INSERT INTO solvetax.customer_services

    (

        customer_id,

        service_id,

        service_status,

        rm_id,

        op_id,

        entity_type,

        entity_id

    )

    SELECT

        NEW.customer_id,

        s.id,

        CASE

            WHEN s.service_code = ANY(NEW.service_provided)

            THEN 'PROVIDED'

            ELSE 'PENDING'

        END,

        NEW.rm_id,

        NEW.op_id,

        NULL,

        NULL

    FROM solvetax.service_config s

    WHERE

        s.is_active = TRUE

        AND (

            s.service_code = ANY(NEW.service_required)

            OR

            s.service_code = ANY(NEW.service_provided)

        )



    ON CONFLICT DO NOTHING;



    RETURN NEW;



END;

$$;


--
-- Name: sync_gst_to_customer_service(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.sync_gst_to_customer_service() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.gstin IS NOT NULL

       AND NEW.username IS NOT NULL

       AND NEW.password IS NOT NULL THEN



        UPDATE solvetax.customer_services cs

        SET service_status = 'PROVIDED',

            provided_at = NOW()

        WHERE cs.customer_id = NEW.customer_id

          AND cs.entity_type = 'GST_REGISTRATION'

          AND cs.entity_id = NEW.id

          AND cs.status = 'ACTIVE';



        UPDATE solvetax.customers c

        SET service_provided = ARRAY(

            SELECT DISTINCT UNNEST(

                COALESCE(c.service_provided, ARRAY[]::text[])

                || ARRAY['GST_REGISTRATION']

            )

        )

        WHERE c.customer_id = NEW.customer_id;

    END IF;



    RETURN NEW;

END;

$$;


--
-- Name: touch_customer_services_updated_at(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.touch_customer_services_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  NEW.updated_at := now();

  RETURN NEW;

END;

$$;


--
-- Name: trg_gst_approved_to_crm_stage(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.trg_gst_approved_to_crm_stage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

  IF NEW.registration_status = 'APPROVED'

     AND NEW.is_active IS TRUE

     AND (TG_OP = 'INSERT' OR OLD.registration_status IS DISTINCT FROM NEW.registration_status)

  THEN

    UPDATE solvetax.crm_leads l

       SET stage = 'GST_REGISTRATION_DONE',

           updated_at = NOW()

     WHERE l.entity_type = 'GST_REGISTRATION'

       AND l.entity_id = NEW.id

       AND l.is_active IS TRUE

       AND l.stage IS DISTINCT FROM 'GST_REGISTRATION_DONE';

  END IF;

  RETURN NEW;

END;

$$;


--
-- Name: validate_customer_service_entity(); Type: FUNCTION; Schema: solvetax; Owner: -
--

CREATE FUNCTION solvetax.validate_customer_service_entity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$

BEGIN

    IF NEW.entity_type IS NOT NULL AND NEW.entity_id IS NULL THEN

        RAISE EXCEPTION 'entity_id required when entity_type is provided';

    END IF;



    IF NEW.entity_type IS NULL AND NEW.entity_id IS NOT NULL THEN

        RAISE EXCEPTION 'entity_type required when entity_id is provided';

    END IF;



    IF NEW.entity_type = '' THEN

        RAISE EXCEPTION 'entity_type cannot be empty';

    END IF;



    RETURN NEW;

END;

$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: customer_otp_verify; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.customer_otp_verify (
    id bigint NOT NULL,
    mobile character varying(10) NOT NULL,
    otp character varying(8) NOT NULL,
    is_verified boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone DEFAULT (now() + '00:02:00'::interval) NOT NULL,
    otp_purpose text DEFAULT 'customer'::text NOT NULL
);


--
-- Name: client_otp_verify_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.client_otp_verify_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: client_otp_verify_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.client_otp_verify_id_seq OWNED BY solvetax.customer_otp_verify.id;


--
-- Name: contact_support; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.contact_support (
    id bigint NOT NULL,
    your_name character varying(150) NOT NULL,
    phone_number character varying(10) NOT NULL,
    email_address character varying(150),
    service_required text[],
    is_service_provided boolean DEFAULT false NOT NULL,
    is_resolved boolean DEFAULT false NOT NULL,
    your_message text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    rm_id bigint,
    op_id bigint,
    referal_phone_number text[]
);


--
-- Name: contact_support_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.contact_support_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: contact_support_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.contact_support_id_seq OWNED BY solvetax.contact_support.id;


--
-- Name: crm_activities; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_activities (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    activity_type character varying(30) DEFAULT 'CALL'::character varying NOT NULL,
    call_type_code character varying(40),
    call_status_code character varying(50),
    old_stage character varying(40),
    new_stage character varying(40),
    followup_at timestamp with time zone,
    remarks text,
    performed_by bigint,
    performed_at timestamp with time zone DEFAULT now() NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_dailed_at timestamp with time zone,
    last_connected_at timestamp with time zone,
    entity_type character varying(64) NOT NULL
);


--
-- Name: crm_activities_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_activities_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_activities_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_activities_id_seq OWNED BY solvetax.crm_activities.id;


--
-- Name: crm_bulk_assign_logs; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_bulk_assign_logs (
    id bigint NOT NULL,
    scheduler_id bigint,
    run_type character varying(10) NOT NULL,
    entity_type character varying(64) NOT NULL,
    triggered_by bigint,
    candidates_matched integer DEFAULT 0 NOT NULL,
    total_assigned_rm integer DEFAULT 0 NOT NULL,
    total_assigned_op integer DEFAULT 0 NOT NULL,
    summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: crm_bulk_assign_logs_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_bulk_assign_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_bulk_assign_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_bulk_assign_logs_id_seq OWNED BY solvetax.crm_bulk_assign_logs.id;


--
-- Name: crm_bulk_assign_schedulers; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_bulk_assign_schedulers (
    id bigint NOT NULL,
    name character varying(120) NOT NULL,
    entity_type character varying(64) NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    filters jsonb DEFAULT '{}'::jsonb NOT NULL,
    assign_rm boolean DEFAULT false NOT NULL,
    assign_op boolean DEFAULT false NOT NULL,
    selected_rm_usernames jsonb DEFAULT '[]'::jsonb NOT NULL,
    selected_op_usernames jsonb DEFAULT '[]'::jsonb NOT NULL,
    per_employee_limit_rm integer,
    per_employee_limit_op integer,
    assign_unassigned_only boolean DEFAULT true NOT NULL,
    interval_minutes integer DEFAULT 5 NOT NULL,
    rr_state jsonb DEFAULT '{"OP": 0, "RM": 0}'::jsonb NOT NULL,
    last_run_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    created_by bigint,
    updated_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: crm_bulk_assign_schedulers_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_bulk_assign_schedulers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_bulk_assign_schedulers_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_bulk_assign_schedulers_id_seq OWNED BY solvetax.crm_bulk_assign_schedulers.id;


--
-- Name: crm_call_statuses; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_call_statuses (
    id bigint NOT NULL,
    code character varying(50) NOT NULL,
    name character varying(100) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    entity_type character varying(64) NOT NULL
);


--
-- Name: crm_call_statuses_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_call_statuses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_call_statuses_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_call_statuses_id_seq OWNED BY solvetax.crm_call_statuses.id;


--
-- Name: crm_call_types; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_call_types (
    id bigint NOT NULL,
    code character varying(40) NOT NULL,
    name character varying(80) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    entity_type character varying(64) NOT NULL
);


--
-- Name: crm_call_types_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_call_types_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_call_types_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_call_types_id_seq OWNED BY solvetax.crm_call_types.id;


--
-- Name: crm_lead_stages; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_lead_stages (
    code character varying(40) NOT NULL,
    name character varying(120) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    id bigint NOT NULL,
    entity_type character varying(64) DEFAULT 'GST_REGISTRATION'::character varying NOT NULL
);


--
-- Name: crm_lead_stages_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_lead_stages_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_lead_stages_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_lead_stages_id_seq OWNED BY solvetax.crm_lead_stages.id;


--
-- Name: crm_leads; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_leads (
    id bigint NOT NULL,
    mobile character varying(20) NOT NULL,
    full_name character varying(200),
    email character varying(255),
    entity_id bigint,
    entity_type character varying(64),
    preferred_language character varying(50),
    stage character varying(40) NOT NULL,
    call_attempted_count integer DEFAULT 0 NOT NULL,
    call_connected_count integer DEFAULT 0 NOT NULL,
    rm_id bigint,
    op_id bigint,
    remarks text,
    followup_at timestamp with time zone,
    follow_up_status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    completed_at timestamp with time zone,
    missed_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    last_dailed_at timestamp with time zone,
    last_connected_at timestamp with time zone,
    lead_type character varying(50),
    tag character varying(100),
    lead_source character varying(100),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    rm_assigned_at timestamp with time zone,
    op_assigned_at timestamp with time zone,
    ay character varying(20)
);


--
-- Name: crm_leads_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_leads_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_leads_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_leads_id_seq OWNED BY solvetax.crm_leads.id;


--
-- Name: crm_rm_op_mappings; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_rm_op_mappings (
    id bigint NOT NULL,
    rm_emp_id bigint NOT NULL,
    op_emp_id bigint NOT NULL,
    entity_type character varying(64),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: crm_rm_op_mappings_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_rm_op_mappings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_rm_op_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_rm_op_mappings_id_seq OWNED BY solvetax.crm_rm_op_mappings.id;


--
-- Name: crm_stage_status_mappings; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.crm_stage_status_mappings (
    id bigint NOT NULL,
    mapping_kind character varying(30) NOT NULL,
    stage character varying(40),
    pitch_type_code character varying(40) NOT NULL,
    call_status_code character varying(50),
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    entity_type character varying(64),
    CONSTRAINT chk_crm_ui_mapping_fields CHECK (((((mapping_kind)::text = 'STAGE_TO_PITCH'::text) AND (stage IS NOT NULL) AND (call_status_code IS NULL)) OR (((mapping_kind)::text = 'PITCH_TO_STATUS'::text) AND (call_status_code IS NOT NULL))))
);


--
-- Name: crm_ui_mappings_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.crm_ui_mappings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crm_ui_mappings_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.crm_ui_mappings_id_seq OWNED BY solvetax.crm_stage_status_mappings.id;


--
-- Name: customer_services; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.customer_services (
    id bigint NOT NULL,
    customer_id bigint,
    service_code character varying(50) NOT NULL,
    service_status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    provided_at timestamp with time zone,
    followup_at timestamp with time zone,
    followup_status character varying(20),
    followup_remarks text,
    completed_at timestamp with time zone,
    missed_at timestamp with time zone,
    is_active boolean DEFAULT true NOT NULL,
    rm_id bigint,
    op_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_followup_completed_fields CHECK ((((followup_status)::text <> 'COMPLETED'::text) OR (completed_at IS NOT NULL)))
);


--
-- Name: customer_services_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.customer_services_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: customer_services_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.customer_services_id_seq OWNED BY solvetax.customer_services.id;


--
-- Name: customers; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.customers (
    customer_id bigint NOT NULL,
    full_name character varying(150) NOT NULL,
    email character varying(150),
    mobile character varying(15) NOT NULL,
    service_required text[] DEFAULT ARRAY[]::text[],
    language character varying(50),
    business_name character varying(200),
    business_description text,
    business_image_url text,
    business_type character varying(50),
    state character varying(100),
    city character varying(100),
    remark text,
    rm_id bigint,
    op_id bigint,
    is_active boolean DEFAULT true,
    lead_source character varying(120),
    tag character varying(100),
    lead_type character varying(100),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    referral_phone_number character varying(15)
);


--
-- Name: customers_customer_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

ALTER TABLE solvetax.customers ALTER COLUMN customer_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME solvetax.customers_customer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: d_customer_session; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.d_customer_session (
    id bigint NOT NULL,
    mobile character varying(10) NOT NULL,
    entity_type character varying(40) DEFAULT 'UNKNOWN'::character varying NOT NULL,
    utm_source character varying(120),
    utm_medium character varying(120),
    utm_campaign character varying(200),
    utm_content character varying(200),
    capture_page_path character varying(1024),
    capture_page_url text,
    capture_page_query text,
    capture_referrer_url text,
    platform character varying(20),
    device_type character varying(20),
    device_model character varying(200),
    os_name character varying(64),
    os_version character varying(32),
    browser_name character varying(64),
    browser_version character varying(32),
    app_version character varying(64),
    environment character varying(32),
    release_tag character varying(64),
    user_agent text,
    viewport_width integer,
    viewport_height integer,
    screen_width integer,
    screen_height integer,
    language character varying(32),
    timezone_offset_min integer,
    lead_source character varying(120),
    ingestion_source character varying(40),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: d_customer_session_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.d_customer_session_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: d_customer_session_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.d_customer_session_id_seq OWNED BY solvetax.d_customer_session.id;


--
-- Name: document_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.document_config (
    id bigint NOT NULL,
    registration character varying(50) NOT NULL,
    ownership_category character varying(50),
    config_type character varying(50) NOT NULL,
    value character varying(100) NOT NULL,
    display_name character varying(200) NOT NULL,
    description text,
    is_mandatory boolean DEFAULT true,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: document_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.document_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.document_config_id_seq OWNED BY solvetax.document_config.id;


--
-- Name: employee_email_verifications; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.employee_email_verifications (
    id bigint NOT NULL,
    email text NOT NULL,
    emp_id bigint,
    otp_code character varying(6) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    is_used boolean DEFAULT false,
    is_verified boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now(),
    verified_at timestamp with time zone
);


--
-- Name: employee_email_verifications_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.employee_email_verifications_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: employee_email_verifications_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.employee_email_verifications_id_seq OWNED BY solvetax.employee_email_verifications.id;


--
-- Name: employee_roles; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.employee_roles (
    emp_id bigint NOT NULL,
    role_id bigint NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: employee_tasks; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.employee_tasks (
    id bigint NOT NULL,
    emp_id bigint NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    scheduled_at timestamp with time zone NOT NULL,
    status character varying(20) DEFAULT 'PENDING'::character varying NOT NULL,
    followup_at timestamp with time zone,
    followup_note text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    time_slots timestamp with time zone[] NOT NULL
);


--
-- Name: employee_tasks_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

ALTER TABLE solvetax.employee_tasks ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME solvetax.employee_tasks_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: employees; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.employees (
    emp_id bigint NOT NULL,
    username character varying(100) NOT NULL,
    email character varying(150) NOT NULL,
    password_hash text NOT NULL,
    first_name character varying(100),
    last_name character varying(100),
    phone_number character varying(20),
    role character varying(50) DEFAULT 'SE'::character varying,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    manager_emp_id bigint,
    employee_image_url text
);


--
-- Name: employees_emp_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

ALTER TABLE solvetax.employees ALTER COLUMN emp_id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME solvetax.employees_emp_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: entity_types; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.entity_types (
    id bigint NOT NULL,
    entity_name character varying(150) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    value character varying(150)
);


--
-- Name: entity_types_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.entity_types_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: entity_types_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.entity_types_id_seq OWNED BY solvetax.entity_types.id;


--
-- Name: features; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.features (
    id bigint NOT NULL,
    feature_code character varying(50) NOT NULL,
    feature_name character varying(100) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: features_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.features_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: features_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.features_id_seq OWNED BY solvetax.features.id;


--
-- Name: gst_filing_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_filing_config (
    id bigint NOT NULL,
    filing_type character varying(20) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text,
    filing_category character varying(20),
    is_active boolean DEFAULT true,
    sort_order integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: gst_filing_rule_engine; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_filing_rule_engine (
    id bigint NOT NULL,
    filing_type character varying(20) NOT NULL,
    display_name character varying(100) NOT NULL,
    filing_category character varying(20) NOT NULL,
    frequency character varying(20) NOT NULL,
    turnover_details character varying(50),
    return_type character varying(20),
    due_day integer NOT NULL,
    due_day_secondary integer,
    due_month_offset integer DEFAULT 1,
    reminder_days integer[] DEFAULT ARRAY[7, 3, 1],
    sort_order integer DEFAULT 0,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now(),
    taxpayer_type character varying(20) DEFAULT 'REGULAR'::character varying NOT NULL,
    turnover_limits character varying(50)
);


--
-- Name: gst_filing_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_filing_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_filing_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_filing_config_id_seq OWNED BY solvetax.gst_filing_rule_engine.id;


--
-- Name: gst_filing_config_id_seq1; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_filing_config_id_seq1
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_filing_config_id_seq1; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_filing_config_id_seq1 OWNED BY solvetax.gst_filing_config.id;


--
-- Name: gst_filing_return_details; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_filing_return_details (
    id bigint NOT NULL,
    gst_filing_id bigint NOT NULL,
    gstr1_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    gstr3b_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    gstr9_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    gstr9c_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    cmp08_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    gstr4_status character varying(15) DEFAULT 'NOT_FILED'::character varying,
    gstr1_due_date timestamp with time zone,
    gstr3b_due_date timestamp with time zone,
    gstr9_due_date timestamp with time zone,
    gstr9c_due_date timestamp with time zone,
    cmp08_due_date timestamp with time zone,
    gstr4_due_date timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    is_active boolean DEFAULT true,
    is_auto_generated boolean DEFAULT false NOT NULL,
    next_auto_generate_at timestamp with time zone,
    filing_frequency character varying(15),
    is_current boolean DEFAULT true NOT NULL,
    gstr1_followup_at timestamp with time zone,
    gstr3b_followup_at timestamp with time zone,
    gstr9_followup_at timestamp with time zone,
    gstr9c_followup_at timestamp with time zone,
    cmp08_followup_at timestamp with time zone,
    gstr4_followup_at timestamp with time zone
);


--
-- Name: COLUMN gst_filing_return_details.filing_frequency; Type: COMMENT; Schema: solvetax; Owner: -
--

COMMENT ON COLUMN solvetax.gst_filing_return_details.filing_frequency IS 'Return cadence for this row (MONTHLY, QUARTERLY, YEARLY); mirrors gst_filings.filing_frequency when set.';


--
-- Name: gst_filing_return_details_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_filing_return_details_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_filing_return_details_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_filing_return_details_id_seq OWNED BY solvetax.gst_filing_return_details.id;


--
-- Name: gst_filings; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_filings (
    id bigint NOT NULL,
    customer_id bigint,
    gst_registration_id bigint,
    filing_category character varying(20),
    filing_period character varying(20) NOT NULL,
    status character varying(20) DEFAULT 'DATA_PENDING'::character varying,
    filed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    service_id bigint,
    priority character varying(10) DEFAULT 'NORMAL'::character varying,
    remarks text,
    is_active boolean DEFAULT true,
    gstin character varying(15),
    rm_id bigint,
    op_id bigint,
    is_auto_enabled boolean DEFAULT true,
    taxpayer_type character varying(20),
    filing_frequency character varying(20) DEFAULT 'MONTHLY'::character varying,
    turnover_details character varying(50),
    state character varying(50),
    data_received_at timestamp with time zone,
    username character varying(100),
    password character varying(100),
    rent numeric(12,2),
    email_id character varying(150),
    rule14a boolean,
    business_name character varying(150),
    business_type character varying(50),
    business_description text,
    gst_reg_status character varying(20),
    language character varying(50),
    referral_id bigint,
    referral_entity character varying(100),
    CONSTRAINT chk_gst_reference CHECK (((gst_registration_id IS NOT NULL) OR (gstin IS NOT NULL)))
);


--
-- Name: gst_filings_documents; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_filings_documents (
    document_id bigint NOT NULL,
    gst_filing_id bigint NOT NULL,
    gstin character varying(15),
    document_type character varying(50) NOT NULL,
    document_url text NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    verified_by bigint,
    verified_at timestamp with time zone,
    remarks text,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    is_active boolean DEFAULT true,
    CONSTRAINT chk_doc_gstin_format CHECK (((gstin IS NULL) OR ((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))),
    CONSTRAINT chk_document_type_upper CHECK (((document_type)::text = upper((document_type)::text))),
    CONSTRAINT chk_gst_filing_doc_reference CHECK ((gst_filing_id IS NOT NULL)),
    CONSTRAINT chk_verified_logic CHECK ((((verified = true) AND (verified_by IS NOT NULL) AND (verified_at IS NOT NULL)) OR (verified = false)))
);


--
-- Name: gst_filings_documents_document_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_filings_documents_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_filings_documents_document_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_filings_documents_document_id_seq OWNED BY solvetax.gst_filings_documents.document_id;


--
-- Name: gst_filings_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_filings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_filings_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_filings_id_seq OWNED BY solvetax.gst_filings.id;


--
-- Name: gst_registration; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_registration (
    id bigint NOT NULL,
    customer_id bigint,
    gstin character varying(15),
    username character varying(100),
    password text,
    pan character varying(10),
    mobile character varying(20),
    language character varying(50),
    state character varying(50),
    business_name character varying(200),
    registration_type character varying(50),
    ownership_category character varying(50),
    business_type character varying(50),
    turnover_details character varying(50) DEFAULT 'LESS_THAN_2CR'::character varying,
    registration_status character varying(50) DEFAULT 'DRAFT'::character varying,
    suspension_reason text,
    cancellation_reason text,
    approved_at timestamp with time zone,
    is_rcm_applicable boolean DEFAULT false,
    is_active boolean DEFAULT true,
    created_by bigint,
    rm_id bigint,
    email character varying(150),
    secondary_email character varying(150),
    is_filing_needed boolean DEFAULT true,
    filing_preference character varying(20),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    client_name character varying(200),
    referral_phone_number character varying(20),
    CONSTRAINT chk_approved_logic CHECK (((((registration_status)::text = 'APPROVED'::text) AND (approved_at IS NOT NULL)) OR (((registration_status)::text <> 'APPROVED'::text) AND (approved_at IS NULL)))),
    CONSTRAINT chk_gst_format CHECK (((gstin IS NULL) OR ((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))),
    CONSTRAINT chk_gstin_pan_match CHECK (((pan IS NULL) OR (gstin IS NULL) OR (upper(TRIM(BOTH FROM pan)) = SUBSTRING(upper(TRIM(BOTH FROM gstin)) FROM 3 FOR 10)))),
    CONSTRAINT chk_mobile_format CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text))),
    CONSTRAINT chk_pan_format CHECK (((pan IS NULL) OR ((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text))),
    CONSTRAINT chk_secondary_email_format CHECK (((secondary_email IS NULL) OR ((secondary_email)::text ~* '^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$'::text)))
);


--
-- Name: gst_registration_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_registration_config (
    id bigint NOT NULL,
    config_type character varying(50) NOT NULL,
    value character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: gst_registration_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.gst_registration_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: gst_registration_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.gst_registration_config_id_seq OWNED BY solvetax.gst_registration_config.id;


--
-- Name: gst_registration_documents; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_registration_documents (
    document_id bigint NOT NULL,
    gstin character varying(15),
    person_id bigint,
    document_type character varying(50) NOT NULL,
    document_url text NOT NULL,
    verified boolean DEFAULT false NOT NULL,
    verified_by bigint,
    verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    is_active boolean DEFAULT true,
    mobile character varying(20),
    CONSTRAINT chk_doc_gst_format CHECK (((gstin IS NULL) OR ((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))),
    CONSTRAINT chk_doc_mobile_format CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text))),
    CONSTRAINT chk_verified_active CHECK ((((verified = true) AND (verified_by IS NOT NULL) AND (verified_at IS NOT NULL)) OR (verified = false)))
);


--
-- Name: gst_registration_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

ALTER TABLE solvetax.gst_registration ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME solvetax.gst_registration_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: gst_registration_persons; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.gst_registration_persons (
    person_id bigint NOT NULL,
    gstin character varying(15),
    full_name character varying(150) NOT NULL,
    designation character varying(100) NOT NULL,
    pan character varying(10),
    aadhaar character varying(20),
    email character varying(150),
    mobile character varying(20),
    is_primary_customer boolean DEFAULT false,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    ownership_category character varying(50),
    gst_registration_id bigint NOT NULL,
    CONSTRAINT chk_pan_format CHECK (((pan IS NULL) OR ((pan)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text))),
    CONSTRAINT chk_person_aadhaar_format CHECK (((aadhaar IS NULL) OR ((aadhaar)::text ~ '^[0-9]{12}$'::text))),
    CONSTRAINT chk_person_gst_format CHECK (((gstin IS NULL) OR ((gstin)::text ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][A-Z0-9]Z[A-Z0-9]$'::text))),
    CONSTRAINT chk_person_mobile_format CHECK (((mobile IS NULL) OR ((mobile)::text ~ '^[0-9]{10}$'::text)))
);


--
-- Name: income_tax; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.income_tax (
    id bigint NOT NULL,
    client_name character varying(150) NOT NULL,
    mobile character varying(20) NOT NULL,
    language character varying(50),
    state character varying(100),
    priority character varying(10) DEFAULT 'NORMAL'::character varying NOT NULL,
    remarks text,
    pan_number character varying(10),
    password text,
    financial_year character varying(9)[] NOT NULL,
    filed_status character varying(12) DEFAULT 'NOT_FILED'::character varying NOT NULL,
    filing_date timestamp with time zone,
    email_id character varying(150),
    source_of_income character varying(100)[],
    refund_amount numeric(12,2),
    rm_id bigint,
    op_id bigint,
    referral_phone_number character varying(20),
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    year smallint NOT NULL,
    CONSTRAINT chk_income_tax_financial_year_not_empty CHECK (((financial_year IS NOT NULL) AND (cardinality(financial_year) > 0))),
    CONSTRAINT chk_income_tax_pan_format CHECK (((pan_number IS NULL) OR ((pan_number)::text ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'::text))),
    CONSTRAINT chk_income_tax_referral_phone_format CHECK (((referral_phone_number IS NULL) OR ((referral_phone_number)::text ~ '^\d{10}$'::text)))
);


--
-- Name: income_tax_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.income_tax_config (
    id bigint NOT NULL,
    config_type character varying(50) NOT NULL,
    value character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


--
-- Name: income_tax_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.income_tax_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: income_tax_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.income_tax_config_id_seq OWNED BY solvetax.income_tax_config.id;


--
-- Name: income_tax_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.income_tax_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: income_tax_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.income_tax_id_seq OWNED BY solvetax.income_tax.id;


--
-- Name: issue_reports; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.issue_reports (
    id bigint NOT NULL,
    reporter_emp_id bigint NOT NULL,
    title character varying(200) NOT NULL,
    description text NOT NULL,
    priority character varying(20) DEFAULT 'MEDIUM'::character varying NOT NULL,
    status character varying(20) DEFAULT 'OPEN'::character varying NOT NULL,
    photo_urls text[] DEFAULT ARRAY[]::text[] NOT NULL,
    resolved_by_emp_id bigint,
    resolved_at timestamp with time zone,
    resolution_note text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: issue_reports_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

ALTER TABLE solvetax.issue_reports ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME solvetax.issue_reports_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: password_reset_otps; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.password_reset_otps (
    id bigint NOT NULL,
    emp_id bigint NOT NULL,
    otp_code character varying(10) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    is_used boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: password_reset_otps_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.password_reset_otps_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: password_reset_otps_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.password_reset_otps_id_seq OWNED BY solvetax.password_reset_otps.id;


--
-- Name: payment_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.payment_config (
    id bigint NOT NULL,
    entity_type character varying(50) NOT NULL,
    config_type character varying(50) NOT NULL,
    value character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    amount numeric(10,2) NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    filter character varying(50)
);


--
-- Name: payment_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.payment_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: payment_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.payment_config_id_seq OWNED BY solvetax.payment_config.id;


--
-- Name: payments; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.payments (
    id bigint NOT NULL,
    transaction_id character varying(100),
    customer_id bigint,
    entity_id bigint NOT NULL,
    entity_type character varying(50) NOT NULL,
    amount numeric(12,2) NOT NULL,
    discount numeric(12,2) DEFAULT 0,
    net_amount numeric(12,2) NOT NULL,
    paid_amount numeric(12,2) DEFAULT 0,
    payment_status character varying(30) DEFAULT 'PENDING'::character varying NOT NULL,
    payment_mode character varying(30),
    payment_date timestamp with time zone,
    remarks text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    followup_at timestamp with time zone,
    followup_status character varying(20),
    followup_remarks text,
    completed_at timestamp with time zone,
    missed_at timestamp with time zone,
    remaining_amount numeric(12,2),
    CONSTRAINT chk_amount_positive CHECK ((amount >= (0)::numeric)),
    CONSTRAINT chk_discount_positive CHECK ((discount >= (0)::numeric)),
    CONSTRAINT chk_paid_amount_positive CHECK ((paid_amount >= (0)::numeric)),
    CONSTRAINT chk_paid_not_exceed_net CHECK ((paid_amount <= net_amount))
);


--
-- Name: registration_documents_document_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.registration_documents_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: registration_documents_document_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.registration_documents_document_id_seq OWNED BY solvetax.gst_registration_documents.document_id;


--
-- Name: registration_payments_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.registration_payments_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: registration_payments_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.registration_payments_id_seq OWNED BY solvetax.payments.id;


--
-- Name: registration_persons_person_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.registration_persons_person_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: registration_persons_person_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.registration_persons_person_id_seq OWNED BY solvetax.gst_registration_persons.person_id;


--
-- Name: role_features; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.role_features (
    id bigint NOT NULL,
    role_id bigint NOT NULL,
    feature_id bigint NOT NULL,
    permission_code character varying(20) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: role_features_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.role_features_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_features_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.role_features_id_seq OWNED BY solvetax.role_features.id;


--
-- Name: roles; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.roles (
    id bigint NOT NULL,
    role_code character varying(50) NOT NULL,
    role_name character varying(100) NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: roles_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.roles_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: roles_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.roles_id_seq OWNED BY solvetax.roles.id;


--
-- Name: service_config; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.service_config (
    id bigint NOT NULL,
    service_category character varying(100) NOT NULL,
    service_code character varying(100) NOT NULL,
    service_name character varying(200) NOT NULL,
    description text,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: service_config_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.service_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: service_config_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.service_config_id_seq OWNED BY solvetax.service_config.id;


--
-- Name: session_audit_log; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.session_audit_log (
    id bigint NOT NULL,
    emp_id bigint NOT NULL,
    session_token text NOT NULL,
    action character varying(50) NOT NULL,
    action_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    action_details text,
    ip_address character varying(50)
);


--
-- Name: session_audit_log_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.session_audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.session_audit_log_id_seq OWNED BY solvetax.session_audit_log.id;


--
-- Name: session_token; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.session_token (
    id bigint NOT NULL,
    emp_id bigint NOT NULL,
    session_token text NOT NULL,
    is_active boolean DEFAULT true,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp with time zone,
    device_info text,
    ip_address character varying(50),
    refresh_token text,
    refresh_expires_at timestamp with time zone
);


--
-- Name: session_token_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.session_token_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: session_token_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.session_token_id_seq OWNED BY solvetax.session_token.id;


--
-- Name: versions; Type: TABLE; Schema: solvetax; Owner: -
--

CREATE TABLE solvetax.versions (
    id bigint NOT NULL,
    emp_id bigint,
    entity_id bigint NOT NULL,
    action character varying(20) NOT NULL,
    "json" jsonb,
    updated_json jsonb,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    entity_type character varying(100) NOT NULL,
    customer_id bigint,
    CONSTRAINT chk_action_json CHECK (((((action)::text = 'CREATE'::text) AND ("json" IS NOT NULL) AND (updated_json IS NULL)) OR (((action)::text = 'UPDATE'::text) AND ("json" IS NOT NULL) AND (updated_json IS NOT NULL)) OR (((action)::text = 'DELETE'::text) AND ("json" IS NULL) AND (updated_json IS NULL)) OR (((action)::text = 'ACTIVATE'::text) AND ("json" IS NULL) AND (updated_json IS NULL))))
);


--
-- Name: versions_id_seq; Type: SEQUENCE; Schema: solvetax; Owner: -
--

CREATE SEQUENCE solvetax.versions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: versions_id_seq; Type: SEQUENCE OWNED BY; Schema: solvetax; Owner: -
--

ALTER SEQUENCE solvetax.versions_id_seq OWNED BY solvetax.versions.id;


--
-- Name: contact_support id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.contact_support ALTER COLUMN id SET DEFAULT nextval('solvetax.contact_support_id_seq'::regclass);


--
-- Name: crm_activities id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_activities ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_activities_id_seq'::regclass);


--
-- Name: crm_bulk_assign_logs id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_bulk_assign_logs ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_bulk_assign_logs_id_seq'::regclass);


--
-- Name: crm_bulk_assign_schedulers id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_bulk_assign_schedulers ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_bulk_assign_schedulers_id_seq'::regclass);


--
-- Name: crm_call_statuses id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_statuses ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_call_statuses_id_seq'::regclass);


--
-- Name: crm_call_types id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_types ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_call_types_id_seq'::regclass);


--
-- Name: crm_lead_stages id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_lead_stages ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_lead_stages_id_seq'::regclass);


--
-- Name: crm_leads id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_leads ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_leads_id_seq'::regclass);


--
-- Name: crm_rm_op_mappings id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_rm_op_mappings ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_rm_op_mappings_id_seq'::regclass);


--
-- Name: crm_stage_status_mappings id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_stage_status_mappings ALTER COLUMN id SET DEFAULT nextval('solvetax.crm_ui_mappings_id_seq'::regclass);


--
-- Name: customer_otp_verify id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_otp_verify ALTER COLUMN id SET DEFAULT nextval('solvetax.client_otp_verify_id_seq'::regclass);


--
-- Name: customer_services id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_services ALTER COLUMN id SET DEFAULT nextval('solvetax.customer_services_id_seq'::regclass);


--
-- Name: d_customer_session id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.d_customer_session ALTER COLUMN id SET DEFAULT nextval('solvetax.d_customer_session_id_seq'::regclass);


--
-- Name: document_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.document_config ALTER COLUMN id SET DEFAULT nextval('solvetax.document_config_id_seq'::regclass);


--
-- Name: employee_email_verifications id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_email_verifications ALTER COLUMN id SET DEFAULT nextval('solvetax.employee_email_verifications_id_seq'::regclass);


--
-- Name: entity_types id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.entity_types ALTER COLUMN id SET DEFAULT nextval('solvetax.entity_types_id_seq'::regclass);


--
-- Name: features id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.features ALTER COLUMN id SET DEFAULT nextval('solvetax.features_id_seq'::regclass);


--
-- Name: gst_filing_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_config ALTER COLUMN id SET DEFAULT nextval('solvetax.gst_filing_config_id_seq1'::regclass);


--
-- Name: gst_filing_return_details id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_return_details ALTER COLUMN id SET DEFAULT nextval('solvetax.gst_filing_return_details_id_seq'::regclass);


--
-- Name: gst_filing_rule_engine id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_rule_engine ALTER COLUMN id SET DEFAULT nextval('solvetax.gst_filing_config_id_seq'::regclass);


--
-- Name: gst_filings id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings ALTER COLUMN id SET DEFAULT nextval('solvetax.gst_filings_id_seq'::regclass);


--
-- Name: gst_filings_documents document_id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings_documents ALTER COLUMN document_id SET DEFAULT nextval('solvetax.gst_filings_documents_document_id_seq'::regclass);


--
-- Name: gst_registration_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_config ALTER COLUMN id SET DEFAULT nextval('solvetax.gst_registration_config_id_seq'::regclass);


--
-- Name: gst_registration_documents document_id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_documents ALTER COLUMN document_id SET DEFAULT nextval('solvetax.registration_documents_document_id_seq'::regclass);


--
-- Name: gst_registration_persons person_id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_persons ALTER COLUMN person_id SET DEFAULT nextval('solvetax.registration_persons_person_id_seq'::regclass);


--
-- Name: income_tax id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax ALTER COLUMN id SET DEFAULT nextval('solvetax.income_tax_id_seq'::regclass);


--
-- Name: income_tax_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax_config ALTER COLUMN id SET DEFAULT nextval('solvetax.income_tax_config_id_seq'::regclass);


--
-- Name: password_reset_otps id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.password_reset_otps ALTER COLUMN id SET DEFAULT nextval('solvetax.password_reset_otps_id_seq'::regclass);


--
-- Name: payment_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.payment_config ALTER COLUMN id SET DEFAULT nextval('solvetax.payment_config_id_seq'::regclass);


--
-- Name: payments id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.payments ALTER COLUMN id SET DEFAULT nextval('solvetax.registration_payments_id_seq'::regclass);


--
-- Name: role_features id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.role_features ALTER COLUMN id SET DEFAULT nextval('solvetax.role_features_id_seq'::regclass);


--
-- Name: roles id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.roles ALTER COLUMN id SET DEFAULT nextval('solvetax.roles_id_seq'::regclass);


--
-- Name: service_config id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.service_config ALTER COLUMN id SET DEFAULT nextval('solvetax.service_config_id_seq'::regclass);


--
-- Name: session_audit_log id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_audit_log ALTER COLUMN id SET DEFAULT nextval('solvetax.session_audit_log_id_seq'::regclass);


--
-- Name: session_token id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_token ALTER COLUMN id SET DEFAULT nextval('solvetax.session_token_id_seq'::regclass);


--
-- Name: versions id; Type: DEFAULT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.versions ALTER COLUMN id SET DEFAULT nextval('solvetax.versions_id_seq'::regclass);


--
-- Name: contact_support contact_support_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.contact_support
    ADD CONSTRAINT contact_support_pkey PRIMARY KEY (id);


--
-- Name: crm_activities crm_activities_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_activities
    ADD CONSTRAINT crm_activities_pkey PRIMARY KEY (id);


--
-- Name: crm_bulk_assign_logs crm_bulk_assign_logs_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_bulk_assign_logs
    ADD CONSTRAINT crm_bulk_assign_logs_pkey PRIMARY KEY (id);


--
-- Name: crm_bulk_assign_schedulers crm_bulk_assign_schedulers_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_bulk_assign_schedulers
    ADD CONSTRAINT crm_bulk_assign_schedulers_pkey PRIMARY KEY (id);


--
-- Name: crm_call_statuses crm_call_statuses_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_statuses
    ADD CONSTRAINT crm_call_statuses_pkey PRIMARY KEY (id);


--
-- Name: crm_call_types crm_call_types_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_types
    ADD CONSTRAINT crm_call_types_pkey PRIMARY KEY (id);


--
-- Name: crm_lead_stages crm_lead_stages_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_lead_stages
    ADD CONSTRAINT crm_lead_stages_pkey PRIMARY KEY (id);


--
-- Name: crm_leads crm_leads_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_leads
    ADD CONSTRAINT crm_leads_pkey PRIMARY KEY (id);


--
-- Name: crm_rm_op_mappings crm_rm_op_mappings_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_rm_op_mappings
    ADD CONSTRAINT crm_rm_op_mappings_pkey PRIMARY KEY (id);


--
-- Name: crm_stage_status_mappings crm_ui_mappings_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_stage_status_mappings
    ADD CONSTRAINT crm_ui_mappings_pkey PRIMARY KEY (id);


--
-- Name: customer_otp_verify customer_otp_verify_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_otp_verify
    ADD CONSTRAINT customer_otp_verify_pkey PRIMARY KEY (id);


--
-- Name: customer_services customer_services_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_services
    ADD CONSTRAINT customer_services_pkey PRIMARY KEY (id);


--
-- Name: customers customers_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (customer_id);


--
-- Name: d_customer_session d_customer_session_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.d_customer_session
    ADD CONSTRAINT d_customer_session_pkey PRIMARY KEY (id);


--
-- Name: document_config document_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.document_config
    ADD CONSTRAINT document_config_pkey PRIMARY KEY (id);


--
-- Name: employee_email_verifications employee_email_verifications_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_email_verifications
    ADD CONSTRAINT employee_email_verifications_pkey PRIMARY KEY (id);


--
-- Name: employee_roles employee_roles_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_roles
    ADD CONSTRAINT employee_roles_pkey PRIMARY KEY (emp_id, role_id);


--
-- Name: employee_tasks employee_tasks_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_tasks
    ADD CONSTRAINT employee_tasks_pkey PRIMARY KEY (id);


--
-- Name: employees employees_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employees
    ADD CONSTRAINT employees_pkey PRIMARY KEY (emp_id);


--
-- Name: entity_types entity_types_name_unique; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.entity_types
    ADD CONSTRAINT entity_types_name_unique UNIQUE (entity_name);


--
-- Name: entity_types entity_types_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.entity_types
    ADD CONSTRAINT entity_types_pkey PRIMARY KEY (id);


--
-- Name: features features_feature_code_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.features
    ADD CONSTRAINT features_feature_code_key UNIQUE (feature_code);


--
-- Name: features features_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.features
    ADD CONSTRAINT features_pkey PRIMARY KEY (id);


--
-- Name: gst_filing_config gst_filing_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_config
    ADD CONSTRAINT gst_filing_config_pkey PRIMARY KEY (id);


--
-- Name: gst_filing_return_details gst_filing_return_details_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_return_details
    ADD CONSTRAINT gst_filing_return_details_pkey PRIMARY KEY (id);


--
-- Name: gst_filing_rule_engine gst_filing_rule_engine_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_rule_engine
    ADD CONSTRAINT gst_filing_rule_engine_pkey PRIMARY KEY (id);


--
-- Name: gst_filings_documents gst_filings_documents_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings_documents
    ADD CONSTRAINT gst_filings_documents_pkey PRIMARY KEY (document_id);


--
-- Name: gst_filings gst_filings_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings
    ADD CONSTRAINT gst_filings_pkey PRIMARY KEY (id);


--
-- Name: gst_registration_config gst_registration_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_config
    ADD CONSTRAINT gst_registration_config_pkey PRIMARY KEY (id);


--
-- Name: gst_registration gst_registration_gstin_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration
    ADD CONSTRAINT gst_registration_gstin_key UNIQUE (gstin);


--
-- Name: gst_registration gst_registration_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration
    ADD CONSTRAINT gst_registration_pkey PRIMARY KEY (id);


--
-- Name: income_tax_config income_tax_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax_config
    ADD CONSTRAINT income_tax_config_pkey PRIMARY KEY (id);


--
-- Name: income_tax income_tax_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax
    ADD CONSTRAINT income_tax_pkey PRIMARY KEY (id);


--
-- Name: issue_reports issue_reports_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.issue_reports
    ADD CONSTRAINT issue_reports_pkey PRIMARY KEY (id);


--
-- Name: password_reset_otps password_reset_otps_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.password_reset_otps
    ADD CONSTRAINT password_reset_otps_pkey PRIMARY KEY (id);


--
-- Name: payment_config payment_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.payment_config
    ADD CONSTRAINT payment_config_pkey PRIMARY KEY (id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (id);


--
-- Name: payments payments_transaction_id_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.payments
    ADD CONSTRAINT payments_transaction_id_key UNIQUE (transaction_id);


--
-- Name: gst_registration_documents registration_documents_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_documents
    ADD CONSTRAINT registration_documents_pkey PRIMARY KEY (document_id);


--
-- Name: gst_registration_persons registration_persons_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_persons
    ADD CONSTRAINT registration_persons_pkey PRIMARY KEY (person_id);


--
-- Name: role_features role_features_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.role_features
    ADD CONSTRAINT role_features_pkey PRIMARY KEY (id);


--
-- Name: role_features role_features_role_id_feature_id_permission_code_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.role_features
    ADD CONSTRAINT role_features_role_id_feature_id_permission_code_key UNIQUE (role_id, feature_id, permission_code);


--
-- Name: roles roles_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);


--
-- Name: roles roles_role_code_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.roles
    ADD CONSTRAINT roles_role_code_key UNIQUE (role_code);


--
-- Name: service_config service_config_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.service_config
    ADD CONSTRAINT service_config_pkey PRIMARY KEY (id);


--
-- Name: service_config service_config_service_code_key; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.service_config
    ADD CONSTRAINT service_config_service_code_key UNIQUE (service_code);


--
-- Name: session_audit_log session_audit_log_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_audit_log
    ADD CONSTRAINT session_audit_log_pkey PRIMARY KEY (id);


--
-- Name: session_token session_token_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_token
    ADD CONSTRAINT session_token_pkey PRIMARY KEY (id);


--
-- Name: crm_call_statuses uq_crm_call_statuses_entity_code; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_statuses
    ADD CONSTRAINT uq_crm_call_statuses_entity_code UNIQUE (entity_type, code);


--
-- Name: crm_call_types uq_crm_call_types_entity_code; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_call_types
    ADD CONSTRAINT uq_crm_call_types_entity_code UNIQUE (entity_type, code);


--
-- Name: crm_lead_stages uq_crm_lead_stages_entity_code; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_lead_stages
    ADD CONSTRAINT uq_crm_lead_stages_entity_code UNIQUE (entity_type, code);


--
-- Name: crm_rm_op_mappings uq_crm_rm_op_entity; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_rm_op_mappings
    ADD CONSTRAINT uq_crm_rm_op_entity UNIQUE (rm_emp_id, entity_type);


--
-- Name: gst_filing_config uq_filing_type; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_config
    ADD CONSTRAINT uq_filing_type UNIQUE (filing_type);


--
-- Name: versions versions_pkey; Type: CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.versions
    ADD CONSTRAINT versions_pkey PRIMARY KEY (id);


--
-- Name: idx_contact_support_is_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_is_active ON solvetax.contact_support USING btree (is_active);


--
-- Name: idx_contact_support_is_resolved; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_is_resolved ON solvetax.contact_support USING btree (is_resolved);


--
-- Name: idx_contact_support_op_id; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_op_id ON solvetax.contact_support USING btree (op_id);


--
-- Name: idx_contact_support_phone; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_phone ON solvetax.contact_support USING btree (phone_number);


--
-- Name: idx_contact_support_referal_phone; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_referal_phone ON solvetax.contact_support USING btree (referal_phone_number);


--
-- Name: idx_contact_support_referal_phone_gin; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_referal_phone_gin ON solvetax.contact_support USING gin (referal_phone_number);


--
-- Name: idx_contact_support_rm_id; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_rm_id ON solvetax.contact_support USING btree (rm_id);


--
-- Name: idx_contact_support_service_required_gin; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_contact_support_service_required_gin ON solvetax.contact_support USING gin (service_required);


--
-- Name: idx_crm_activities_actor_time; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_activities_actor_time ON solvetax.crm_activities USING btree (performed_by, performed_at DESC);


--
-- Name: idx_crm_activities_deal_time; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_activities_deal_time ON solvetax.crm_activities USING btree (lead_id, performed_at DESC);


--
-- Name: idx_crm_activities_entity_lead_time; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_activities_entity_lead_time ON solvetax.crm_activities USING btree (entity_type, lead_id, performed_at DESC);


--
-- Name: idx_crm_activities_last_attempted; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_activities_last_attempted ON solvetax.crm_activities USING btree (last_dailed_at DESC) WHERE (last_dailed_at IS NOT NULL);


--
-- Name: idx_crm_activities_last_connected; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_activities_last_connected ON solvetax.crm_activities USING btree (last_connected_at DESC) WHERE (last_connected_at IS NOT NULL);


--
-- Name: idx_crm_bulk_assign_logs_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_bulk_assign_logs_created ON solvetax.crm_bulk_assign_logs USING btree (created_at DESC);


--
-- Name: idx_crm_bulk_assign_logs_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_bulk_assign_logs_entity ON solvetax.crm_bulk_assign_logs USING btree (entity_type, run_type);


--
-- Name: idx_crm_bulk_assign_schedulers_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_bulk_assign_schedulers_entity ON solvetax.crm_bulk_assign_schedulers USING btree (entity_type, enabled) WHERE (is_active = true);


--
-- Name: idx_crm_lead_stages_active_sort; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_lead_stages_active_sort ON solvetax.crm_lead_stages USING btree (is_active, sort_order);


--
-- Name: idx_crm_leads_ay; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_ay ON solvetax.crm_leads USING btree (ay);


--
-- Name: idx_crm_leads_email; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_email ON solvetax.crm_leads USING btree (email);


--
-- Name: idx_crm_leads_entity_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_entity_active ON solvetax.crm_leads USING btree (entity_type, entity_id, is_active);


--
-- Name: idx_crm_leads_entity_mobile_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_entity_mobile_active ON solvetax.crm_leads USING btree (entity_type, mobile, is_active);


--
-- Name: idx_crm_leads_followup; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_followup ON solvetax.crm_leads USING btree (followup_at) WHERE (is_active = true);


--
-- Name: idx_crm_leads_full_name; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_full_name ON solvetax.crm_leads USING btree (full_name);


--
-- Name: idx_crm_leads_last_connected_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_last_connected_at ON solvetax.crm_leads USING btree (last_connected_at) WHERE (is_active = true);


--
-- Name: idx_crm_leads_lead_source; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_lead_source ON solvetax.crm_leads USING btree (lead_source);


--
-- Name: idx_crm_leads_lead_type; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_lead_type ON solvetax.crm_leads USING btree (lead_type);


--
-- Name: idx_crm_leads_mobile; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_mobile ON solvetax.crm_leads USING btree (mobile);


--
-- Name: idx_crm_leads_stage_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_stage_active ON solvetax.crm_leads USING btree (stage, is_active);


--
-- Name: idx_crm_leads_tag; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_leads_tag ON solvetax.crm_leads USING btree (tag);


--
-- Name: idx_crm_rm_op_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_rm_op_entity ON solvetax.crm_rm_op_mappings USING btree (entity_type) WHERE (is_active = true);


--
-- Name: idx_crm_ui_mappings_kind_pitch; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_crm_ui_mappings_kind_pitch ON solvetax.crm_stage_status_mappings USING btree (mapping_kind, pitch_type_code) WHERE (is_active = true);


--
-- Name: idx_customer_otp_verify_expires_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_otp_verify_expires_at ON solvetax.customer_otp_verify USING btree (expires_at);


--
-- Name: idx_customer_otp_verify_mobile_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_otp_verify_mobile_active_created ON solvetax.customer_otp_verify USING btree (mobile, is_active, created_at DESC);


--
-- Name: idx_customer_otp_verify_mobile_purpose_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_otp_verify_mobile_purpose_active ON solvetax.customer_otp_verify USING btree (mobile, otp_purpose) WHERE (is_active = true);


--
-- Name: idx_customer_services_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_active ON solvetax.customer_services USING btree (customer_id, service_code) WHERE (is_active IS TRUE);


--
-- Name: idx_customer_services_followup_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_followup_at ON solvetax.customer_services USING btree (followup_at) WHERE (followup_at IS NOT NULL);


--
-- Name: idx_customer_services_followup_pending; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_followup_pending ON solvetax.customer_services USING btree (followup_at) WHERE ((followup_at IS NOT NULL) AND ((followup_status)::text = 'PENDING'::text));


--
-- Name: idx_customer_services_op; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_op ON solvetax.customer_services USING btree (op_id);


--
-- Name: idx_customer_services_op_followup; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_op_followup ON solvetax.customer_services USING btree (op_id, followup_at) WHERE (followup_at IS NOT NULL);


--
-- Name: idx_customer_services_rm; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_rm ON solvetax.customer_services USING btree (rm_id);


--
-- Name: idx_customer_services_rm_followup; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_rm_followup ON solvetax.customer_services USING btree (rm_id, followup_at) WHERE (followup_at IS NOT NULL);


--
-- Name: idx_customer_services_service_code_norm; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customer_services_service_code_norm ON solvetax.customer_services USING btree (upper(btrim((service_code)::text)));


--
-- Name: idx_customers_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customers_active_created ON solvetax.customers USING btree (is_active, created_at DESC);


--
-- Name: idx_customers_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customers_created_at ON solvetax.customers USING btree (created_at);


--
-- Name: idx_customers_created_at_desc; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customers_created_at_desc ON solvetax.customers USING btree (created_at DESC);


--
-- Name: idx_customers_language; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customers_language ON solvetax.customers USING btree (language);


--
-- Name: idx_customers_service_required_gin; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_customers_service_required_gin ON solvetax.customers USING gin (service_required);


--
-- Name: idx_d_customer_session_entity_mobile; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_d_customer_session_entity_mobile ON solvetax.d_customer_session USING btree (entity_type, mobile);


--
-- Name: idx_d_customer_session_mobile_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_d_customer_session_mobile_created ON solvetax.d_customer_session USING btree (mobile, created_at DESC);


--
-- Name: idx_doc_gstin_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_doc_gstin_active_created ON solvetax.gst_registration_documents USING btree (gstin, is_active, created_at DESC) WHERE (gstin IS NOT NULL);


--
-- Name: idx_doc_person_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_doc_person_active_created ON solvetax.gst_registration_documents USING btree (person_id, is_active, created_at DESC);


--
-- Name: idx_doc_type_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_doc_type_active ON solvetax.gst_registration_documents USING btree (document_type, is_active);


--
-- Name: idx_doc_verified_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_doc_verified_active ON solvetax.gst_registration_documents USING btree (verified, is_active);


--
-- Name: idx_document_config_entity_active_sort; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_document_config_entity_active_sort ON solvetax.document_config USING btree (registration, ownership_category, is_active, sort_order);


--
-- Name: idx_documents_verified; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_documents_verified ON solvetax.gst_registration_documents USING btree (verified) WHERE (verified = true);


--
-- Name: idx_email_verifications_email; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_email_verifications_email ON solvetax.employee_email_verifications USING btree (email);


--
-- Name: idx_employee_tasks_emp_sched; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_employee_tasks_emp_sched ON solvetax.employee_tasks USING btree (emp_id, scheduled_at);


--
-- Name: idx_employee_tasks_followup; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_employee_tasks_followup ON solvetax.employee_tasks USING btree (followup_at) WHERE (followup_at IS NOT NULL);


--
-- Name: idx_employees_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_employees_created_at ON solvetax.employees USING btree (created_at);


--
-- Name: idx_employees_updated_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_employees_updated_at ON solvetax.employees USING btree (updated_at);


--
-- Name: idx_gfrd_current_active_filing; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gfrd_current_active_filing ON solvetax.gst_filing_return_details USING btree (gst_filing_id, is_current, is_active);


--
-- Name: idx_gfrd_current_auto_next; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gfrd_current_auto_next ON solvetax.gst_filing_return_details USING btree (next_auto_generate_at) WHERE ((is_current = true) AND (is_active = true));


--
-- Name: idx_gst_active_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_active_created_at ON solvetax.gst_registration USING btree (created_at) WHERE (is_active = true);


--
-- Name: idx_gst_active_created_range; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_active_created_range ON solvetax.gst_registration USING btree (is_active, created_at DESC);


--
-- Name: idx_gst_bname_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_active ON solvetax.gst_registration USING btree (lower((business_name)::text), is_active);


--
-- Name: idx_gst_bname_active_created_desc; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_active_created_desc ON solvetax.gst_registration USING btree (lower((business_name)::text), is_active, created_at DESC);


--
-- Name: idx_gst_bname_business_type_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_business_type_active ON solvetax.gst_registration USING btree (lower((business_name)::text), business_type, is_active);


--
-- Name: idx_gst_bname_master_filter; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_master_filter ON solvetax.gst_registration USING btree (lower((business_name)::text), is_active, rm_id, business_type, ownership_category, registration_type, created_at DESC);


--
-- Name: idx_gst_bname_ownership_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_ownership_active ON solvetax.gst_registration USING btree (lower((business_name)::text), ownership_category, is_active);


--
-- Name: idx_gst_bname_registration_type_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_registration_type_active ON solvetax.gst_registration USING btree (lower((business_name)::text), registration_type, is_active);


--
-- Name: idx_gst_bname_rm_active_created_desc; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_bname_rm_active_created_desc ON solvetax.gst_registration USING btree (lower((business_name)::text), rm_id, is_active, created_at DESC);


--
-- Name: idx_gst_business_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_business_active_created ON solvetax.gst_registration USING btree (business_type, is_active, created_at DESC);


--
-- Name: idx_gst_business_name_lower; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_business_name_lower ON solvetax.gst_registration USING btree (lower((business_name)::text));


--
-- Name: idx_gst_config_type_active_sort; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_config_type_active_sort ON solvetax.gst_registration_config USING btree (config_type, is_active, sort_order);


--
-- Name: idx_gst_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_created_at ON solvetax.gst_registration USING btree (created_at);


--
-- Name: idx_gst_customer_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_customer_active_created ON solvetax.gst_registration USING btree (customer_id, is_active, created_at DESC);


--
-- Name: idx_gst_customer_id; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_customer_id ON solvetax.gst_registration USING btree (customer_id);


--
-- Name: idx_gst_customer_status_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_customer_status_active_created ON solvetax.gst_registration USING btree (customer_id, registration_status, is_active, created_at DESC);


--
-- Name: idx_gst_email_lower; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_email_lower ON solvetax.gst_registration USING btree (lower((email)::text));


--
-- Name: idx_gst_filing_docs_filing; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filing_docs_filing ON solvetax.gst_filings_documents USING btree (gst_filing_id, is_active);


--
-- Name: idx_gst_filing_docs_type; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filing_docs_type ON solvetax.gst_filings_documents USING btree (document_type, is_active);


--
-- Name: idx_gst_filing_docs_verified; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filing_docs_verified ON solvetax.gst_filings_documents USING btree (verified) WHERE (verified = true);


--
-- Name: idx_gst_filings_frequency; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_frequency ON solvetax.gst_filings USING btree (filing_frequency);


--
-- Name: idx_gst_filings_language; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_language ON solvetax.gst_filings USING btree (language);


--
-- Name: idx_gst_filings_op; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_op ON solvetax.gst_filings USING btree (op_id);


--
-- Name: idx_gst_filings_referral_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_referral_entity ON solvetax.gst_filings USING btree (referral_entity);


--
-- Name: idx_gst_filings_referral_id; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_referral_id ON solvetax.gst_filings USING btree (referral_id);


--
-- Name: idx_gst_filings_rm; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_rm ON solvetax.gst_filings USING btree (rm_id);


--
-- Name: idx_gst_filings_taxpayer; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_taxpayer ON solvetax.gst_filings USING btree (taxpayer_type);


--
-- Name: idx_gst_filings_turnover; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_filings_turnover ON solvetax.gst_filings USING btree (turnover_details);


--
-- Name: idx_gst_gstin_upper; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_gstin_upper ON solvetax.gst_registration USING btree (upper((gstin)::text));


--
-- Name: idx_gst_is_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_is_active ON solvetax.gst_registration USING btree (is_active);


--
-- Name: idx_gst_language; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_language ON solvetax.gst_registration USING btree (language);


--
-- Name: idx_gst_registration_status; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_registration_status ON solvetax.gst_registration USING btree (registration_status);


--
-- Name: idx_gst_rm_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_rm_active_created ON solvetax.gst_registration USING btree (rm_id, is_active, created_at DESC);


--
-- Name: idx_gst_rm_id; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_rm_id ON solvetax.gst_registration USING btree (rm_id);


--
-- Name: idx_gst_rm_status_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_rm_status_active_created ON solvetax.gst_registration USING btree (rm_id, registration_status, is_active, created_at DESC);


--
-- Name: idx_gst_secondary_email_lower; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_secondary_email_lower ON solvetax.gst_registration USING btree (lower((secondary_email)::text));


--
-- Name: idx_gst_status_active_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_gst_status_active_created ON solvetax.gst_registration USING btree (registration_status, is_active, created_at DESC);


--
-- Name: idx_income_tax_config_type_active_sort; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_income_tax_config_type_active_sort ON solvetax.income_tax_config USING btree (config_type, is_active, sort_order);


--
-- Name: idx_issue_reports_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_issue_reports_created_at ON solvetax.issue_reports USING btree (created_at DESC);


--
-- Name: idx_issue_reports_priority; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_issue_reports_priority ON solvetax.issue_reports USING btree (priority);


--
-- Name: idx_issue_reports_reporter; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_issue_reports_reporter ON solvetax.issue_reports USING btree (reporter_emp_id);


--
-- Name: idx_issue_reports_status; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_issue_reports_status ON solvetax.issue_reports USING btree (status);


--
-- Name: idx_password_reset_emp; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_password_reset_emp ON solvetax.password_reset_otps USING btree (emp_id);


--
-- Name: idx_password_reset_expiry; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_password_reset_expiry ON solvetax.password_reset_otps USING btree (expires_at);


--
-- Name: idx_payment_config_entity_active_sort; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payment_config_entity_active_sort ON solvetax.payment_config USING btree (entity_type, is_active, sort_order);


--
-- Name: idx_payments_created; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_created ON solvetax.payments USING btree (entity_id, customer_id, created_at DESC);


--
-- Name: idx_payments_entity_customer_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_entity_customer_active ON solvetax.payments USING btree (customer_id, entity_id, entity_type, is_active);


--
-- Name: idx_payments_filter; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_filter ON solvetax.payments USING btree (entity_id, customer_id, payment_status, created_at);


--
-- Name: idx_payments_followup_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_followup_at ON solvetax.payments USING btree (followup_at) WHERE ((followup_at IS NOT NULL) AND ((payment_status)::text = 'PENDING'::text));


--
-- Name: idx_payments_followup_entity_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_followup_entity_at ON solvetax.payments USING btree (entity_type, followup_at) WHERE ((followup_at IS NOT NULL) AND ((payment_status)::text = 'PENDING'::text) AND (is_active = true));


--
-- Name: idx_payments_followup_pending; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_followup_pending ON solvetax.payments USING btree (followup_at) WHERE ((followup_at IS NOT NULL) AND ((followup_status)::text = 'PENDING'::text) AND (is_active = true));


--
-- Name: idx_payments_lookup; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_payments_lookup ON solvetax.payments USING btree (customer_id, entity_id, entity_type, is_active);


--
-- Name: idx_reg_email_lower; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_reg_email_lower ON solvetax.gst_registration_persons USING btree (lower((email)::text)) WHERE (email IS NOT NULL);


--
-- Name: idx_reg_gstid_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_reg_gstid_active ON solvetax.gst_registration_persons USING btree (gst_registration_id, is_active);


--
-- Name: idx_reg_gstid_active_created_desc; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_reg_gstid_active_created_desc ON solvetax.gst_registration_persons USING btree (gst_registration_id, is_active, created_at DESC);


--
-- Name: idx_reg_person_pan_upper; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_reg_person_pan_upper ON solvetax.gst_registration_persons USING btree (upper((pan)::text)) WHERE (pan IS NOT NULL);


--
-- Name: idx_session_token_emp_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_session_token_emp_active ON solvetax.session_token USING btree (emp_id, is_active);


--
-- Name: idx_session_token_expires; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_session_token_expires ON solvetax.session_token USING btree (expires_at);


--
-- Name: idx_versions_created_at; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_versions_created_at ON solvetax.versions USING btree (created_at DESC);


--
-- Name: idx_versions_emp; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_versions_emp ON solvetax.versions USING btree (emp_id);


--
-- Name: idx_versions_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE INDEX idx_versions_entity ON solvetax.versions USING btree (entity_type, entity_id);


--
-- Name: uq_crm_leads_gst_mobile_entity; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_crm_leads_gst_mobile_entity ON solvetax.crm_leads USING btree (TRIM(BOTH FROM mobile), upper(TRIM(BOTH FROM entity_type))) WHERE (upper(TRIM(BOTH FROM entity_type)) = 'GST_REGISTRATION'::text);


--
-- Name: uq_crm_ui_pitch_status; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_crm_ui_pitch_status ON solvetax.crm_stage_status_mappings USING btree (entity_type, mapping_kind, pitch_type_code, call_status_code) WHERE (((mapping_kind)::text = 'PITCH_TO_STATUS'::text) AND (is_active = true));


--
-- Name: uq_crm_ui_stage_pitch; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_crm_ui_stage_pitch ON solvetax.crm_stage_status_mappings USING btree (entity_type, mapping_kind, stage, pitch_type_code) WHERE (((mapping_kind)::text = 'STAGE_TO_PITCH'::text) AND (is_active = true));


--
-- Name: uq_customer_services_customer_service_code; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_customer_services_customer_service_code ON solvetax.customer_services USING btree (customer_id, service_code) NULLS NOT DISTINCT;


--
-- Name: uq_customers_email; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_customers_email ON solvetax.customers USING btree (lower(TRIM(BOTH FROM email))) WHERE (email IS NOT NULL);


--
-- Name: uq_customers_mobile; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_customers_mobile ON solvetax.customers USING btree (TRIM(BOTH FROM mobile));


--
-- Name: uq_doc_gstin_type_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_doc_gstin_type_active ON solvetax.gst_registration_documents USING btree (gstin, document_type) WHERE ((person_id IS NULL) AND (is_active = true) AND (gstin IS NOT NULL));


--
-- Name: uq_doc_person_type_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_doc_person_type_active ON solvetax.gst_registration_documents USING btree (person_id, document_type) WHERE ((person_id IS NOT NULL) AND (is_active = true));


--
-- Name: uq_document_config_unique; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_document_config_unique ON solvetax.document_config USING btree (upper(TRIM(BOTH FROM registration)), upper(TRIM(BOTH FROM ownership_category)), upper(TRIM(BOTH FROM config_type)), upper(TRIM(BOTH FROM value)));


--
-- Name: uq_employees_email; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_employees_email ON solvetax.employees USING btree (lower(TRIM(BOTH FROM email)));


--
-- Name: uq_employees_phone; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_employees_phone ON solvetax.employees USING btree (TRIM(BOTH FROM phone_number)) WHERE (phone_number IS NOT NULL);


--
-- Name: uq_employees_username; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_employees_username ON solvetax.employees USING btree (lower(TRIM(BOTH FROM username)));


--
-- Name: uq_gst_config_type_value; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_gst_config_type_value ON solvetax.gst_registration_config USING btree (upper(TRIM(BOTH FROM config_type)), upper(TRIM(BOTH FROM value)));


--
-- Name: uq_gst_filing_doc_unique; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_gst_filing_doc_unique ON solvetax.gst_filings_documents USING btree (gst_filing_id, document_type) WHERE (is_active = true);


--
-- Name: uq_gst_filing_unique; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_gst_filing_unique ON solvetax.gst_filings USING btree (customer_id, COALESCE(gst_registration_id, (0)::bigint), COALESCE(gstin, ''::character varying), filing_period);


--
-- Name: uq_gst_gstin_mobile_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_gst_gstin_mobile_active ON solvetax.gst_registration USING btree (upper(TRIM(BOTH FROM gstin)), TRIM(BOTH FROM mobile)) WHERE ((mobile IS NOT NULL) AND (is_active = true));


--
-- Name: uq_gst_username_lower; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_gst_username_lower ON solvetax.gst_registration USING btree (lower((username)::text));


--
-- Name: uq_income_tax_config_type_value; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_income_tax_config_type_value ON solvetax.income_tax_config USING btree (upper(TRIM(BOTH FROM config_type)), upper(TRIM(BOTH FROM value)));


--
-- Name: uq_payments_paid; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_payments_paid ON solvetax.payments USING btree (customer_id, entity_id, entity_type) WHERE (((payment_status)::text = 'PAID'::text) AND (is_active = true));


--
-- Name: uq_reg_person_gstid_aadhaar_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_reg_person_gstid_aadhaar_active ON solvetax.gst_registration_persons USING btree (gst_registration_id, TRIM(BOTH FROM aadhaar)) WHERE ((aadhaar IS NOT NULL) AND (is_active = true));


--
-- Name: uq_reg_person_gstid_email_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_reg_person_gstid_email_active ON solvetax.gst_registration_persons USING btree (gst_registration_id, lower(TRIM(BOTH FROM email))) WHERE ((email IS NOT NULL) AND (is_active = true));


--
-- Name: uq_reg_person_gstid_mobile_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_reg_person_gstid_mobile_active ON solvetax.gst_registration_persons USING btree (gst_registration_id, TRIM(BOTH FROM mobile)) WHERE ((mobile IS NOT NULL) AND (is_active = true));


--
-- Name: uq_reg_person_gstid_pan_active; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_reg_person_gstid_pan_active ON solvetax.gst_registration_persons USING btree (gst_registration_id, upper(TRIM(BOTH FROM pan))) WHERE ((pan IS NOT NULL) AND (is_active = true));


--
-- Name: uq_reg_primary_per_gstid; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_reg_primary_per_gstid ON solvetax.gst_registration_persons USING btree (gst_registration_id) WHERE ((is_primary_customer = true) AND (is_active = true));


--
-- Name: uq_session_refresh_token; Type: INDEX; Schema: solvetax; Owner: -
--

CREATE UNIQUE INDEX uq_session_refresh_token ON solvetax.session_token USING btree (refresh_token) WHERE (is_active = true);


--
-- Name: crm_leads trg_crm_leads_milestone_dial_timestamps; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_crm_leads_milestone_dial_timestamps BEFORE INSERT OR UPDATE OF stage ON solvetax.crm_leads FOR EACH ROW EXECUTE FUNCTION solvetax.fn_crm_leads_touch_dial_on_milestone_stage();


--
-- Name: crm_leads trg_crm_leads_set_assigned_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_crm_leads_set_assigned_at BEFORE INSERT OR UPDATE OF rm_id, op_id ON solvetax.crm_leads FOR EACH ROW EXECUTE FUNCTION solvetax.fn_crm_leads_set_assigned_at();


--
-- Name: customer_services trg_customer_services_updated_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_customer_services_updated_at BEFORE UPDATE ON solvetax.customer_services FOR EACH ROW EXECUTE FUNCTION solvetax.touch_customer_services_updated_at();


--
-- Name: customer_services trg_followup_completed_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_followup_completed_at BEFORE INSERT OR UPDATE ON solvetax.customer_services FOR EACH ROW EXECUTE FUNCTION solvetax.set_followup_completed_at();


--
-- Name: gst_registration trg_normalize_gst_fields; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_normalize_gst_fields BEFORE INSERT OR UPDATE ON solvetax.gst_registration FOR EACH ROW EXECUTE FUNCTION solvetax.normalize_gst_fields();


--
-- Name: gst_filings trg_on_filing_completed; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_on_filing_completed BEFORE UPDATE ON solvetax.gst_filings FOR EACH ROW EXECUTE FUNCTION solvetax.fn_on_filing_completed();


--
-- Name: payments trg_payments_followup_completed_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_payments_followup_completed_at BEFORE INSERT OR UPDATE OF followup_status ON solvetax.payments FOR EACH ROW EXECUTE FUNCTION solvetax.fn_payments_followup_completed_at();


--
-- Name: gst_registration trg_propagate_gst_reg_status_to_filings; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_propagate_gst_reg_status_to_filings AFTER UPDATE OF registration_status ON solvetax.gst_registration FOR EACH ROW EXECUTE FUNCTION solvetax.fn_propagate_gst_registration_status_to_filings();


--
-- Name: gst_registration trg_set_approved_timestamp; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_approved_timestamp BEFORE UPDATE ON solvetax.gst_registration FOR EACH ROW EXECUTE FUNCTION solvetax.set_approved_timestamp();


--
-- Name: gst_filings trg_set_data_received_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_data_received_at BEFORE UPDATE ON solvetax.gst_filings FOR EACH ROW EXECUTE FUNCTION solvetax.fn_set_data_received_at();


--
-- Name: customer_services trg_set_provided_at; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_provided_at BEFORE INSERT OR UPDATE ON solvetax.customer_services FOR EACH ROW EXECUTE FUNCTION solvetax.set_provided_at();


--
-- Name: gst_filings_documents trg_set_updated_at_doc; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_updated_at_doc BEFORE UPDATE ON solvetax.gst_filings_documents FOR EACH ROW EXECUTE FUNCTION solvetax.fn_set_updated_at_doc();


--
-- Name: gst_filings_documents trg_set_verified_fields_doc; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_verified_fields_doc BEFORE UPDATE ON solvetax.gst_filings_documents FOR EACH ROW EXECUTE FUNCTION solvetax.fn_set_verified_fields_doc();


--
-- Name: gst_registration_documents trg_set_verified_timestamp; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_set_verified_timestamp BEFORE UPDATE ON solvetax.gst_registration_documents FOR EACH ROW EXECUTE FUNCTION solvetax.set_verified_timestamp();


--
-- Name: gst_filings trg_sync_gst_reg_status_to_filings; Type: TRIGGER; Schema: solvetax; Owner: -
--

CREATE TRIGGER trg_sync_gst_reg_status_to_filings BEFORE INSERT OR UPDATE OF gst_registration_id ON solvetax.gst_filings FOR EACH ROW EXECUTE FUNCTION solvetax.fn_sync_gst_reg_status_to_filings();


--
-- Name: crm_activities crm_activities_call_status_entity_code_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_activities
    ADD CONSTRAINT crm_activities_call_status_entity_code_fkey FOREIGN KEY (entity_type, call_status_code) REFERENCES solvetax.crm_call_statuses(entity_type, code);


--
-- Name: crm_activities crm_activities_call_type_entity_code_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_activities
    ADD CONSTRAINT crm_activities_call_type_entity_code_fkey FOREIGN KEY (entity_type, call_type_code) REFERENCES solvetax.crm_call_types(entity_type, code);


--
-- Name: crm_activities crm_activities_performed_by_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_activities
    ADD CONSTRAINT crm_activities_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES solvetax.employees(emp_id);


--
-- Name: crm_bulk_assign_logs crm_bulk_assign_logs_scheduler_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_bulk_assign_logs
    ADD CONSTRAINT crm_bulk_assign_logs_scheduler_id_fkey FOREIGN KEY (scheduler_id) REFERENCES solvetax.crm_bulk_assign_schedulers(id) ON DELETE SET NULL;


--
-- Name: customers customers_op_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customers
    ADD CONSTRAINT customers_op_id_fkey FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: customers customers_rm_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customers
    ADD CONSTRAINT customers_rm_id_fkey FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: employee_email_verifications employee_email_verifications_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_email_verifications
    ADD CONSTRAINT employee_email_verifications_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: employee_roles employee_roles_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_roles
    ADD CONSTRAINT employee_roles_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE CASCADE;


--
-- Name: employee_roles employee_roles_role_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_roles
    ADD CONSTRAINT employee_roles_role_id_fkey FOREIGN KEY (role_id) REFERENCES solvetax.roles(id) ON DELETE CASCADE;


--
-- Name: employee_tasks employee_tasks_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employee_tasks
    ADD CONSTRAINT employee_tasks_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: crm_leads fk_crm_leads_op; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_leads
    ADD CONSTRAINT fk_crm_leads_op FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: crm_leads fk_crm_leads_rm; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_leads
    ADD CONSTRAINT fk_crm_leads_rm FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: crm_rm_op_mappings fk_crm_rm_op_op; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_rm_op_mappings
    ADD CONSTRAINT fk_crm_rm_op_op FOREIGN KEY (op_emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE CASCADE;


--
-- Name: crm_rm_op_mappings fk_crm_rm_op_rm; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.crm_rm_op_mappings
    ADD CONSTRAINT fk_crm_rm_op_rm FOREIGN KEY (rm_emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE CASCADE;


--
-- Name: customer_services fk_customer_services_customer; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_services
    ADD CONSTRAINT fk_customer_services_customer FOREIGN KEY (customer_id) REFERENCES solvetax.customers(customer_id);


--
-- Name: customer_services fk_customer_services_op; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_services
    ADD CONSTRAINT fk_customer_services_op FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: customer_services fk_customer_services_rm; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.customer_services
    ADD CONSTRAINT fk_customer_services_rm FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: employees fk_employees_manager; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.employees
    ADD CONSTRAINT fk_employees_manager FOREIGN KEY (manager_emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: gst_filings_documents fk_gst_filing_documents_filing; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings_documents
    ADD CONSTRAINT fk_gst_filing_documents_filing FOREIGN KEY (gst_filing_id) REFERENCES solvetax.gst_filings(id) ON DELETE CASCADE;


--
-- Name: gst_filings_documents fk_gst_filing_documents_verified_by; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings_documents
    ADD CONSTRAINT fk_gst_filing_documents_verified_by FOREIGN KEY (verified_by) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: gst_filing_return_details fk_gst_filing_return_details; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filing_return_details
    ADD CONSTRAINT fk_gst_filing_return_details FOREIGN KEY (gst_filing_id) REFERENCES solvetax.gst_filings(id) ON DELETE CASCADE;


--
-- Name: gst_filings fk_gst_filings_op; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings
    ADD CONSTRAINT fk_gst_filings_op FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: gst_filings fk_gst_filings_rm; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings
    ADD CONSTRAINT fk_gst_filings_rm FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: gst_filings fk_gst_filings_service; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_filings
    ADD CONSTRAINT fk_gst_filings_service FOREIGN KEY (service_id) REFERENCES solvetax.service_config(id);


--
-- Name: income_tax fk_income_tax_op; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax
    ADD CONSTRAINT fk_income_tax_op FOREIGN KEY (op_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: income_tax fk_income_tax_rm; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.income_tax
    ADD CONSTRAINT fk_income_tax_rm FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- Name: password_reset_otps fk_password_reset_employee; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.password_reset_otps
    ADD CONSTRAINT fk_password_reset_employee FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE CASCADE;


--
-- Name: gst_registration gst_registration_created_by_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration
    ADD CONSTRAINT gst_registration_created_by_fkey FOREIGN KEY (created_by) REFERENCES solvetax.employees(emp_id);


--
-- Name: gst_registration gst_registration_rm_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration
    ADD CONSTRAINT gst_registration_rm_id_fkey FOREIGN KEY (rm_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: issue_reports issue_reports_reporter_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.issue_reports
    ADD CONSTRAINT issue_reports_reporter_emp_id_fkey FOREIGN KEY (reporter_emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: issue_reports issue_reports_resolved_by_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.issue_reports
    ADD CONSTRAINT issue_reports_resolved_by_emp_id_fkey FOREIGN KEY (resolved_by_emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: gst_registration_documents registration_documents_person_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_documents
    ADD CONSTRAINT registration_documents_person_id_fkey FOREIGN KEY (person_id) REFERENCES solvetax.gst_registration_persons(person_id) ON DELETE CASCADE;


--
-- Name: gst_registration_documents registration_documents_verified_by_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.gst_registration_documents
    ADD CONSTRAINT registration_documents_verified_by_fkey FOREIGN KEY (verified_by) REFERENCES solvetax.employees(emp_id);


--
-- Name: role_features role_features_feature_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.role_features
    ADD CONSTRAINT role_features_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES solvetax.features(id) ON DELETE CASCADE;


--
-- Name: role_features role_features_role_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.role_features
    ADD CONSTRAINT role_features_role_id_fkey FOREIGN KEY (role_id) REFERENCES solvetax.roles(id) ON DELETE CASCADE;


--
-- Name: session_audit_log session_audit_log_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_audit_log
    ADD CONSTRAINT session_audit_log_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: session_token session_token_emp_id_fkey; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.session_token
    ADD CONSTRAINT session_token_emp_id_fkey FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id);


--
-- Name: versions versions_emp_fk; Type: FK CONSTRAINT; Schema: solvetax; Owner: -
--

ALTER TABLE ONLY solvetax.versions
    ADD CONSTRAINT versions_emp_fk FOREIGN KEY (emp_id) REFERENCES solvetax.employees(emp_id) ON DELETE SET NULL;


--
-- PostgreSQL database dump complete
--
