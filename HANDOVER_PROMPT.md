# 전남경찰청 소상공인 방범물품 지원 관리시스템 — 인수인계 프롬프트

## 프로젝트 개요

전라남도경찰청 CPO(지역경찰관)가 운영하는 **소상공인 방범물품 지원 선발 관리 시스템**입니다.

소상공인 점주가 웹 설문지를 통해 방범물품 지원을 신청하면, 경찰 CPO가 관리자 시스템에서 현장 조사 데이터를 입력하고 점수를 자동 산출하여 지원 대상자를 선발합니다.

---

## 기술 스택

| 구성 요소 | 기술 |
|---|---|
| 데이터베이스 | Supabase (PostgreSQL) |
| 관리자 앱 | Python + Streamlit |
| 신청 설문 웹 | Vanilla HTML/CSS/JavaScript |
| 지도 (설문) | VWorld OpenLayers 2.13 |
| 주소 검색 | 행정안전부 도로명주소 JUSO API (JSONP) |
| 리포트 생성 | python-docx (A4 Word 문서) |
| 주요 라이브러리 | pandas, supabase-py, folium, streamlit-folium, pyproj, openpyxl |

---

## 파일 구조

```
jeonnam-cpo/
├── survey_web/                  # 점주 신청 설문 (정적 웹)
│   ├── index.html               # 설문 폼 (VWorld 지도 포함)
│   ├── app.js                   # 설문 로직 (주소검색, Supabase 저장)
│   ├── style.css                # 스타일
│   └── config.js                # API 키 설정 (VWorld, Supabase, Juso)
│
├── admin_app/                   # CPO 관리자 Streamlit 앱
│   ├── app.py                   # 메인 앱 진입점 (로그인/라우팅)
│   ├── core/
│   │   ├── scoring.py           # 점수 산출 로직 (100점 만점)
│   │   ├── report.py            # A4 1페이지 Word 리포트 생성
│   │   ├── auth.py              # Supabase 인증
│   │   └── supabase_client.py   # Supabase 클라이언트
│   └── pages/
│       ├── cpo_view.py          # CPO 메인 화면 (조회/검토/선발)
│       ├── admin_view.py        # 관리자 화면 (경찰서/계정 관리)
│       └── map_view.py          # 지도 전용 뷰
│
├── migration_scoring.sql        # DB 스키마 마이그레이션 SQL
└── migration_view_update.sql    # v_admin_applications 뷰 업데이트 SQL
```

---

## Supabase 데이터베이스 구조

### 주요 테이블

**`applications`** — 점주 신청 데이터
```
id (uuid, PK)
applicant_name        -- 신청인 이름
business_name         -- 점포명
phone                 -- 연락처
business_type         -- 업종
business_type_other   -- 기타 업종명
annual_sales          -- 연매출 (원)
sales_band            -- 연매출 구간 (텍스트)
address_road          -- 도로명주소
address_detail        -- 상세주소
address_jibun         -- 지번주소
full_address          -- 전체주소
latitude / longitude  -- 좌표
station_id            -- 관할 경찰서 FK
status                -- 현재 상태 (enum)
requested_item        -- 희망 지원물품 (비상벨+경광등/호신용품 세트/방범 강화키트)
has_cctv / has_emergency_bell / uses_security_company  -- boolean
other_security        -- 기타 방범시설
survey_crime_anxiety  -- 범죄불안 경험 (설문)
survey_late_night     -- 야간영업 (설문)
survey_dark_area      -- 주변 환경 어두움 (설문)
survey_single_worker  -- 단독 근무 (설문)
safe_feel_1~5         -- 체감안전도 5문항
apply_reason / etc_note
submitted_at
```

