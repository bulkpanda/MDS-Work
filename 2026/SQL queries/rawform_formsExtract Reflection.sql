UPDATE rawform_forms
SET
  student_reflection  = studentdata->>'reflection',
  assessor_reflection = assessordata->>'reflection'
WHERE
  student_reflection IS NULL
  OR assessor_reflection IS NULL;

UPDATE rawform_forms
SET
  studentdata  = studentdata  - 'reflection',
  assessordata = assessordata - 'reflection';
