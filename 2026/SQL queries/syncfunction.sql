CREATE OR REPLACE FUNCTION sync_rawform_forms()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  DELETE FROM rawform_forms
  WHERE assessmentid = NEW.assessmentid;

  INSERT INTO rawform_forms (
    assessmentid, form_code,
    studentnumber, datetimeutc, cohort, subject, type, completed,

    studentdata, assessordata,
    student_reflection, assessor_reflection,

    assessor_time_mgmt, assessor_professionalism, assessor_communication, assessor_entrustment,
    assessor_patient_complexity,

    role, clinic, scales, checklists, version,
    patient_age, patient_drn, assessor_name, patient_details, patient_interpreter,
    submitted_by_student, additional_checklists, submitted_by_assessor
  )
  SELECT
    NEW.assessmentid,
    f.key,
    NEW.studentnumber, NEW.datetimeutc, NEW.cohort, NEW.subject, NEW.type, NEW.completed,

    studentJson,
    assessorJson
      - 'reflection'
      - 'time_mgmt'
      - 'professionalism'
      - 'communication'
      - 'entrustment'
      - 'patient_complexity',

    (studentJson  ->> 'reflection') AS student_reflection,
    (assessorJson ->> 'reflection') AS assessor_reflection,

    NULLIF(assessorJson->'time_mgmt'->>'scale','')::smallint,
    NULLIF(assessorJson->'professionalism'->>'scale','')::smallint,
    NULLIF(assessorJson->'communication'->>'scale','')::smallint,
    NULLIF(assessorJson->'entrustment'->>'scale','')::smallint,
    (assessorJson->'patient_complexity'->>'scale') AS assessor_patient_complexity,

    f.value->>'role',
    f.value->>'clinic',
    f.value->'scales',
    f.value->'checklists',
    NULLIF(f.value->>'version','')::int,
    NULLIF(f.value->>'patient_age','')::int,
    f.value->>'patient_drn',
    f.value->>'assessor_name',
    f.value->>'patient_details',
    f.value->>'patient_interpreter',
    (f.value->>'submitted_by_student')::boolean,
    f.value->'additional_checklists',
    (f.value->>'submitted_by_assessor')::boolean
  FROM jsonb_each(NEW.forms) AS f(key, value)
  CROSS JOIN LATERAL (SELECT f.value->'data'->'student')  AS s(studentJson)
  CROSS JOIN LATERAL (SELECT f.value->'data'->'assessor') AS a(assessorJson);

  RETURN NEW;
END;
$$;
