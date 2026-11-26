-- GoogleSQL. Replace PROJECT_ID and kr_talkdock_app_ANDROID with the production app tables.
-- The default cohort is the last 7 complete Korean calendar days. Rerun after late exports.
DECLARE date_end DATE DEFAULT CURRENT_DATE('Asia/Seoul');
DECLARE date_start DATE DEFAULT DATE_SUB(date_end, INTERVAL 7 DAY);
WITH sessions AS (
  SELECT session_id, MIN(event_timestamp) AS started_at
  FROM `PROJECT_ID.firebase_sessions.kr_talkdock_app_ANDROID`
  WHERE event_type = 'SESSION_START'
    AND crashlytics_data_collection_enabled = TRUE
    AND SAFE_CAST(SPLIT(operating_system.display_version, '.')[SAFE_OFFSET(0)] AS INT64) >= 11
  GROUP BY session_id
), cohort AS (
  SELECT * FROM sessions
  WHERE DATE(started_at, 'Asia/Seoul') >= date_start
    AND DATE(started_at, 'Asia/Seoul') < date_end
), anrs AS (
  SELECT DISTINCT firebase_session_id
  FROM `PROJECT_ID.firebase_crashlytics.kr_talkdock_app_ANDROID`
  WHERE error_type = 'ANR'
), totals AS (
  SELECT COUNT(*) AS sessions, COUNTIF(a.firebase_session_id IS NOT NULL) AS anr_sessions
  FROM cohort s LEFT JOIN anrs a ON s.session_id = a.firebase_session_id
)
SELECT date_start, date_end, sessions, anr_sessions,
  ROUND(100 * SAFE_DIVIDE(anr_sessions, sessions), 2) AS anr_percent,
  CASE WHEN sessions = 0 THEN '데이터 없음'
       WHEN SAFE_DIVIDE(anr_sessions, sessions) >= 0.01 THEN '목표 미달'
       ELSE '목표 충족' END AS target,
  (SELECT COUNT(*) FROM `PROJECT_ID.firebase_crashlytics.kr_talkdock_app_ANDROID` c
   WHERE error_type='ANR' AND DATE(event_timestamp,'Asia/Seoul') >= date_start
     AND DATE(event_timestamp,'Asia/Seoul') < date_end
     AND NOT EXISTS (SELECT 1 FROM sessions s WHERE s.session_id=c.firebase_session_id)) AS unmatched_anr_events
FROM totals;