**`cpo_reviews`** — CPO 검토 기록 (이력 누적)
```
id, application_id (FK)
reviewer_id, station_id
review_result         -- 검토 상태 (submitted/under_review/reviewed/selection_considered/selected/excluded)
is_excluded / exclude_reason
review_comment        -- 최종 검토 의견
docs_request_comment  -- 추가서류 요청 내용
reviewed_at
-- 치안현황 (경찰 내부 시스템):
precas_112_count      -- 112신고 건수
precas_risk_grade     -- 위험도 등급 (1~9, 1=최위험)
precas_patrol_count   -- 탄력순찰 횟수
-- CPO 현장 안전평가:
field_neighborhood_type  -- 주변 환경 유형
field_location_type      -- 점포 위치 유형
field_lighting           -- 야간 조명 상태
field_police_distance    -- 파출소 거리
field_vulnerable_facilities
field_public_cctv
field_foot_traffic
field_building_condition
-- CPO 재량:
cpo_discretionary_score   -- 재량 가산점 (0~10)
cpo_discretionary_reason
```

**`stations`** — 전남 22개 경찰서
```
id, station_label, is_active
```

**`v_admin_applications`** — 관리자 조회용 뷰 (applications + 최신 cpo_reviews JOIN)
```
최신 cpo_reviews의 모든 필드 + applications의 모든 필드를 합친 플랫 뷰.
current_status = 최신 리뷰의 review_result
```

---

## 점수 산출 로직 (`admin_app/core/scoring.py`)

### 총점 = 100점 만점

| 항목 | 배점 | 방식 |
|---|---|---|
| ① 치안현황 데이터 (경찰 내부 시스템) | 40점 | **상대평가** (전체 접수 건 중 백분위) |
| ② CPO 현장 안전평가 | 20점 | **절대평가** (23점 원점수 → 20점 환산) |
| ③ 점주 설문 응답 | 30점 | 절대평가 |
| ④ CPO 재량 가산점 | 10점 | CPO 직접 입력 (0~10) |

### ① 치안현황 데이터 (40점)
- **프리카스(PRECAS)** 100m 격자 기준 경찰청 내부 시스템 데이터
- 112신고 건수 16점, 범죄위험도 등급 14점, 탄력순찰 횟수 10점
- 3개 항목 **모두** 입력 시에만 산정 (상대평가: 전체 접수 건 중 백분위로 환산)
- `compute_precas_scores_batch(all_rows)` 로 배치 계산

### ② CPO 현장 안전평가 (20점)
절대평가. 8개 항목, 원점수 합계 23점 → 20점으로 환산

| 항목 | 최대점 |
|---|---|
| 점포 주변 환경 유형 | 3점 |
| 점포 위치 유형 | 3점 |
| 야간 가로등·조명 | 3점 |
| 파출소·지구대 거리 | 3점 |
| 주변 취약시설 | 2점 |
| 공공 CCTV 현황 | 3점 |
| 심야 유동인구 | 3점 |
| 건물 노후·고립도 | 3점 |

### ③ 점주 설문 응답 (30점)
- **점포환경 응답 25점**: 범죄불안 경험(5점), 야간영업(4점), 주변 어두움(4점), 단독근무(4점), CCTV 없음(4점), 사설경비 미이용(2점), 비상벨 없음(2점) 합산
- **안전체감도 5점**: `safe_feel_1~5` 5문항 Likert 응답 → 0~1 정규화 후 합산

### ④ CPO 재량 가산점 (10점)
- 5점 초과 시 사유 입력 필수
- 8점 이상 시 구체 사유 10자 이상 필수

---

## 신청 설문 웹 (`survey_web/`)

### 주요 기능
1. **VWorld OpenLayers 지도** — 전라남도 중심, 점주가 지도 핀으로 위치 확정
2. **JUSO 주소 검색** — 도로명주소 팝업 → 선택 → VWorld API 좌표 자동 변환
3. **방범물품 선택 카드** — 3종 중 1개 선택 (비상벨+경광등 / 호신용품 세트 / 방범 강화키트)
4. **설문 항목** — 범죄불안, 야간영업, 주변환경, 단독근무, CCTV, 비상벨, 사설경비, 체감안전도 5문항
5. **개인정보 동의** 체크박스
6. **Supabase REST API**로 직접 저장 (supabase-js 미사용, fetch + anon key)

