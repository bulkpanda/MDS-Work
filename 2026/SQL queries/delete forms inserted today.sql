DELETE FROM rawForm_forms
WHERE insertedAt >= date_trunc('day', now());