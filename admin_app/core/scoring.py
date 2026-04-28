"""
소상공인 안전물품 지원 관리시스템 - 점수 산출 모듈

총점: 100점 만점
  ① 프리카스 데이터      40점  상대평가
     - 112신고 건수       16점  많을수록 위험
     - 위험도 등급        14점  1=최위험, 낮을수록 위험
     - 탄력순찰 수        10점  적을수록 위험
  ② CPO 현장 환경조사    20점  절대평가, 23점 원점수 → 20점 환산
  ③ 신청인 설문          30점
     - 점포환경 7항목     25점
     - 체감안전도 5문항    5점
  ④ CPO 재량점수          10점
"""

from __future__ import annotations

from typing import Any, Dict, List


PRECAS_112_MAX = 14
PRECAS_RISK_MAX = 12
PRECAS_PATROL_MAX = 8
PRECAS_CCTV_MAX = 6

FIELD_SURVEY_RAW_MAX = 20
FIELD_SURVEY_MAX = 20


def _safe_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except Exception:
        return default


def _has_value(v: Any) -> bool:
    return v is not None and str(v).strip() != ""


def _has_complete_precas(row: Dict[str, Any]) -> bool:
    """
    프리카스 3개 값이 모두 있을 때만 40점 산정.
    0은 유효값으로 인정.
    """
    return (
        _has_value(row.get("precas_112_count"))
        and _has_value(row.get("precas_risk_grade"))
        and _has_value(row.get("precas_patrol_count"))
        and _has_value(row.get("public_cctv_count"))
    )


def _percentile(value: float, values: List[float], higher_is_risk: bool = True) -> float:
    """
    백분위 0.0~1.0.
    higher_is_risk=True  : 값이 클수록 위험
    higher_is_risk=False : 값이 작을수록 위험
    """
    if not values:
        return 0.0

    compare_value = value if higher_is_risk else -value
    compare_values = values if higher_is_risk else [-v for v in values]

    n = len(compare_values)
    below = sum(1 for v in compare_values if v < compare_value)
    equal = sum(1 for v in compare_values if v == compare_value)

    pct = (below + equal * 0.5) / n
    return round(max(0.0, min(1.0, pct)), 4)


def compute_precas_scores_batch(all_rows: List[Dict[str, Any]]) -> Dict[Any, Dict[str, Any]]:
    """
    전체 접수건 중 프리카스 3개 값이 모두 입력된 건만 상대평가.
    """
    valid_rows = [r for r in all_rows if _has_complete_precas(r)]

    if not valid_rows:
        return {}

    counts_112 = [_safe_float(r.get("precas_112_count"), 0.0) for r in valid_rows]
    risk_grades = [_safe_float(r.get("precas_risk_grade"), 9.0) for r in valid_rows]
    patrol_counts = [_safe_float(r.get("precas_patrol_count"), 0.0) for r in valid_rows]
    public_cctv_counts = [_safe_float(r.get("public_cctv_count"), 0.0) for r in valid_rows]

    result: Dict[Any, Dict[str, Any]] = {}

    for i, row in enumerate(valid_rows):
        app_id = row.get("application_id") or row.get("id")

        p112 = _percentile(counts_112[i], counts_112, higher_is_risk=True)
        prisk = _percentile(risk_grades[i], risk_grades, higher_is_risk=False)
        ppatrol = _percentile(patrol_counts[i], patrol_counts, higher_is_risk=False)
        pcctv = _percentile(public_cctv_counts[i], public_cctv_counts, higher_is_risk=False)

        s112 = round(p112 * PRECAS_112_MAX, 1)
        srisk = round(prisk * PRECAS_RISK_MAX, 1)
        spatrol = round(ppatrol * PRECAS_PATROL_MAX, 1)
        scctv = round(pcctv * PRECAS_CCTV_MAX, 1)

        result[app_id] = {
            "score_112": s112,
            "score_risk": srisk,
            "score_patrol": spatrol,
            "score_cctv": scctv,
            "total": round(s112 + srisk + spatrol + scctv, 1),
            "pct_112": round(p112 * 100, 1),
            "pct_risk": round(prisk * 100, 1),
            "pct_patrol": round(ppatrol * 100, 1),
            "pct_cctv": round(pcctv * 100, 1),
            "has_data": True,
        }

    return result


