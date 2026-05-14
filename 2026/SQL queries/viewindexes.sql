SELECT
  t.relname  AS table_name,
  i.relname  AS index_name,
  a.attname  AS column_name,
  ix.indisunique AS is_unique,
  ix.indisprimary AS is_primary
FROM pg_class t
JOIN pg_index ix       ON t.oid = ix.indrelid
JOIN pg_class i        ON i.oid = ix.indexrelid
JOIN pg_attribute a   ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relname = 'rawform_form_items'
ORDER BY index_name, a.attnum;
