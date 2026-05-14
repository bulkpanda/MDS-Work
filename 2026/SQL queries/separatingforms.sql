CREATE TABLE IF NOT EXISTS rawform_forms (
  form_code TEXT NOT NULL,
  assessmentid BIGINT NOT NULL,

  studentnumber BIGINT,
  studentname TEXT,
  datetimeutc TIMESTAMPTZ,
  cohort TEXT,
  subject TEXT,
  type TEXT,
  completed BOOLEAN,

  studentdata JSONB,
  assessordata JSONB,

  student_reflection TEXT,
  assessor_reflection TEXT,
  clinicalincident TEXT,

  patient_complexity TEXT,

  role TEXT,
  clinic TEXT,
  scales JSONB,
  checklists JSONB,
  version INTEGER,

  patient_age INTEGER,
  patient_drn TEXT,
  assessor_name TEXT,
  patient_details TEXT,
  patient_interpreter BOOLEAN,

  submitted_by_student BOOLEAN,
  additional_checklists JSONB,
  submitted_by_assessor BOOLEAN,

  insertedat TIMESTAMPTZ DEFAULT now(),

  PRIMARY KEY (form_code, assessmentid)
);


INSERT INTO rawform_forms (
  form_code,
  assessmentid, student_number, student_name, datetimeutc, cohort, subject, type, completed,
  student_data, assessor_data,
  student_reflection, assessor_reflection,
  clinicalincident,
  -- time_mgmt, professionalism, communication, entrustment,
  patient_complexity,
  role, clinic, scales, checklists, version,
  patient_age, patient_drn, assessor_name, patient_details, patient_interpreter,
  submitted_by_student, additional_checklists, submitted_by_assessor
)
SELECT
  f.form_code,

  r.assessmentid, r.studentnumber, r.studentname, r.datetimeutc, r.cohort, r.subject, r.type, r.completed,

  /* studentdata: remove reflection only */
  (studentJson - 'reflection') AS studentdata,

  /* assessordata: remove extracted keys */
  (assessorJson
    - 'reflection'
    -- - 'time_mgmt'
    -- - 'professionalism'
    -- - 'communication'
    -- - 'entrustment'
    - 'patient_complexity'
	- 'clinical_incident'
  ) AS assessordata,

  /* reflections */
  (studentJson->>'reflection')  AS student_reflection,
  (assessorJson->>'reflection') AS assessor_reflection,
 /* put this exactly where clinicalincident is in INSERT */
  NULLIF(COALESCE(assessorJson->>'critical_incident', assessorJson->>'clinical_incident'), '') AS clinicalincident,

  /* extracted scalars (no assessor_ prefix) */
  -- NULLIF(assessorJson->'time_mgmt'->>'scale','')::smallint       AS time_mgmt,
  -- NULLIF(assessorJson->'professionalism'->>'scale','')::smallint AS professionalism,
  -- NULLIF(assessorJson->'communication'->>'scale','')::smallint   AS communication,
  -- NULLIF(assessorJson->'entrustment'->>'scale','')::smallint     AS entrustment,
  (assessorJson->'patient_complexity'->>'scale')                 AS patient_complexity,

  f.form_value->>'role' AS role,
  COALESCE(f.form_value->>'clinic_type', f.form_value->>'clinic') AS clinic,
  f.form_value->'scales' AS scales,
  f.form_value->'checklists' AS checklists,
  NULLIF(f.form_value->>'version','')::int AS version,

  NULLIF(f.form_value->>'patient_age','')::int AS patient_age,
  NULLIF(f.form_value->>'patient_drn','') AS patient_drn,
  f.form_value->>'assessor_name' AS assessor_name,
  f.form_value->>'patient_details' AS patient_details,
  (f.form_value->>'patient_interpreter')::boolean AS patient_interpreter,

  (f.form_value->>'submitted_by_student')::boolean AS submitted_by_student,
  f.form_value->'additional_checklists' AS additional_checklists,
  (f.form_value->>'submitted_by_assessor')::boolean AS submitted_by_assessor
FROM rawforms r
CROSS JOIN LATERAL (
  SELECT e.key AS form_code, e.value AS form_value
  FROM jsonb_each(r.forms) e
  WHERE jsonb_typeof(r.forms) = 'object'
  UNION ALL
  SELECT a.value->>'form_key' AS form_code, a.value AS form_value
  FROM jsonb_array_elements(r.forms) a
  WHERE jsonb_typeof(r.forms) = 'array'
) f
CROSS JOIN LATERAL (
  SELECT
    COALESCE(f.form_value->'student_data',  f.form_value->'data'->'student')  AS studentJson,
    COALESCE(f.form_value->'assessor_data', f.form_value->'data'->'assessor') AS assessorJson
) j
WHERE f.form_code IS NOT NULL
ON CONFLICT (assessmentid, form_code) DO NOTHING;