FIELD_SCORING: Dict[str, Dict[str, Any]] = {
    "field_neighborhood_type": {
        "label": "점포 주변 환경 유형",
        "max": 3,
        "scores": {
            "유흥·오락 밀집 (노래방·바·유흥주점 밀집)": 3,
            "유흥·숙박 혼재 (모텔·PC방 인접)": 3,
            "전통시장·번화가 (시장·상점가)": 2,
            "일반 상업지구 (카페·음식점 혼재)": 1,
            "주택가·아파트단지 내 상가": 0,
            "농촌·외곽·한적한 지역": 0,
        },
    },
    "field_location_type": {
        "label": "점포 위치 유형",
        "max": 3,
        "scores": {
            "지하층·반지하 점포": 3,
            "골목 안쪽 (대로에서 보이지 않는 위치)": 3,
            "이면도로·골목 점포": 2,
            "1층 이면도로변": 1,
            "1층 대로변 (정면 가시성 양호)": 0,
        },
    },
    "field_lighting": {
        "label": "야간 가로등·조명",
        "max": 2,
        "scores": {
            "불량(어두움)": 2,
            "보통": 1,
            "양호": 0,
        },
    },
    "field_police_distance": {
        "label": "파출소·지구대 거리",
        "max": 4,
        "scores": {
            "10분 이상": 4,
            "5~10분": 2,
            "3분 이내": 0,
        },
    },
    "field_vulnerable_facilities": {
        "label": "주변 취약시설",
        "max": 4,
        "scores": {
            "유흥업소·숙박업소 인접": 4,
            "일부 있음": 2,
            "없음": 0,
        },
    },
    "field_foot_traffic": {
        "label": "심야 유동인구",
        "max": 2,
        "scores": {
            "매우 적음": 2,
            "보통": 1,
            "많음": 0,
        },
    },
    "field_building_condition": {
        "label": "건물 노후·고립도",
        "max": 2,
        "scores": {
            "노후·고립": 2,
            "보통": 1,
            "양호": 0,
        },
    },
}


FIELD_OPTIONS: Dict[str, List[str]] = {
    "field_neighborhood_type": [
        "미입력",
        "유흥·오락 밀집 (노래방·바·유흥주점 밀집)",
        "유흥·숙박 혼재 (모텔·PC방 인접)",
        "전통시장·번화가 (시장·상점가)",
        "일반 상업지구 (카페·음식점 혼재)",
        "주택가·아파트단지 내 상가",
        "농촌·외곽·한적한 지역",
    ],
    "field_location_type": [
        "미입력",
        "지하층·반지하 점포",
        "골목 안쪽 (대로에서 보이지 않는 위치)",
        "이면도로·골목 점포",
        "1층 이면도로변",
        "1층 대로변 (정면 가시성 양호)",
    ],
    "field_lighting": ["미입력", "불량(어두움)", "보통", "양호"],
    "field_police_distance": ["미입력", "10분 이상", "5~10분", "3분 이내"],
    "field_vulnerable_facilities": ["미입력", "유흥업소·숙박업소 인접", "일부 있음", "없음"],
    "field_foot_traffic": ["미입력", "매우 적음", "보통", "많음"],
    "field_building_condition": ["미입력", "노후·고립", "보통", "양호"],
}


def compute_field_raw_score(row: Dict[str, Any]) -> int:
    score = 0
    for field, info in FIELD_SCORING.items():
        value = _safe_str(row.get(field))
        score += int(info["scores"].get(value, 0))
    return max(0, min(FIELD_SURVEY_RAW_MAX, score))


def compute_field_survey_score(row: Dict[str, Any]) -> float:
    """
    환경조사 원점수 20점을 그대로 20점 만점으로 사용.
    """
    raw = compute_field_raw_score(row)
    return round(max(0.0, min(float(FIELD_SURVEY_MAX), float(raw))), 1)