### config.js 설정값
```javascript
window.APP_CONFIG = {
  VWORLD_API_KEY: "...",       // VWorld 지도 API 키
  VWORLD_DOMAIN: "http://127.0.0.1:5500",  // VWorld 등록 도메인
  SUPABASE_URL: "https://nvhcpmixptliqrwgusch.supabase.co",
  SUPABASE_ANON_KEY: "...",
  JUSO_CONFM_KEY: "...",       // 주소 검색 키
  JUSO_COORD_CONFM_KEY: "..."  // 좌표 변환 키
};
```

### 주소 검색 아키텍처 (중요)
- JUSO JSONP API로 주소 목록 팝업 → 선택
- 선택 후 VWorld geocoding API로 좌표 변환 → 지도 핀 배치
- **주소 검색 버튼 바인딩이 VWorld 지도 초기화와 독립적으로 동작** (VWorld 실패 시에도 주소 검색은 가능)
- `window.__updateSelectedPointRef`로 핀 배치 함수를 전역 참조 (지도 준비 전 stub → 지도 로드 후 실제 함수로 업그레이드)

---

## CPO 관리자 앱 (`admin_app/pages/cpo_view.py`)

### 화면 구성 (단일 페이지, 세로 스크롤)

```
[페이지 헤더 배너]    파란 그라디언트, 총 접수 건수 표시

[컬러 메트릭 카드 6개]
총접수 / 검토완료 / 선정고려 / 선정 / 제외 / 미검토

[필터 영역]
경찰서 / 상태 / 기간 / 키워드 검색

[섹션 1: 우선 검토 대상]
  → 점수 구성 가이드 (접이식 표)
  → SEMAS 제외업종 링크
  → 우선순위 테이블 (상위 N건)

[섹션 2: 위원회 리포트 다운로드]
  → 파란 배너 패널
  → "선정고려·선정 전체 ZIP" 버튼
  → "체크 항목 ZIP" 버튼

[섹션 3: 접수 목록]
  → 툴바: 전체선택 / 선택해제 / 체크N건 엑셀 / 전체N건 엑셀
  → data_editor 테이블 (체크박스 선택 가능)
    컬럼: 선택, 번호, 점포명, 신청인, 연락처, 업종, 경찰서,
          접수일시, 주소, 위도, 경도, 희망물품,
          치안현황, 현장평가, 점포환경응답, 안전체감도, CPO재량, 총점, 상태

[섹션 4: 지도 + 상세 검토]
  → Folium 지도 (목록 체크 = 지도 표시 / 상세는 선택 1건)
  → 점포 상세 정보 (기본정보 + 점수 카드 5개)
  → 접수 정보 수정 (주소검색, 기본정보, 저장/삭제)
  → 검토 이력 (과거 저장 내역)
  → CPO 검토 입력 폼 (프리카스 입력, 현장평가, 재량, 의견, 상태 → 저장)
```

### 역할 분리 (role)
- `admin` — 전체 경찰서 조회 가능, 경찰서 필터 선택 가능
- `cpo` — 자신의 관할 경찰서 데이터만 조회

### 주요 함수
- `compute_precas_scores_batch(rows)` — 전체 행 배치 점수 계산
- `score_breakdown(row, precas_scores)` — 1건 상세 점수 분해
- `generate_report(row, precas_scores, rank, total_count)` — A4 1페이지 Word 생성
- `generate_report_zip(rows, precas_scores)` — 다건 ZIP
- `_save_review(...)` — cpo_reviews INSERT + applications.status UPDATE
- `_update_application(...)` — 기본정보 수정 저장
- `_delete_application(...)` — cpo_reviews + applications 삭제

---

## Word 리포트 구조 (`admin_app/core/report.py`)

A4 1페이지 이내 (여백 1.0cm, 폰트 8.5pt):

