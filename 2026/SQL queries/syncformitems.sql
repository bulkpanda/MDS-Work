CREATE OR REPLACE FUNCTION sync_rawform_form_items()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  DELETE FROM rawform_form_items
  WHERE assessmentid = NEW.assessmentid
    AND form_code = NEW.form_code;

  INSERT INTO rawform_form_items (
    assessmentid, form_code, item_code,
    studentnumber, datetimeutc, cohort, subject, type,
    role, clinic,
    student_item_data, assessor_item_data,
    submitted_by_student, submitted_by_assessor,
    time_mgmt, entrustment, professionalism, communication, patient_complexity
  )
  SELECT
    NEW.assessmentid,
    NEW.form_code,
    k.item_code,

    NEW.studentnumber, NEW.datetimeutc, NEW.cohort, NEW.subject, NEW.type,
    NEW.role, NEW.clinic,

    COALESCE(NEW.studentdata, '{}'::jsonb) -> k.item_code,
    COALESCE(NEW.assessordata, '{}'::jsonb) -> k.item_code,

    NEW.submitted_by_student,
    NEW.submitted_by_assessor,

    NEW.time_mgmt,
    NEW.entrustment,
    NEW.professionalism,
    NEW.communication,
    NEW.patient_complexity
  FROM (
    SELECT key AS item_code
    FROM jsonb_object_keys(COALESCE(NEW.studentdata, '{}'::jsonb)) AS key
    UNION
    SELECT key AS item_code
    FROM jsonb_object_keys(COALESCE(NEW.assessordata, '{}'::jsonb)) AS key
  ) k;

  RETURN NEW;
END;
$$;