def field_survey_detail(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    detail: List[Dict[str, Any]] = []
    for field, info in FIELD_SCORING.items():
        value = _safe_str(row.get(field)) or "미입력"
        score = int(info["scores"].get(value, 0))
        detail.append(
            {
                "field": field,
                "label": info["label"],
                "value": value,
                "score": score,
                "max": info["max"],
            }
        )
    return detail


_CRIME_SC = {
    "자주 있음": 5,
    "가끔 있음": 3,
    "거의 없음": 1,
    "전혀 없음": 0,
}

_NIGHT_SC = {
    "자주 있음": 4,
    "가끔 있음": 2,
    "전혀 없음": 0,
}

_DARK_SC = {
    "그렇다": 4,
    "보통": 2,
    "전혀 아님": 0,
}

_SOLO_SC = {
    "자주 있음": 4,
    "가끔 있음": 2,
    "전혀 없음": 0,
}


def compute_survey_environment_score(row: Dict[str, Any]) -> int:
    """
    신청인 점포환경 설문 7항목: 최대 25점
      - 범죄피해 불안감:  5점
      - 야간 영업 빈도:   4점
      - 주변 어두움:      4점
      - 혼자 근무 빈도:   4점
      - CCTV 없음:        4점
      - 경비업체 없음:    2점
      - 비상벨 없음:      2점
    """
    score = 0

    score += _CRIME_SC.get(_safe_str(row.get("survey_crime_anxiety")), 0)
    score += _NIGHT_SC.get(_safe_str(row.get("survey_late_night")), 0)
    score += _DARK_SC.get(_safe_str(row.get("survey_dark_area")), 0)
    score += _SOLO_SC.get(_safe_str(row.get("survey_single_worker")), 0)

    if not bool(row.get("has_cctv")):
        score += 4

    if not bool(row.get("uses_security_company")):
        score += 2

    if not bool(row.get("has_emergency_bell")):
        score += 2

    return max(0, min(25, score))


def _safe_feel_answer_score(answer: Any, reverse: bool = False) -> float:
    """
    체감안전도 5문항 개별 점수. 문항당 최대 1.0점 (5문항 합계 최대 5점).
    reverse=True: '안전하다' 계열 문항이므로 부정응답일수록 고점.
    reverse=False: '불안하다/피해가능성' 계열 문항이므로 긍정응답일수록 고점.
    """
    text = _safe_str(answer)

    if reverse:
        return {
            "매우 그렇다": 0.0,
            "그렇다": 0.25,
            "보통이다": 0.5,
            "그렇지 않다": 0.75,
            "매우 그렇지 않다": 1.0,
        }.get(text, 0.0)

    return {
        "매우 그렇지 않다": 0.0,
        "그렇지 않다": 0.25,
        "보통이다": 0.5,
        "그렇다": 0.75,
        "매우 그렇다": 1.0,
    }.get(text, 0.0)


def compute_felt_safety_score(row: Dict[str, Any]) -> float:
    """
    체감안전도 5문항: 최대 5점.
    5문항 컬럼이 있으면 그것을 우선 사용.
    없으면 기존 felt_safety_score 값을 fallback으로 사용.
    """
    has_5_answers = any(
        _has_value(row.get(key))
        for key in ["safe_feel_1", "safe_feel_2", "safe_feel_3", "safe_feel_4", "safe_feel_5"]
    )

    if has_5_answers:
        score = 0.0
        score += _safe_feel_answer_score(row.get("safe_feel_1"), reverse=True)
        score += _safe_feel_answer_score(row.get("safe_feel_2"), reverse=True)
        score += _safe_feel_answer_score(row.get("safe_feel_3"), reverse=False)
        score += _safe_feel_answer_score(row.get("safe_feel_4"), reverse=True)
        score += _safe_feel_answer_score(row.get("safe_feel_5"), reverse=False)
        return round(max(0.0, min(5.0, score)), 1)

    raw = _safe_float(row.get("felt_safety_score"), 0.0)

    # 구버전 10점 척도 → 5점으로 환산
    if raw > 5:
        return round(max(0.0, min(5.0, raw / 2.0)), 1)

    return round(max(0.0, min(5.0, raw)), 1)


def compute_survey_total(row: Dict[str, Any]) -> float:
    return round(compute_survey_environment_score(row) + compute_felt_safety_score(row), 1)


def compute_discretionary_score(row: Dict[str, Any]) -> float:
    return round(max(0.0, min(10.0, _safe_float(row.get("cpo_discretionary_score"), 0.0))), 1)


def compute_total_score(row: Dict[str, Any], precas_scores: Dict[Any, Dict[str, Any]]) -> float:
    app_id = row.get("application_id") or row.get("id")
    precas_info = precas_scores.get(app_id, {})

    precas_total = _safe_float(precas_info.get("total"), 0.0)
    field_total = compute_field_survey_score(row)
    survey_total = compute_survey_total(row)
    discretionary = compute_discretionary_score(row)

    return round(precas_total + field_total + survey_total + discretionary, 1)


def score_breakdown(row: Dict[str, Any], precas_scores: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
    app_id = row.get("application_id") or row.get("id")
    precas_info = precas_scores.get(app_id, {})

    survey_env = compute_survey_environment_score(row)
    felt_safety = compute_felt_safety_score(row)
    field_raw = compute_field_raw_score(row)
    field_total = compute_field_survey_score(row)
    discretionary = compute_discretionary_score(row)
    precas_total = _safe_float(precas_info.get("total"), 0.0)

    total = round(precas_total + field_total + survey_env + felt_safety + discretionary, 1)

    return {
        "total": total,

        "precas_total": precas_total,
        "precas_112": _safe_float(precas_info.get("score_112"), 0.0),
        "precas_risk": _safe_float(precas_info.get("score_risk"), 0.0),
        "precas_patrol": _safe_float(precas_info.get("score_patrol"), 0.0),
        "precas_cctv": _safe_float(precas_info.get("score_cctv"), 0.0),
        "pct_112": precas_info.get("pct_112"),
        "pct_risk": precas_info.get("pct_risk"),
        "pct_patrol": precas_info.get("pct_patrol"),
        "pct_cctv": precas_info.get("pct_cctv"),
        "has_precas": bool(precas_info.get("has_data")),

        "field_raw": field_raw,
        "field_total": field_total,
        "field_detail": field_survey_detail(row),

        "survey_env": survey_env,
        "felt_safety": felt_safety,
        "survey_total": round(survey_env + felt_safety, 1),

        "discretionary": discretionary,
        "discretionary_reason": _safe_str(row.get("cpo_discretionary_reason")),
    }
