-- Recorded findings across ALL dispositions, including quarantine and repeats.
-- Count occurrences separately from distinct audit IDs, not source row numbers.
-- A record can appear in multiple groups: affected_records is not additive.
WITH findings AS (
    SELECT r.audit_record_id, r.disposition,
           json_extract(j.value, '$.code') AS code,
           json_extract(j.value, '$.severity') AS severity
    FROM raw_records AS r
    CROSS JOIN json_each(r.issues_json) AS j
)
SELECT code, severity,
       COUNT(*) AS occurrences,
       COUNT(DISTINCT audit_record_id) AS affected_records,
       COUNT(DISTINCT CASE WHEN disposition = 'accepted'
                           THEN audit_record_id END) AS affected_accepted_records,
       COUNT(DISTINCT CASE WHEN disposition = 'quarantined'
                           THEN audit_record_id END) AS affected_quarantined_records,
       COUNT(DISTINCT CASE WHEN disposition = 'duplicates'
                           THEN audit_record_id END) AS affected_duplicate_records
FROM findings
GROUP BY code, severity
ORDER BY code, severity;
