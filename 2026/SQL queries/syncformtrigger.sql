
DROP TRIGGER IF EXISTS trg_sync_rawform_form_items ON rawform_forms;

CREATE TRIGGER trg_sync_rawform_form_items
AFTER INSERT OR UPDATE OF studentdata, assessordata, role, clinic,
                          studentnumber, datetimeutc, cohort, subject, type,
                          submitted_by_student, submitted_by_assessor,
                          time_mgmt, entrustment, professionalism, communication, patient_complexity
ON rawform_forms
FOR EACH ROW
EXECUTE FUNCTION sync_rawform_form_items();