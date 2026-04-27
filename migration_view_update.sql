-- ========================================================
-- v_admin_applications 뷰 업데이트
-- 새 컬럼 (프리카스, 환경조사, 재량점수) 반영
-- Supabase SQL Editor에서 실행하세요
-- ========================================================

-- 1. selection_consideration 상태값 허용 (check constraint 있을 경우)
-- ─────────────────────────────────────────────────────────
ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_status_check;
ALTER TABLE applications ADD CONSTRAINT applications_status_check
  CHECK (status IN (
    'submitted',
    'under_review',
    'docs_requested',
    'reviewed',
    'excluded',
    'selected',
    'selection_consideration'
  ));


-- 2. 뷰 재생성 (새 컬럼 포함)
-- ─────────────────────────────────────────────────────────
DROP VIEW IF EXISTS v_admin_applications;
CREATE VIEW v_admin_applications AS
WITH latest_review AS (
  SELECT DISTINCT ON (cpo_reviews.application_id)
    cpo_reviews.id                  AS review_id,
    cpo_reviews.application_id,
    cpo_reviews.reviewer_id,
    cpo_reviews.station_id          AS review_station_id,
    cpo_reviews.review_result,
    cpo_reviews.cpo_risk_label,
    cpo_reviews.cpo_risk_score,
    cpo_reviews.is_excluded,
    cpo_reviews.exclude_reason,
    cpo_reviews.review_comment,
    cpo_reviews.docs_request_comment,
    cpo_reviews.reviewed_at,
    cpo_reviews.created_at          AS review_created_at,
    -- ▼ 신규: 프리카스 격자 데이터
    cpo_reviews.precas_112_count,
    cpo_reviews.precas_risk_grade,
    cpo_reviews.precas_patrol_count,
    -- ▼ 신규: CPO 현장 환경조사
    cpo_reviews.field_neighborhood_type,
    cpo_reviews.field_location_type,
    cpo_reviews.field_lighting,
    cpo_reviews.field_police_distance,
    cpo_reviews.field_vulnerable_facilities,
    cpo_reviews.field_public_cctv,
    cpo_reviews.field_foot_traffic,
    cpo_reviews.field_building_condition,
    -- ▼ 신규: CPO 재량점수
    cpo_reviews.cpo_discretionary_score,
    cpo_reviews.cpo_discretionary_reason
  FROM cpo_reviews
  ORDER BY cpo_reviews.application_id, cpo_reviews.reviewed_at DESC, cpo_reviews.id DESC
)
SELECT
  a.id              AS application_id,
  a.submitted_at,
  a.created_at,
  a.updated_at,
  a.status          AS application_status,
  COALESCE(lr.review_result, a.status) AS current_status,
  a.station_id,
  s.station_name,
  s.station_label,
  s.area_name,
  a.applicant_name,
  a.business_name,
  a.business_type,
  a.business_type_other,
  a.phone,
  a.email,
  a.address_road,
  a.address_jibun,
  a.address_detail,
  TRIM(BOTH FROM (
    COALESCE(a.address_road, '') ||
    CASE
      WHEN COALESCE(a.address_detail, '') <> '' THEN ', ' || a.address_detail
      ELSE ''
    END
  )) AS full_address,
  a.latitude,
  a.longitude,
  a.annual_sales,
  a.sales_band,
  a.has_cctv,
  a.has_emergency_bell,
  a.uses_security_company,
  a.other_security,
  a.apply_reason,
  a.requested_item,
  a.etc_note,
  a.survey_crime_anxiety,
  a.survey_late_night,
  a.survey_dark_area,
  a.survey_single_worker,
  calc_felt_safety_score(
    a.survey_crime_anxiety, a.survey_late_night,
    a.survey_dark_area, a.survey_single_worker
  ) AS felt_safety_score,
  calc_security_vulnerability_score(
    a.has_cctv, a.uses_security_company
  ) AS security_vulnerability_score,
  -- 리뷰 기본 정보
  lr.review_id,
  lr.reviewer_id,
  lr.review_station_id,
  lr.review_result,
  lr.cpo_risk_label,
  COALESCE(lr.cpo_risk_score, 0)     AS cpo_risk_score,
  COALESCE(lr.is_excluded, false)    AS is_excluded,
  lr.exclude_reason,
  lr.review_comment,
  lr.docs_request_comment,
  lr.reviewed_at,
  -- ▼ 신규: 프리카스
  lr.precas_112_count,
  lr.precas_risk_grade,
  lr.precas_patrol_count,
  -- ▼ 신규: 현장 환경조사
  lr.field_neighborhood_type,
  lr.field_location_type,
  lr.field_lighting,
  lr.field_police_distance,
  lr.field_vulnerable_facilities,
  lr.field_public_cctv,
  lr.field_foot_traffic,
  lr.field_building_condition,
  -- ▼ 신규: 재량점수
  COALESCE(lr.cpo_discretionary_score, 0) AS cpo_discretionary_score,
  lr.cpo_discretionary_reason,
  -- 기존 총점 (하위 호환)
  (
    calc_felt_safety_score(a.survey_crime_anxiety, a.survey_late_night, a.survey_dark_area, a.survey_single_worker)
    + calc_security_vulnerability_score(a.has_cctv, a.uses_security_company)
    + COALESCE(lr.cpo_risk_score, 0)
  ) AS total_score
FROM applications a
LEFT JOIN stations s ON a.station_id = s.id
LEFT JOIN latest_review lr ON a.id = lr.application_id;
