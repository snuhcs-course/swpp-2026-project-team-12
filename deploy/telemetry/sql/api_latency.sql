-- GoogleSQL. Replace PROJECT_ID.analytics_PROPERTY_ID; query exported production events.
WITH decoded AS (
  SELECT
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='event_id') AS event_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='environment') AS environment,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='route') AS route,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='method') AS method,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='result') AS result,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key='duration_ms') AS duration_ms,
    event_timestamp
  FROM `PROJECT_ID.analytics_PROPERTY_ID.events_*`
  WHERE event_name='api_result'
    AND _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d',DATE_SUB(CURRENT_DATE('Asia/Seoul'),INTERVAL 7 DAY))
      AND FORMAT_DATE('%Y%m%d',CURRENT_DATE('Asia/Seoul'))
), deduplicated AS (
  SELECT * FROM decoded WHERE environment='production' AND event_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY event_timestamp)=1
)
SELECT DISTINCT route, method, result,
  COUNT(*) OVER (PARTITION BY route,method,result) AS attempts,
  PERCENTILE_DISC(duration_ms,0.50) OVER (PARTITION BY route,method,result) AS p50_ms,
  PERCENTILE_DISC(duration_ms,0.95) OVER (PARTITION BY route,method,result) AS p95_ms
FROM deduplicated ORDER BY p95_ms DESC;
