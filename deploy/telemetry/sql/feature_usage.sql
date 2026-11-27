-- GoogleSQL. Replace PROJECT_ID.analytics_PROPERTY_ID with the exported Analytics dataset.
-- Source window includes later completions; always recompute recent cohorts after daily exports.
WITH decoded AS (
  SELECT event_name, TIMESTAMP_MICROS(event_timestamp) AS timestamp,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='event_id') AS event_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='operation_id') AS operation_id,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='feature') AS feature,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='stage') AS stage,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='result') AS result,
    (SELECT value.string_value FROM UNNEST(event_params) WHERE key='environment') AS environment,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key='duration_ms') AS duration_ms
  FROM `PROJECT_ID.analytics_PROPERTY_ID.events_*`
  WHERE _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d',DATE_SUB(CURRENT_DATE('Asia/Seoul'),INTERVAL 30 DAY))
    AND FORMAT_DATE('%Y%m%d',CURRENT_DATE('Asia/Seoul'))
    AND event_name IN ('feature_used','feature_stage','api_result')
), deduplicated AS (
  SELECT * FROM decoded WHERE environment='production' AND event_id IS NOT NULL
  QUALIFY ROW_NUMBER() OVER (PARTITION BY event_id ORDER BY timestamp)=1
), operations AS (
  SELECT feature, operation_id,
    MIN(IF(event_name='feature_used',timestamp,NULL)) AS started_at,
    MIN(IF(event_name='feature_stage' AND result='success' AND stage = CASE feature
      WHEN 'photo_post' THEN 'feed_shown' WHEN 'family_history' THEN 'screen_shown'
      WHEN 'post_qa' THEN 'screen_shown' WHEN 'daily_question' THEN 'answer_shown'
      WHEN 'family_join' THEN 'room_shown' WHEN 'notification_open' THEN 'destination_shown'
      WHEN 'app_start' THEN 'first_feed_shown' WHEN 'read_aloud' THEN 'playback_completed'
      WHEN 'voice_reply' THEN 'server_saved' WHEN 'text_reply' THEN 'server_saved' END,
      timestamp,NULL)) AS completed_at,
    COUNTIF(event_name='api_result') AS api_attempts
  FROM deduplicated WHERE operation_id IS NOT NULL
  GROUP BY feature, operation_id
)
SELECT DATE(started_at,'Asia/Seoul') AS started_date, feature,
  COUNT(*) AS starts, COUNTIF(completed_at IS NOT NULL) AS completions,
  COUNTIF(completed_at IS NULL) AS incomplete,
  SAFE_DIVIDE(COUNTIF(completed_at IS NOT NULL),COUNT(*)) AS completion_rate,
  SUM(api_attempts) AS api_attempts
FROM operations WHERE started_at IS NOT NULL
GROUP BY started_date, feature ORDER BY started_date DESC, feature;
