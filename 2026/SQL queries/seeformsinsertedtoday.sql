SELECT *
FROM rawForms
-- FROM rawform_forms
WHERE insertedAt >= date_trunc('year', now())
ORDER BY insertedAt DESC;
