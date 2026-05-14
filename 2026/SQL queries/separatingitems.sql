INSERT INTO rawform_form_items (
  form_code, item_code,
  assessmentid, studentnumber, studentname, datetimeutc, cohort, subject, type,
  role, clinic,
  student_item_data, assessor_item_data
)
SELECT
  f.form_code,
  k.item_code,
  f.assessmentid, f.studentnumber, f.studentname, f.datetimeutc, f.cohort, f.subject, f.type,
  f.role, f.clinic,
  f.studentdata -> k.item_code,
  f.assessordata -> k.item_code
FROM rawform_forms f
CROSS JOIN LATERAL (
  SELECT key AS item_code
  FROM jsonb_object_keys(COALESCE(f.studentdata, '{}'::jsonb)) AS key

  UNION

  SELECT key AS item_code
  FROM jsonb_object_keys(COALESCE(f.assessordata, '{}'::jsonb)) AS key
) k
ON CONFLICT (assessmentid, form_code, item_code) DO UPDATE SET
  assessmentid = EXCLUDED.assessmentid,
  studentnumber = EXCLUDED.studentnumber,
  studentname = EXCLUDED.studentname,
  datetimeutc = EXCLUDED.datetimeutc,
  cohort = EXCLUDED.cohort,
  subject = EXCLUDED.subject,
  type = EXCLUDED.type,
  role = EXCLUDED.role,
  clinic = EXCLUDED.clinic,
  student_item_data = EXCLUDED.student_item_data,
  assessor_item_data = EXCLUDED.assessor_item_data;