```
[헤더 배너]   파란 그라디언트 | 제목 | 기관 + 생성일
[총점 요약 바]  총점 | 순위/백분위 | 치안현황/40 | 현장평가/20 | 설문/30 | 재량/10
[2열 메인]
  왼쪽: 점포 기본정보 (점포명, 대표자, 연락처, 업종, 주소, 경찰서, 신청일, 상태, 희망물품)
  오른쪽: 치안현황 데이터 (112신고/위험도/탄력순찰 바 표시)
          + 점주 설문 응답 (범죄불안/야간영업/주변환경/단독근무, CCTV/비상벨/사설경비, 체감안전도)
[CPO 현장평가]  8개 항목 × (항목명 + 선택값 + 점수), 4열 그리드 2행
[재량 + 최종의견]  재량점수/사유 | 최종 검토의견 + 검토상태/관할/검토일
```

---

## 현재 구현 완료 사항

- [x] 점주 신청 설문 웹 (VWorld 지도 + JUSO 주소 검색 + 설문 + Supabase 저장)
- [x] 방범물품 3종 카드 선택 UI (비상벨+경광등 / 호신용품 세트 / 방범 강화키트)
- [x] CPO 관리자 앱 로그인/인증 (Supabase Auth)
- [x] 접수 조회 (경찰서/상태/기간/키워드 필터)
- [x] 100점 만점 자동 점수 산출 (scoring.py)
- [x] CPO 현장 검토 입력 및 저장 (cpo_reviews 이력 누적)
- [x] 접수 정보 수정 (기본정보, 주소, 좌표)
- [x] 우선순위 테이블 + 점수 구성 가이드
- [x] Folium 지도 시각화
- [x] A4 1페이지 Word 리포트 (개별 / 일괄 ZIP)
- [x] 엑셀 다운로드 (선택 건 / 전체 결과)
- [x] 컬러 메트릭 카드 + 파란 헤더 배너 UI
- [x] 리포트 패널 (선정고려·선정 ZIP 즉시 다운로드)

---

## 주요 주의사항

1. **null bytes 오염**: 일부 파일이 UTF-16으로 저장된 적이 있어 null byte가 섞일 수 있음. 파일 수정 후 `open(f,'rb').read().replace(b'\x00',b'')` 로 정리 필요.

2. **VWorld 도메인**: `config.js`의 `VWORLD_DOMAIN`이 VWorld 콘솔에 등록된 서비스 URL과 정확히 일치해야 지도 로드됨. 현재 `http://127.0.0.1:5500`.

3. **프리카스 점수는 상대평가**: 현재 조회된 전체 행 기준 백분위 → 접수 건 추가 시 기존 건 점수가 변동됨.

4. **v_admin_applications 뷰**: `DROP VIEW IF EXISTS` 후 `CREATE VIEW` 방식 사용 (PostgreSQL은 뷰 컬럼 순서 변경 불가).

5. **cpo_reviews 이력 누적**: 검토 저장 시 매번 INSERT (UPDATE 아님). 최신 리뷰가 `current_status`에 반영.

6. **주소 검색 독립성**: `searchAddressToCoord()` 함수와 버튼 바인딩은 VWorld 지도 초기화 *이전에* 먼저 완료됨. VWorld 실패 시에도 JUSO 팝업 검색은 동작함.

---

## 개발 환경 실행 방법

```bash
# 관리자 앱 실행
cd admin_app
streamlit run app.py

# 설문 웹 (VS Code Live Server 등 정적 서버)
# survey_web/index.html 을 http://127.0.0.1:5500 에서 서빙
```

---

## 향후 개선 가능 사항 (미구현)

- 점수 변동 이력 트래킹 (프리카스 상대평가로 인한 점수 변동 알림)
- 위원회 결과 일괄 처리 (선정 → 안내 문자 발송 연동)
- 방범물품 재고/배분 현황 관리 모듈
- 신청 현황 대시보드 (경찰서별 통계, 그래프)
- 설문 웹 도메인 배포 (현재 로컬 개발 환경)
