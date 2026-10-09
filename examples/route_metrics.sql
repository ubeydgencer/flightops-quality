-- Accepted UNIQUE records only. NULL delays are excluded, never imputed as zero.
-- These are data-quality cohort metrics, not a published airline ranking.
SELECT origin, destination,
       COUNT(*) AS accepted_flights,
       SUM(cancelled) AS cancelled,
       SUM(diverted) AS diverted,
       SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes IS NOT NULL
                THEN 1 ELSE 0 END) AS otp_eligible,
       SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes < 15
                THEN 1 ELSE 0 END) AS otp_on_time,
       SUM(CASE WHEN cancelled = 0 AND diverted = 0 THEN 1 ELSE 0 END)
           AS arrival_coverage_population,
       SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes IS NULL
                THEN 1 ELSE 0 END) AS missing_arrival_delay,
       100.0 * SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes IS NOT NULL
                        THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN cancelled = 0 AND diverted = 0 THEN 1 ELSE 0 END), 0)
           AS arrival_delay_coverage_percent,
       100.0 * SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes < 15
                        THEN 1 ELSE 0 END)
       / NULLIF(SUM(CASE WHEN cancelled = 0 AND diverted = 0 AND arrival_delay_minutes IS NOT NULL
                        THEN 1 ELSE 0 END), 0) AS arrival_otp_15_completed_percent
FROM flights
GROUP BY origin, destination
ORDER BY origin, destination;
