-- Database: MDS_DASH

-- DROP DATABASE IF EXISTS "MDS_DASH";

CREATE DATABASE "MDS_DASH"
    WITH
    OWNER = postgres
    ENCODING = 'UTF8'
    LC_COLLATE = 'English_Australia.1252'
    LC_CTYPE = 'English_Australia.1252'
    LOCALE_PROVIDER = 'libc'
    TABLESPACE = pg_default
    CONNECTION LIMIT = -1
    IS_TEMPLATE = False;

COMMENT ON DATABASE "MDS_DASH"
    IS 'Database for the MDS Dashboard';

CREATE TABLE mds_raw_data (
    assessment_id      INTEGER PRIMARY KEY,
    student_name       TEXT,
    student_number     INTEGER,
    assessor_name      TEXT,
    date               DATE,
    cohort             TEXT,
    subject            TEXT,
    type               TEXT,
    student_role       TEXT,
    clinic_type        TEXT,
    patient_age        INTEGER,
    patient_drn        TEXT,
    patient_status     TEXT,
    teeth_quadrant_info TEXT,
    student_submitted  BOOLEAN,
    assessor_submitted BOOLEAN,
    time_mgmt          NUMERIC,
    entrustment        NUMERIC,
    communication      NUMERIC,
    professionalism    NUMERIC,
    assessor_feedback  TEXT,
    clinical_incident  BOOLEAN,
    patient_complexity TEXT,
    student_feedback   TEXT,
    student_data       JSONB,
    supervisor_data    JSONB,
    created_at         TIMESTAMPTZ DEFAULT now()
);
