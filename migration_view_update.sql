BEGIN;

DROP VIEW IF EXISTS public.v_admin_applications;

ALTER TABLE public.cpo_reviews
    ADD COLUMN IF NOT EXISTS public_cctv_count integer;

ALTER TABLE public.cpo_reviews
    ALTER COLUMN cpo_risk_score TYPE integer
    USING COALESCE(NULLIF(TRIM(cpo_risk_score::text), ''), '0')::numeric::integer;

ALTER TABLE public.cpo_reviews
    ALTER COLUMN cpo_discretionary_score TYPE integer
    USING COALESCE(NULLIF(TRIM(cpo_discretionary_score::text), ''), '0')::numeric::integer;

UPDATE public.cpo_reviews
SET
    cpo_risk_score = GREATEST(COALESCE(cpo_risk_score, 0), 0),
    cpo_discretionary_score = LEAST(GREATEST(COALESCE(cpo_discretionary_score, 0), 0), 10)
WHERE cpo_risk_score IS NULL
   OR cpo_risk_score < 0
   OR cpo_discretionary_score IS NULL
   OR cpo_discretionary_score < 0
   OR cpo_discretionary_score > 10;

ALTER TABLE public.cpo_reviews
    ALTER COLUMN cpo_risk_score SET DEFAULT 0,
    ALTER COLUMN cpo_risk_score SET NOT NULL,
    ALTER COLUMN cpo_discretionary_score SET DEFAULT 0,
    ALTER COLUMN cpo_discretionary_score SET NOT NULL;

CREATE VIEW public.v_admin_applications AS
WITH latest_review AS (
    SELECT DISTINCT ON (r.application_id)
        r.id AS review_id,
        r.application_id,
        r.reviewer_id,
        r.station_id AS review_station_id,
        r.review_result,
        r.cpo_risk_label,
        r.cpo_risk_score,
        r.is_excluded,
        r.exclude_reason,
        r.review_comment,
        r.docs_request_comment,
        r.reviewed_at,
        r.created_at AS review_created_at,
        r.precas_112_count,
        r.precas_risk_grade,
        r.precas_patrol_count,
        r.public_cctv_count,
        r.field_neighborhood_type,
        r.field_location_type,
        r.field_lighting,
        r.field_police_distance,
        r.field_vulnerable_facilities,
        r.field_foot_traffic,
        r.field_building_condition,
        r.cpo_discretionary_score,
        r.cpo_discretionary_reason
    FROM public.cpo_reviews r
    ORDER BY r.application_id, r.reviewed_at DESC, r.id DESC
)
SELECT
    a.id AS application_id,
    a.submitted_at,
    a.created_at,
    a.updated_at,
    a.status AS application_status,
    COALESCE(lr.review_result, a.status) AS current_status,
    a.station_id,
    s.station_label AS station_name,
    s.station_label,
    REPLACE(COALESCE(s.station_label, ''), '경찰서', '') AS area_name,
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
    a.safe_feel_1,
    a.safe_feel_2,
    a.safe_feel_3,
    a.safe_feel_4,
    a.safe_feel_5,
    calc_felt_safety_score(
        a.survey_crime_anxiety,
        a.survey_late_night,
        a.survey_dark_area,
        a.survey_single_worker
    ) AS felt_safety_score,
    calc_security_vulnerability_score(
        a.has_cctv,
        a.uses_security_company
    ) AS security_vulnerability_score,
    lr.review_id,
    lr.reviewer_id,
    lr.review_station_id,
    lr.review_result,
    lr.cpo_risk_label,
    COALESCE(lr.cpo_risk_score, 0) AS cpo_risk_score,
    COALESCE(lr.is_excluded, false) AS is_excluded,
    lr.exclude_reason,
    lr.review_comment,
    lr.docs_request_comment,
    lr.reviewed_at,
    lr.review_created_at,
    lr.precas_112_count,
    lr.precas_risk_grade,
    lr.precas_patrol_count,
    lr.public_cctv_count,
    lr.field_neighborhood_type,
    lr.field_location_type,
    lr.field_lighting,
    lr.field_police_distance,
    lr.field_vulnerable_facilities,
    lr.field_foot_traffic,
    lr.field_building_condition,
    COALESCE(lr.cpo_discretionary_score, 0) AS cpo_discretionary_score,
    lr.cpo_discretionary_reason,
    (
        calc_felt_safety_score(
            a.survey_crime_anxiety,
            a.survey_late_night,
            a.survey_dark_area,
            a.survey_single_worker
        )
        + calc_security_vulnerability_score(
            a.has_cctv,
            a.uses_security_company
        )
        + COALESCE(lr.cpo_risk_score, 0)
        + COALESCE(lr.cpo_discretionary_score, 0)
    ) AS total_score
FROM public.applications a
LEFT JOIN public.stations s
    ON a.station_id = s.id
LEFT JOIN latest_review lr
    ON a.id = lr.application_id;

COMMIT;
