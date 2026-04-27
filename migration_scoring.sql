-- ========================================================
-- 소상공인 안전물품 지원 관리시스템 - 점수 체계 마이그레이션
-- 실행 위치: Supabase SQL Editor
-- ========================================================

-- 1. cpo_reviews 테이블에 새 컬럼 추가
-- ─────────────────────────────────────────────────────────

-- 프리카스 격자 데이터
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS precas_112_count    INTEGER;
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS precas_risk_grade   INTEGER;  -- 1(최위험)~9(안전)
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS precas_patrol_count INTEGER;

-- CPO 현장 환경조사 체크리스트 (8항목)
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_neighborhood_type     TEXT;  -- 주변환경유형
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_location_type         TEXT;  -- 위치유형
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_lighting              TEXT;  -- 야간조명
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_police_distance       TEXT;  -- 파출소거리
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_vulnerable_facilities TEXT;  -- 주변취약시설
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_public_cctv           TEXT;  -- 공공CCTV
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_foot_traffic          TEXT;  -- 심야유동인구
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS field_building_condition    TEXT;  -- 건물노후고립도

-- CPO 재량점수 (0~10)
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS cpo_discretionary_score  INTEGER DEFAULT 0;
ALTER TABLE cpo_reviews ADD COLUMN IF NOT EXISTS cpo_discretionary_reason TEXT;


-- 2. v_admin_applications 뷰 재생성
-- (기존 뷰 정의에 새 컬럼을 추가한 버전입니다)
-- ─────────────────────────────────────────────────────────
-- 아래는 뷰 업데이트 예시입니다.
-- 기존 뷰의 SELECT에 아래 항목들을 추가해주세요:
--
--   lr.precas_112_count,
--   lr.precas_risk_grade,
--   lr.precas_patrol_count,
--   lr.field_neighborhood_type,
--   lr.field_location_type,
--   lr.field_lighting,
--   lr.field_police_distance,
--   lr.field_vulnerable_facilities,
--   lr.field_public_cctv,
--   lr.field_foot_traffic,
--   lr.field_building_condition,
--   lr.cpo_discretionary_score,
--   lr.cpo_discretionary_reason,
--
-- (lr = latest_review 서브쿼리 alias)


-- 3. '선정고려' 상태값 확인
-- ─────────────────────────────────────────────────────────
-- applications.status 컬럼의 check constraint가 있다면
-- 'selection_consideration' 값을 허용하도록 수정 필요.
-- 예:
-- ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_status_check;
-- ALTER TABLE applications ADD CONSTRAINT applications_status_check
--   CHECK (status IN (
--     'submitted', 'under_review', 'docs_requested', 'reviewed',
--     'excluded', 'selected', 'selection_consideration'
--   ));
