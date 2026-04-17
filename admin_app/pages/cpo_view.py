from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from pyproj import Transformer


STATUS_LABELS = {
    "submitted": "접수완료",
    "under_review": "검토중",
    "docs_requested": "추가서류요청",
    "reviewed": "검토완료",
    "excluded": "제외",
    "selected": "선정",
}

STATUS_FILTER_OPTIONS = ["전체", "접수완료", "검토중", "추가서류요청", "검토완료", "제외", "선정"]
STATUS_VALUE_BY_LABEL = {v: k for k, v in STATUS_LABELS.items()}

CPO_RISK_OPTIONS = {
    "미입력": 0,
    "매우 높음": 50,
    "높음": 40,
    "보통": 25,
    "낮음": 10,
    "매우 낮음": 0,
}

REVIEW_STATUS_OPTIONS = ["검토완료", "추가서류요청", "선정", "제외"]
JEONNAM_CENTER = [34.8679, 126.9910]
COMMON_BUSINESS_TYPES = ["", "편의점", "음식점", "카페", "주점", "미용실", "소매점", "기타"]
COMMON_SALES_BANDS = [
    "",
    "1천만원 이하",
    "1천만원 초과 ~ 3천만원 이하",
    "3천만원 초과 ~ 5천만원 이하",
    "5천만원 초과 ~ 1억원 이하",
    "1억원 초과 ~ 2억원 이하",
    "2억원 초과",
]
JEONNAM_STATION_AREAS = [
    ("목포", "목포경찰서"),
    ("여수", "여수경찰서"),
    ("순천", "순천경찰서"),
    ("나주", "나주경찰서"),
    ("광양", "광양경찰서"),
    ("고흥", "고흥경찰서"),
    ("해남", "해남경찰서"),
    ("무안", "무안경찰서"),
    ("장흥", "장흥경찰서"),
    ("보성", "보성경찰서"),
    ("영광", "영광경찰서"),
    ("화순", "화순경찰서"),
    ("함평", "함평경찰서"),
    ("영암", "영암경찰서"),
    ("장성", "장성경찰서"),
    ("강진", "강진경찰서"),
    ("담양", "담양경찰서"),
    ("곡성", "곡성경찰서"),
    ("완도", "완도경찰서"),
    ("진도", "진도경찰서"),
    ("구례", "구례경찰서"),
    ("신안", "신안경찰서"),
]

_COORD_TRANSFORMER = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)


def _safe_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _normalize_text(v: Any) -> str:
    return _safe_str(v).replace(" ", "")


def _infer_station_label_from_address(address_text: str, station_options: List[str]) -> str:
    normalized = _normalize_text(address_text)
    if not normalized:
        return ""

    option_set = {_safe_str(x) for x in station_options if _safe_str(x)}
    best_station = ""
    best_score = 0

    for area_name, station_label in JEONNAM_STATION_AREAS:
        if station_label not in option_set:
            continue

        tokens = [
            area_name,
            f"{area_name}시",
            f"{area_name}군",
            f"{area_name}구",
            station_label.replace("경찰서", ""),
            station_label,
        ]
        normalized_tokens = [_normalize_text(token) for token in tokens if _normalize_text(token)]

        score = 0
        for token in normalized_tokens:
            if normalized == token:
                score = max(score, 20)
            elif normalized.startswith(token):
                score = max(score, 16)
            elif token in normalized:
                score = max(score, 12)

        if score > best_score:
            best_score = score
            best_station = station_label

    return best_station if best_score > 0 else ""


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


def _to_dt(v: Any) -> Optional[datetime]:
    text = _safe_str(v)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _status_label(value: str) -> str:
    return STATUS_LABELS.get(_safe_str(value), _safe_str(value))


def _review_status_value(label: str, exclude_flag: bool) -> str:
    if exclude_flag:
        return "excluded"
    return STATUS_VALUE_BY_LABEL.get(label, "reviewed")


def _display_business_type(row: Dict[str, Any]) -> str:
    business_type = _safe_str(row.get("business_type"))
    business_type_other = _safe_str(row.get("business_type_other"))
    if business_type == "기타" and business_type_other:
        return f"기타 ({business_type_other})"
    if business_type_other and business_type and business_type != business_type_other:
        return f"{business_type} / {business_type_other}"
    return business_type or business_type_other or "-"


def _display_sales(row: Dict[str, Any]) -> str:
    annual_sales = _safe_int(row.get("annual_sales"), 0)
    return f"{annual_sales:,}원" if annual_sales else "-"


def _full_address(row: Dict[str, Any]) -> str:
    full_address = _safe_str(row.get("full_address"))
    if full_address:
        return full_address
    address_road = _safe_str(row.get("address_road"))
    address_detail = _safe_str(row.get("address_detail"))
    if address_detail:
        return f"{address_road}, {address_detail}"
    return address_road or _safe_str(row.get("address_jibun")) or "-"


def _format_submitted_text(value: Any) -> str:
    dt = _to_dt(value)
    if not dt:
        text = _safe_str(value)
        return text.replace("T", " ")[:16] if text else "-"
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_coord(value: Any) -> str:
    num = _safe_float(value, 0.0)
    return f"{num:.6f}" if num else "-"


def _unique_station_options(station_options: List[str]) -> List[str]:
    seen = set()
    result = []
    for item in station_options:
        label = _safe_str(item)
        if not label or label in seen:
            continue
        seen.add(label)
        result.append(label)
    return result


def _get_secret_first(*keys: str) -> str:
    for key in keys:
        try:
            if key in st.secrets and _safe_str(st.secrets[key]):
                return _safe_str(st.secrets[key])
        except Exception:
            pass
    return ""


def _get_juso_search_key() -> str:
    return _get_secret_first(
        "JUSO_CONFM_KEY",
        "JUSO_SEARCH_CONFM_KEY",
        "JUSO_SEARCH_KEY",
        "JUSO_KEY",
        "juso_confm_key",
        "juso_search_key",
        "juso_key",
    )


def _get_juso_coord_key() -> str:
    return _get_secret_first(
        "JUSO_COORD_CONFM_KEY",
        "JUSO_ADDRCOORD_CONFM_KEY",
        "JUSO_COORD_KEY",
        "JUSO_KEY",
        "juso_coord_confm_key",
        "juso_coord_key",
        "juso_key",
    )


def _get_vworld_api_key() -> str:
    return _get_secret_first(
        "VWORLD_API_KEY",
        "V_WORLD_API_KEY",
        "VWORLD_KEY",
        "vworld_api_key",
        "vworld_key",
    )


def _search_juso_addresses(query: str) -> List[Dict[str, Any]]:
    query = _safe_str(query)
    if not query:
        return []

    key = _get_juso_search_key()
    if not key:
        raise Exception("JUSO 검색 키가 st.secrets에 없습니다.")

    url = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
    params = {
        "confmKey": key,
        "currentPage": 1,
        "countPerPage": 10,
        "keyword": query,
        "resultType": "json",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or {}
    common = results.get("common") or {}
    error_code = _safe_str(common.get("errorCode"))
    error_message = _safe_str(common.get("errorMessage"))
    if error_code and error_code != "0":
        raise Exception(error_message or f"주소 검색 오류({error_code})")
    return list(results.get("juso") or [])


def _coord_from_juso_candidate(candidate: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    key = _get_juso_coord_key()
    if not key:
        return None, None

    url = "https://business.juso.go.kr/addrlink/addrCoordApi.do"
    params = {
        "confmKey": key,
        "admCd": _safe_str(candidate.get("admCd")),
        "rnMgtSn": _safe_str(candidate.get("rnMgtSn")),
        "udrtYn": _safe_str(candidate.get("udrtYn")) or "0",
        "buldMnnm": _safe_str(candidate.get("buldMnnm")),
        "buldSlno": _safe_str(candidate.get("buldSlno")) or "0",
        "resultType": "json",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results") or {}
    common = results.get("common") or {}
    error_code = _safe_str(common.get("errorCode"))
    error_message = _safe_str(common.get("errorMessage"))
    if error_code and error_code != "0":
        raise Exception(error_message or f"좌표 검색 오류({error_code})")

    juso_list = list(results.get("juso") or [])
    if not juso_list:
        return None, None

    first = juso_list[0]
    ent_x = _safe_str(first.get("entX"))
    ent_y = _safe_str(first.get("entY"))
    if not ent_x or not ent_y:
        return None, None

    x = float(ent_x)
    y = float(ent_y)
    lon, lat = _COORD_TRANSFORMER.transform(x, y)
    return float(lat), float(lon)


def _coord_from_vworld(address: str) -> Tuple[Optional[float], Optional[float], str]:
    query = _safe_str(address)
    if not query:
        return None, None, ""

    api_key = _get_vworld_api_key()
    if not api_key:
        return None, None, ""

    url = "https://api.vworld.kr/req/address"

    def _call(addr_type: str) -> Tuple[Optional[float], Optional[float], str]:
        params = {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "address": query,
            "refine": "true",
            "simple": "false",
            "format": "json",
            "errorformat": "json",
            "type": addr_type,
            "key": api_key,
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response") or {}
        if response.get("status") != "OK":
            return None, None, ""
        result = response.get("result") or {}
        point = result.get("point") or {}
        refined = response.get("refined") or {}
        x = point.get("x")
        y = point.get("y")
        try:
            lon = float(x)
            lat = float(y)
        except Exception:
            return None, None, ""
        official_address = _safe_str(refined.get("text")) or query
        return lat, lon, official_address

    for addr_type in ["road", "parcel"]:
        lat, lon, official = _call(addr_type)
        if lat is not None and lon is not None:
            return lat, lon, official
    return None, None, ""


def _resolve_candidate_to_address_and_coord(candidate: Dict[str, Any]) -> Tuple[str, float, float]:
    road_addr = _safe_str(candidate.get("roadAddr"))
    jibun_addr = _safe_str(candidate.get("jibunAddr"))
    official_address = road_addr or jibun_addr

    lat, lon = _coord_from_juso_candidate(candidate)
    if lat is not None and lon is not None:
        return official_address, float(lat), float(lon)

    lat, lon, vworld_official = _coord_from_vworld(road_addr or jibun_addr)
    if lat is not None and lon is not None:
        return vworld_official or official_address, float(lat), float(lon)

    raise Exception("선택한 주소의 좌표를 찾지 못했습니다. JUSO 좌표키 또는 VWORLD 키를 확인해주세요.")


def _fetch_rows(supabase) -> List[Dict[str, Any]]:
    try:
        resp = (
            supabase.table("v_admin_applications")
            .select("*")
            .order("submitted_at", desc=True)
            .limit(5000)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        st.error(f"v_admin_applications 조회 실패: {exc}")
        return []


def _fetch_station_map(supabase) -> Dict[str, Any]:
    try:
        resp = (
            supabase.table("stations")
            .select("id, station_label")
            .eq("is_active", True)
            .order("id", desc=False)
            .execute()
        )
        rows = resp.data or []
        return {_safe_str(row.get("station_label")): row.get("id") for row in rows if _safe_str(row.get("station_label"))}
    except Exception:
        return {}


def _apply_filters(
    rows: List[Dict[str, Any]],
    role: str,
    selected_station: str,
    status_filter: str,
    date_from: date,
    date_to: date,
    keyword: str,
) -> List[Dict[str, Any]]:
    keyword = keyword.strip().lower()
    result: List[Dict[str, Any]] = []

    for row in rows:
        station_label = _safe_str(row.get("station_label"))
        submitted_at = _to_dt(row.get("submitted_at"))
        current_status_label = _status_label(row.get("current_status"))

        if role == "admin":
            if selected_station not in ["", "전체"] and station_label != selected_station:
                continue
        else:
            if selected_station and station_label != selected_station:
                continue

        if submitted_at:
            if submitted_at.date() < date_from or submitted_at.date() > date_to:
                continue

        if status_filter != "전체" and current_status_label != status_filter:
            continue

        if keyword:
            haystack = " ".join(
                [
                    _safe_str(row.get("business_name")),
                    _safe_str(row.get("applicant_name")),
                    _safe_str(row.get("phone")),
                    _safe_str(row.get("station_label")),
                    _display_business_type(row),
                    _full_address(row),
                ]
            ).lower()
            if keyword not in haystack:
                continue

        result.append(row)

    result.sort(
        key=lambda x: (
            -_safe_int(x.get("total_score"), 0),
            _to_dt(x.get("submitted_at")) or datetime.min,
        ),
        reverse=False,
    )
    return result


def _summary_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "총 접수": len(rows),
        "검토완료": 0,
        "제외": 0,
        "선정": 0,
        "미검토": 0,
    }
    for row in rows:
        status = _status_label(row.get("current_status"))
        if status == "검토완료":
            counts["검토완료"] += 1
        elif status == "제외":
            counts["제외"] += 1
        elif status == "선정":
            counts["선정"] += 1
        elif status in ["접수완료", "검토중", "추가서류요청"]:
            counts["미검토"] += 1
    return counts


def _df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="data", index=False)
    return output.getvalue()


def _build_export_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    data = []
    for row in rows:
        data.append(
            {
                "접수일시": _format_submitted_text(row.get("submitted_at")),
                "상태": _status_label(row.get("current_status")),
                "경찰서": _safe_str(row.get("station_label")),
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "연락처": _safe_str(row.get("phone")),
                "업종": _display_business_type(row),
                "정식주소": _safe_str(row.get("address_road")),
                "상세주소": _safe_str(row.get("address_detail")),
                "전체주소": _full_address(row),
                "위도": _safe_float(row.get("latitude"), 0.0),
                "경도": _safe_float(row.get("longitude"), 0.0),
                "연매출구간": _safe_str(row.get("sales_band")),
                "연매출(원)": _safe_int(row.get("annual_sales"), 0),
                "범죄불안경험": _safe_str(row.get("survey_crime_anxiety")),
                "야간영업여부": _safe_str(row.get("survey_late_night")),
                "주변환경": _safe_str(row.get("survey_dark_area")),
                "단독근무": _safe_str(row.get("survey_single_worker")),
                "점포내CCTV": "있음" if bool(row.get("has_cctv")) else "없음",
                "비상벨": "있음" if bool(row.get("has_emergency_bell")) else "없음",
                "사설경비": "이용 중" if bool(row.get("uses_security_company")) else "이용하지 않음",
                "기타방범시설": _safe_str(row.get("other_security")),
                "체감안전도": _safe_int(row.get("felt_safety_score"), 0),
                "CPO위험도등급": _safe_str(row.get("cpo_risk_label")),
                "CPO위험도점수": _safe_int(row.get("cpo_risk_score"), 0),
                "보안취약도": _safe_int(row.get("security_vulnerability_score"), 0),
                "총점": _safe_int(row.get("total_score"), 0),
                "우선순위제외": "예" if bool(row.get("is_excluded")) else "아니오",
                "제외사유": _safe_str(row.get("exclude_reason")),
                "검토메모": _safe_str(row.get("review_comment")),
                "추가서류요청내용": _safe_str(row.get("docs_request_comment")),
                "신청사유": _safe_str(row.get("apply_reason")),
            }
        )
    return pd.DataFrame(data)


def _set_selected_application(row: Dict[str, Any]):
    st.session_state["selected_application_id"] = row.get("application_id")


def _selected_row(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    selected_id = st.session_state.get("selected_application_id")
    if selected_id is not None:
        for row in rows:
            if row.get("application_id") == selected_id:
                return row
    return rows[0] if rows else None


def _sync_selected_row_by_selectbox(rows: List[Dict[str, Any]]):
    if not rows:
        st.session_state.pop("selected_application_id", None)
        st.session_state.pop("selected_application_selectbox", None)
        return

    options = []
    for row in rows:
        options.append(
            {
                "application_id": row.get("application_id"),
                "label": (
                    f"{_safe_str(row.get('business_name'))} | {_safe_str(row.get('station_label')) or '-'} | "
                    f"{_status_label(row.get('current_status'))} | 총점 {_safe_int(row.get('total_score'), 0)}점 | "
                    f"{_format_submitted_text(row.get('submitted_at'))}"
                ),
            }
        )

    current_id = st.session_state.get("selected_application_id")
    option_ids = [item["application_id"] for item in options]
    if current_id not in option_ids:
        current_id = option_ids[0]
        st.session_state["selected_application_id"] = current_id

    if st.session_state.get("selected_application_selectbox") != current_id:
        st.session_state["selected_application_selectbox"] = current_id

    id_to_label = {item["application_id"]: item["label"] for item in options}

    selected_id = st.selectbox(
        "선택 점포",
        option_ids,
        format_func=lambda x: id_to_label.get(x, str(x)),
        key="selected_application_selectbox",
    )

    if selected_id != current_id:
        st.session_state["selected_application_id"] = selected_id
        st.rerun()


def _extract_selected_indexes(event: Any) -> List[int]:
    try:
        selection = getattr(event, "selection", None)
        if selection is None and isinstance(event, dict):
            selection = event.get("selection")
        if selection is None:
            return []
        rows = getattr(selection, "rows", None)
        if rows is not None:
            return list(rows)
        if isinstance(selection, dict):
            return list(selection.get("rows", []) or [])
    except Exception:
        return []
    return []


def _render_map(rows: List[Dict[str, Any]], selected_row: Optional[Dict[str, Any]]):
    import folium
    from folium.plugins import MarkerCluster
    from streamlit_folium import st_folium

    if selected_row and _safe_float(selected_row.get("latitude"), 0) and _safe_float(selected_row.get("longitude"), 0):
        center = [
            _safe_float(selected_row.get("latitude"), JEONNAM_CENTER[0]),
            _safe_float(selected_row.get("longitude"), JEONNAM_CENTER[1]),
        ]
        zoom = 16
    else:
        valid_rows = [r for r in rows if _safe_float(r.get("latitude"), 0) and _safe_float(r.get("longitude"), 0)]
        if valid_rows:
            center = [
                sum(_safe_float(r.get("latitude"), 0) for r in valid_rows) / len(valid_rows),
                sum(_safe_float(r.get("longitude"), 0) for r in valid_rows) / len(valid_rows),
            ]
            zoom = 11
        else:
            center = JEONNAM_CENTER
            zoom = 9

    fmap = folium.Map(location=center, zoom_start=zoom, control_scale=True, prefer_canvas=True)
    cluster = MarkerCluster().add_to(fmap)

    for row in rows:
        lat = _safe_float(row.get("latitude"), 0.0)
        lon = _safe_float(row.get("longitude"), 0.0)
        if not lat or not lon:
            continue

        popup_html = (
            f"<b>{_safe_str(row.get('business_name'))}</b><br>"
            f"업종: {_display_business_type(row)}<br>"
            f"주소: {_full_address(row)}<br>"
            f"상태: {_status_label(row.get('current_status'))}<br>"
            f"총점: {_safe_int(row.get('total_score'), 0)}점"
        )
        tooltip = f"{_safe_str(row.get('business_name'))} / {_status_label(row.get('current_status'))}"
        icon_color = "red" if selected_row and row.get("application_id") == selected_row.get("application_id") else "blue"

        folium.Marker(
            [lat, lon],
            tooltip=tooltip,
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=icon_color),
        ).add_to(cluster)

    if selected_row and _safe_float(selected_row.get("latitude"), 0) and _safe_float(selected_row.get("longitude"), 0):
        folium.CircleMarker(
            location=[_safe_float(selected_row.get("latitude")), _safe_float(selected_row.get("longitude"))],
            radius=16,
            weight=4,
            fill=False,
        ).add_to(fmap)

    st_folium(fmap, key="admin_main_map", height=520, width=None)


def _render_score_guide():
    with st.expander("우선순위 현황", expanded=True):
        st.markdown(
            """
**우선순위는 아래 항목을 합산하여 산정합니다.**

**총점 = 체감안전도(최대 40점) + CPO 위험도(최대 50점) + 보안취약도(최대 10점)**

- **체감안전도(최대 40점)**: 신청 설문 응답을 바탕으로 자동 산출
- **CPO 위험도(최대 50점)**: 현장 여건과 범죄 취약성을 고려하여 CPO가 직접 입력
- **보안취약도(최대 10점)**: CCTV 미설치 +5점, 사설경비 미이용 +5점

※ 최종 지원 여부는 검토의견과 현장 상황을 함께 반영하여 결정합니다.
"""
        )


def _render_priority_table(rows: List[Dict[str, Any]]):
    c1, c2 = st.columns([2, 2])
    with c1:
        hide_excluded = st.checkbox("제외 건 숨기기", value=True, key="priority_hide_excluded")
    with c2:
        top_n = st.number_input("상위 순위만 보기", min_value=1, max_value=500, value=20, step=1)

    filtered = []
    for row in rows:
        if hide_excluded and _status_label(row.get("current_status")) == "제외":
            continue
        filtered.append(row)

    filtered.sort(key=lambda x: _safe_int(x.get("total_score"), 0), reverse=True)
    filtered = filtered[:top_n]

    table_rows = []
    for idx, row in enumerate(filtered, start=1):
        table_rows.append(
            {
                "순위": idx,
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "경찰서": _safe_str(row.get("station_label")),
                "업종": _display_business_type(row),
                "체감안전도": _safe_int(row.get("felt_safety_score"), 0),
                "CPO위험도": _safe_int(row.get("cpo_risk_score"), 0),
                "보안취약도": _safe_int(row.get("security_vulnerability_score"), 0),
                "총점": _safe_int(row.get("total_score"), 0),
                "상태": _status_label(row.get("current_status")),
            }
        )

    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("우선순위 데이터가 없습니다.")


def _render_top_metrics(rows: List[Dict[str, Any]]):
    counts = _summary_counts(rows)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 접수", f"{counts['총 접수']}건")
    c2.metric("검토완료", f"{counts['검토완료']}건")
    c3.metric("제외", f"{counts['제외']}건")
    c4.metric("선정", f"{counts['선정']}건")
    c5.metric("미검토", f"{counts['미검토']}건")


def _build_list_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    table_rows = []
    for idx, row in enumerate(rows, start=1):
        table_rows.append(
            {
                "번호": idx,
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "연락처": _safe_str(row.get("phone")),
                "업종": _display_business_type(row),
                "경찰서": _safe_str(row.get("station_label")),
                "접수일시": _format_submitted_text(row.get("submitted_at")),
                "주소": _full_address(row),
                "위도": _format_coord(row.get("latitude")),
                "경도": _format_coord(row.get("longitude")),
                "체감안전도": _safe_int(row.get("felt_safety_score"), 0),
                "CPO위험도": _safe_int(row.get("cpo_risk_score"), 0),
                "보안취약도": _safe_int(row.get("security_vulnerability_score"), 0),
                "총점": _safe_int(row.get("total_score"), 0),
                "상태": _status_label(row.get("current_status")),
            }
        )
    return pd.DataFrame(table_rows)



def _render_list_table(rows: List[Dict[str, Any]]) -> List[Any]:
    if not rows:
        st.info("조회 결과가 없습니다.")
        st.session_state.pop("selected_application_id", None)
        st.session_state["list_checked_application_ids"] = []
        return []

    visible_ids = [row.get("application_id") for row in rows]
    current_selected_id = st.session_state.get("selected_application_id")
    if current_selected_id is None or current_selected_id not in visible_ids:
        current_selected_id = rows[0].get("application_id")
        st.session_state["selected_application_id"] = current_selected_id
        st.session_state["selected_application_selectbox"] = current_selected_id

    stored_ids = st.session_state.get("list_checked_application_ids", [])
    stored_ids = [x for x in stored_ids if x in visible_ids]
    st.session_state["list_checked_application_ids"] = stored_ids

    table_rows = []
    for idx, row in enumerate(rows, start=1):
        app_id = row.get("application_id")
        table_rows.append(
            {
                "선택": app_id in stored_ids,
                "_application_id": app_id,
                "번호": idx,
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "연락처": _safe_str(row.get("phone")),
                "업종": _display_business_type(row),
                "경찰서": _safe_str(row.get("station_label")),
                "접수일시": _format_submitted_text(row.get("submitted_at")),
                "주소": _full_address(row),
                "위도": _format_coord(row.get("latitude")),
                "경도": _format_coord(row.get("longitude")),
                "체감안전도": _safe_int(row.get("felt_safety_score"), 0),
                "CPO위험도": _safe_int(row.get("cpo_risk_score"), 0),
                "보안취약도": _safe_int(row.get("security_vulnerability_score"), 0),
                "총점": _safe_int(row.get("total_score"), 0),
                "상태": _status_label(row.get("current_status")),
            }
        )

    editor_df = pd.DataFrame(table_rows)
    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        disabled=[
            "_application_id",
            "번호",
            "점포명",
            "신청인",
            "연락처",
            "업종",
            "경찰서",
            "접수일시",
            "주소",
            "위도",
            "경도",
            "체감안전도",
            "CPO위험도",
            "보안취약도",
            "총점",
            "상태",
        ],
        column_config={
            "_application_id": None,
            "선택": st.column_config.CheckboxColumn(
                "선택",
                help="체크하면 해당 점포가 아래 지도와 상세정보에 바로 반영되고, 체크한 점포만 다운로드할 수 있습니다.",
            ),
        },
        key="applications_table_editor",
    )

    checked_ids = edited_df.loc[edited_df["선택"] == True, "_application_id"].tolist()
    prev_checked_ids = stored_ids
    st.session_state["list_checked_application_ids"] = checked_ids

    next_selected_id = None
    new_checked_ids = [x for x in checked_ids if x not in prev_checked_ids]
    if new_checked_ids:
        next_selected_id = new_checked_ids[-1]
    elif checked_ids:
        if current_selected_id in checked_ids:
            next_selected_id = current_selected_id
        else:
            next_selected_id = checked_ids[-1]
    else:
        next_selected_id = rows[0].get("application_id")

    if next_selected_id is not None:
        st.session_state["selected_application_id"] = next_selected_id
        st.session_state["selected_application_selectbox"] = next_selected_id

    return checked_ids


def _render_download_selector(rows: List[Dict[str, Any]]) -> List[Any]:
    if not rows:
        return []

    visible_ids = [row.get("application_id") for row in rows]
    stored_ids = st.session_state.get("download_selected_application_ids", [])
    stored_ids = [x for x in stored_ids if x in visible_ids]
    st.session_state["download_selected_application_ids"] = stored_ids

    selector_rows = []
    for idx, row in enumerate(rows, start=1):
        app_id = row.get("application_id")
        selector_rows.append(
            {
                "다운로드": app_id in stored_ids,
                "_application_id": app_id,
                "번호": idx,
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "경찰서": _safe_str(row.get("station_label")),
                "접수일시": _format_submitted_text(row.get("submitted_at")),
                "주소": _full_address(row),
                "상태": _status_label(row.get("current_status")),
            }
        )

    editor_df = pd.DataFrame(selector_rows)
    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        disabled=["_application_id", "번호", "점포명", "신청인", "경찰서", "접수일시", "주소", "상태"],
        column_config={
            "_application_id": None,
            "다운로드": st.column_config.CheckboxColumn(
                "다운로드",
                help="체크한 점포만 별도 다운로드할 수 있습니다.",
            ),
        },
        key="download_target_editor",
    )

    checked_ids = edited_df.loc[edited_df["다운로드"] == True, "_application_id"].tolist()
    st.session_state["download_selected_application_ids"] = checked_ids
    return checked_ids


def _save_review(
    supabase,
    row: Dict[str, Any],
    reviewer_id: str,
    reviewer_station_id: Any,
    risk_label: str,
    review_status_label: str,
    exclude_flag: bool,
    exclude_reason: str,
    review_comment: str,
    docs_request_comment: str,
):
    application_id = row.get("application_id")
    if not application_id:
        raise Exception("application_id가 없습니다.")
    if not reviewer_id:
        raise Exception("로그인 사용자 정보가 없습니다. 다시 로그인해주세요.")

    risk_label = _safe_str(risk_label) or "미입력"
    review_status_label = _safe_str(review_status_label) or "검토완료"
    effective_excluded = bool(exclude_flag) or review_status_label == "제외"
    exclude_reason = _safe_str(exclude_reason)
    review_comment = _safe_str(review_comment)
    docs_request_comment = _safe_str(docs_request_comment)

    if effective_excluded and not exclude_reason:
        raise Exception("제외 대상으로 저장하려면 제외 사유를 입력해주세요.")

    if review_status_label == "추가서류요청" and not docs_request_comment:
        raise Exception("추가서류요청으로 저장하려면 요청 내용을 입력해주세요.")

    review_result = _review_status_value(review_status_label, effective_excluded)
    payload = {
        "application_id": application_id,
        "reviewer_id": reviewer_id,
        "station_id": reviewer_station_id,
        "review_result": review_result,
        "cpo_risk_label": risk_label,
        "cpo_risk_score": CPO_RISK_OPTIONS.get(risk_label, 0),
        "is_excluded": effective_excluded,
        "exclude_reason": exclude_reason,
        "review_comment": review_comment,
        "docs_request_comment": docs_request_comment,
        "reviewed_at": datetime.now().isoformat(),
    }

    supabase.table("cpo_reviews").insert(payload).execute()
    supabase.table("applications").update({"status": review_result}).eq("id", application_id).execute()


def _update_application(
    supabase,
    application_id: Any,
    station_map: Dict[str, Any],
    payload: Dict[str, Any],
):
    if not application_id:
        raise Exception("application_id가 없습니다.")

    station_label = _safe_str(payload.pop("station_label", ""))
    if station_label:
        payload["station_id"] = station_map.get(station_label)
    else:
        payload["station_id"] = None

    supabase.table("applications").update(payload).eq("id", application_id).execute()


def _delete_application(supabase, application_id: Any):
    if not application_id:
        raise Exception("application_id가 없습니다.")
    supabase.table("cpo_reviews").delete().eq("application_id", application_id).execute()
    supabase.table("applications").delete().eq("id", application_id).execute()


def _render_detail_summary_cards(row: Dict[str, Any]):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재 상태", _status_label(row.get("current_status")) or "-")
    c2.metric("체감안전도", f"{_safe_int(row.get('felt_safety_score'), 0)}점")
    c3.metric("CPO위험도", f"{_safe_int(row.get('cpo_risk_score'), 0)}점")
    c4.metric("총점", f"{_safe_int(row.get('total_score'), 0)}점")


def _ensure_edit_state(row: Dict[str, Any], station_options: List[str]):
    application_id = row.get("application_id")
    prefix = f"edit_{application_id}_"
    current_station_label = _safe_str(row.get("station_label"))
    if current_station_label and current_station_label not in station_options:
        station_options = [*station_options, current_station_label]

    defaults = {
        f"{prefix}applicant_name": _safe_str(row.get("applicant_name")),
        f"{prefix}business_name": _safe_str(row.get("business_name")),
        f"{prefix}phone": _safe_str(row.get("phone")),
        f"{prefix}business_type": _safe_str(row.get("business_type")) or "",
        f"{prefix}business_type_other": _safe_str(row.get("business_type_other")),
        f"{prefix}annual_sales": _safe_int(row.get("annual_sales"), 0),
        f"{prefix}sales_band": _safe_str(row.get("sales_band")) or "",
        f"{prefix}station_label": current_station_label if current_station_label in station_options else "",
        f"{prefix}address_query": _safe_str(row.get("address_road")),
        f"{prefix}resolved_address": _safe_str(row.get("address_road")),
        f"{prefix}address_detail": _safe_str(row.get("address_detail")),
        f"{prefix}latitude": _safe_float(row.get("latitude"), 0.0),
        f"{prefix}longitude": _safe_float(row.get("longitude"), 0.0),
        f"{prefix}has_cctv": bool(row.get("has_cctv")),
        f"{prefix}has_emergency_bell": bool(row.get("has_emergency_bell")),
        f"{prefix}uses_security_company": bool(row.get("uses_security_company")),
        f"{prefix}other_security": _safe_str(row.get("other_security")),
        f"{prefix}search_message": "",
        f"{prefix}search_results": [],
        f"{prefix}selected_search_idx": 0,
    }

    bound_id = st.session_state.get("edit_state_bound_application_id")
    if bound_id != application_id:
        for key, value in defaults.items():
            st.session_state[key] = value
        st.session_state["edit_state_bound_application_id"] = application_id
    else:
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value



def _render_application_edit_section(
    row: Dict[str, Any],
    supabase,
    station_map: Dict[str, Any],
    station_options: List[str],
):
    application_id = row.get("application_id")
    prefix = f"edit_{application_id}_"

    current_business_type = _safe_str(row.get("business_type"))
    business_type_options = COMMON_BUSINESS_TYPES.copy()
    if current_business_type and current_business_type not in business_type_options:
        business_type_options.append(current_business_type)

    current_sales_band = _safe_str(row.get("sales_band"))
    sales_band_options = COMMON_SALES_BANDS.copy()
    if current_sales_band and current_sales_band not in sales_band_options:
        sales_band_options.append(current_sales_band)

    station_label_options = [""] + [label for label in station_options if label]
    current_station_label = _safe_str(row.get("station_label"))
    if current_station_label and current_station_label not in station_label_options:
        station_label_options.append(current_station_label)

    _ensure_edit_state(row, station_label_options)

    st.markdown("#### 접수 정보 수정 / 삭제")

    with st.container(border=True):
        st.markdown("##### 점포 위치")
        st.caption("설문지처럼 주소를 검색한 뒤 결과를 선택하면 선택된 주소와 좌표가 자동 반영됩니다. 저장하면 지도 위치도 함께 바뀝니다.")

        c_addr1, c_addr2 = st.columns([5, 1])
        with c_addr1:
            st.text_input(
                "주소 입력",
                key=f"{prefix}address_query",
                placeholder="예: 전라남도 목포시 ○○로 123",
            )
        with c_addr2:
            search_clicked = st.button("주소 검색", key=f"{prefix}search_btn", use_container_width=True)

        if search_clicked:
            try:
                query = _safe_str(st.session_state.get(f"{prefix}address_query"))
                if not query:
                    st.session_state[f"{prefix}search_message"] = "주소를 먼저 입력해주세요."
                    st.session_state[f"{prefix}search_results"] = []
                else:
                    results = _search_juso_addresses(query)
                    st.session_state[f"{prefix}search_results"] = results
                    st.session_state[f"{prefix}selected_search_idx"] = 0
                    if results:
                        st.session_state[f"{prefix}search_message"] = f"검색 결과 {len(results)}건을 찾았습니다. 아래에서 주소를 선택해주세요."
                    else:
                        st.session_state[f"{prefix}search_message"] = "검색 결과가 없습니다. 시/군/구와 도로명, 건물번호를 더 자세히 입력해주세요."
                st.rerun()
            except Exception as exc:
                st.session_state[f"{prefix}search_results"] = []
                st.session_state[f"{prefix}search_message"] = f"주소 검색 실패: {exc}"
                st.rerun()

        msg = _safe_str(st.session_state.get(f"{prefix}search_message"))
        if msg:
            st.caption(msg)

        search_results = st.session_state.get(f"{prefix}search_results", []) or []
        if search_results:
            st.radio(
                "검색 결과",
                list(range(len(search_results))),
                index=min(_safe_int(st.session_state.get(f"{prefix}selected_search_idx"), 0), len(search_results) - 1),
                format_func=lambda i: (
                    f"{_safe_str(search_results[i].get('roadAddr'))} "
                    f"(지번: {_safe_str(search_results[i].get('jibunAddr')) or '-'})"
                ),
                key=f"{prefix}selected_search_idx",
            )

            if st.button("선택한 주소 반영", key=f"{prefix}apply_selected_address_btn", use_container_width=True):
                try:
                    selected_idx = _safe_int(st.session_state.get(f"{prefix}selected_search_idx"), 0)
                    selected = search_results[selected_idx]
                    chosen_address, lat, lon = _resolve_candidate_to_address_and_coord(selected)
                    inferred_station_label = _infer_station_label_from_address(chosen_address, station_label_options)
                    st.session_state[f"{prefix}resolved_address"] = chosen_address
                    st.session_state[f"{prefix}latitude"] = float(lat)
                    st.session_state[f"{prefix}longitude"] = float(lon)
                    st.session_state[f"{prefix}station_label"] = inferred_station_label
                    if inferred_station_label:
                        st.session_state[f"{prefix}search_message"] = (
                            f"선택한 주소를 반영했습니다. 관할 경찰서는 {inferred_station_label}로 자동 설정되었습니다."
                        )
                    else:
                        st.session_state[f"{prefix}search_message"] = (
                            "선택한 주소를 반영했지만 관할 경찰서를 자동 판별하지 못했습니다. "
                            "다른 검색 결과를 선택해주세요."
                        )
                    st.rerun()
                except Exception as exc:
                    st.session_state[f"{prefix}search_message"] = f"주소 반영 실패: {exc}"
                    st.rerun()

        st.text_input(
            "선택된 주소",
            key=f"{prefix}resolved_address",
            placeholder="주소 검색 결과를 선택하면 여기에 반영됩니다.",
            disabled=True,
        )
        st.text_input(
            "상세 주소",
            key=f"{prefix}address_detail",
            placeholder="예: 1층, 101호",
        )

        st.info("선택한 주소 위치가 지도에 반영됩니다. 위치가 맞지 않으면 다른 검색 결과를 선택한 뒤 다시 반영해주세요.")

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("신청인", key=f"{prefix}applicant_name")
        st.text_input("점포명", key=f"{prefix}business_name")
        st.text_input("연락처", key=f"{prefix}phone")
        st.selectbox(
            "업종",
            business_type_options,
            index=business_type_options.index(st.session_state.get(f"{prefix}business_type", "")) if st.session_state.get(f"{prefix}business_type", "") in business_type_options else 0,
            key=f"{prefix}business_type",
        )
        st.text_input("기타 업종", key=f"{prefix}business_type_other")
        st.number_input("연매출", min_value=0, step=100000, key=f"{prefix}annual_sales")
        st.selectbox(
            "연매출 구간",
            sales_band_options,
            index=sales_band_options.index(st.session_state.get(f"{prefix}sales_band", "")) if st.session_state.get(f"{prefix}sales_band", "") in sales_band_options else 0,
            key=f"{prefix}sales_band",
        )

    with c2:
        st.text_input(
            "관할 경찰서(주소 기준 자동반영)",
            value=_safe_str(st.session_state.get(f"{prefix}station_label")),
            disabled=True,
        )
        st.number_input("위도", format="%.6f", key=f"{prefix}latitude")
        st.number_input("경도", format="%.6f", key=f"{prefix}longitude")
        st.checkbox("점포 내 CCTV 있음", key=f"{prefix}has_cctv")
        st.checkbox("비상벨 설치됨", key=f"{prefix}has_emergency_bell")
        st.checkbox("사설경비 이용 중", key=f"{prefix}uses_security_company")
        st.text_input("기타 방범시설", key=f"{prefix}other_security")

    action_col1, action_col2 = st.columns(2)
    with action_col1:
        save_clicked = st.button("상세정보 수정 저장", key=f"{prefix}save_btn", use_container_width=True)
    with action_col2:
        delete_clicked = st.button("접수건 바로 삭제", key=f"delete_application_btn_{application_id}", use_container_width=True)

    if save_clicked:
        try:
            final_address = _safe_str(st.session_state.get(f"{prefix}resolved_address")) or _safe_str(st.session_state.get(f"{prefix}address_query"))
            if not final_address:
                raise Exception("정식 주소가 없습니다. 주소 검색 후 결과를 선택해주세요.")

            lat_to_save = _safe_float(st.session_state.get(f"{prefix}latitude"), 0.0)
            lon_to_save = _safe_float(st.session_state.get(f"{prefix}longitude"), 0.0)

            if not lat_to_save or not lon_to_save:
                lat, lon, official = _coord_from_vworld(final_address)
                if lat is not None and lon is not None:
                    lat_to_save = lat
                    lon_to_save = lon
                    final_address = official or final_address

            if not lat_to_save or not lon_to_save:
                raise Exception("선택한 주소의 좌표를 확인하지 못했습니다. 주소 검색 결과를 다시 선택해주세요.")

            inferred_station_label = _infer_station_label_from_address(final_address, station_label_options)
            if not inferred_station_label:
                raise Exception("정식 주소 기준으로 관할 경찰서를 자동 판별하지 못했습니다. 주소 검색 결과를 다시 선택해주세요.")

            update_payload = {
                "applicant_name": _safe_str(st.session_state.get(f"{prefix}applicant_name")) or None,
                "business_name": _safe_str(st.session_state.get(f"{prefix}business_name")) or None,
                "phone": _safe_str(st.session_state.get(f"{prefix}phone")) or None,
                "business_type": _safe_str(st.session_state.get(f"{prefix}business_type")) or None,
                "business_type_other": _safe_str(st.session_state.get(f"{prefix}business_type_other")) or None,
                "annual_sales": int(_safe_int(st.session_state.get(f"{prefix}annual_sales"), 0)),
                "sales_band": _safe_str(st.session_state.get(f"{prefix}sales_band")) or None,
                "address_road": final_address or None,
                "address_detail": _safe_str(st.session_state.get(f"{prefix}address_detail")) or None,
                "latitude": float(lat_to_save),
                "longitude": float(lon_to_save),
                "has_cctv": bool(st.session_state.get(f"{prefix}has_cctv")),
                "has_emergency_bell": bool(st.session_state.get(f"{prefix}has_emergency_bell")),
                "uses_security_company": bool(st.session_state.get(f"{prefix}uses_security_company")),
                "other_security": _safe_str(st.session_state.get(f"{prefix}other_security")) or None,
                "station_label": inferred_station_label,
            }
            _update_application(
                supabase=supabase,
                application_id=application_id,
                station_map=station_map,
                payload=update_payload,
            )
            st.success(
                f"상세정보가 수정되었습니다. 주소, 좌표, 지도 위치, 관할 경찰서가 {inferred_station_label} 기준으로 함께 반영되었습니다."
            )
            st.rerun()
        except Exception as exc:
            st.error(f"상세정보 수정 실패: {exc}")

    if delete_clicked:
        try:
            _delete_application(supabase, application_id)
            st.session_state.pop("selected_application_id", None)
            st.success("접수건이 삭제되었습니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"삭제 실패: {exc}")

def _render_detail(
    row: Dict[str, Any],
    supabase,
    user_id: str,
    station_id: Any,
    station_map: Dict[str, Any],
    station_options: List[str],
):
    st.markdown("### 점포 상세정보")
    _render_detail_summary_cards(row)

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**점포명**: {_safe_str(row.get('business_name')) or '-'}")
        st.write(f"**신청인**: {_safe_str(row.get('applicant_name')) or '-'}")
        st.write(f"**연락처**: {_safe_str(row.get('phone')) or '-'}")
        st.write(f"**업종**: {_display_business_type(row)}")
        st.write(f"**연매출**: {_display_sales(row)}")
        st.write(f"**연매출 구간**: {_safe_str(row.get('sales_band')) or '-'}")
    with c2:
        st.write(f"**접수일시**: {_format_submitted_text(row.get('submitted_at'))}")
        st.write(f"**관할 경찰서**: {_safe_str(row.get('station_label')) or '-'}")
        st.write(f"**위도**: {_format_coord(row.get('latitude'))}")
        st.write(f"**경도**: {_format_coord(row.get('longitude'))}")
        st.write(f"**비상벨 설치 여부**: {'있음' if bool(row.get('has_emergency_bell')) else '없음'}")
        st.write(f"**사설경비 이용 여부**: {'이용 중' if bool(row.get('uses_security_company')) else '이용하지 않음'}")

    st.markdown("#### 위치 정보")
    st.write(f"**주소**: {_full_address(row)}")

    st.markdown("#### 설문 응답")
    s1, s2 = st.columns(2)
    with s1:
        st.write(f"- 범죄 불안 경험: {_safe_str(row.get('survey_crime_anxiety')) or '-'}")
        st.write(f"- 야간 영업 여부: {_safe_str(row.get('survey_late_night')) or '-'}")
        st.write(f"- 주변 환경: {_safe_str(row.get('survey_dark_area')) or '-'}")
        st.write(f"- 단독 근무: {_safe_str(row.get('survey_single_worker')) or '-'}")
    with s2:
        st.write(f"- 점포 내 CCTV: {'있음' if bool(row.get('has_cctv')) else '없음'}")
        st.write(f"- 사설경비 이용: {'이용 중' if bool(row.get('uses_security_company')) else '이용하지 않음'}")
        st.write(f"- 비상벨 설치: {'있음' if bool(row.get('has_emergency_bell')) else '없음'}")
        st.write(f"- 기타 방범시설: {_safe_str(row.get('other_security')) or '-'}")

    if _safe_str(row.get("apply_reason")):
        st.markdown("#### 신청 사유")
        st.write(_safe_str(row.get("apply_reason")))

    st.markdown("#### 자동 산출 점수")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("체감안전도", f"{_safe_int(row.get('felt_safety_score'), 0)}점")
    a2.metric("보안취약도", f"{_safe_int(row.get('security_vulnerability_score'), 0)}점")
    a3.metric("CPO위험도", f"{_safe_int(row.get('cpo_risk_score'), 0)}점")
    a4.metric("현재 총점", f"{_safe_int(row.get('total_score'), 0)}점")

    _render_application_edit_section(
        row=row,
        supabase=supabase,
        station_map=station_map,
        station_options=station_options,
    )

    st.markdown("#### CPO 검토 입력")
    st.caption("검토 결과를 저장하면 cpo_reviews에 이력이 쌓이고, applications의 현재 상태도 함께 변경됩니다.")

    with st.form(f"review_form_{row.get('application_id')}"):
        risk_labels = list(CPO_RISK_OPTIONS.keys())
        current_risk_label = _safe_str(row.get("cpo_risk_label")) or "미입력"
        risk_index = risk_labels.index(current_risk_label) if current_risk_label in risk_labels else 0

        review_status_default = _status_label(row.get("current_status"))
        if review_status_default not in REVIEW_STATUS_OPTIONS:
            review_status_default = "검토완료"

        r1, r2 = st.columns(2)
        with r1:
            review_status = st.selectbox(
                "검토 상태",
                REVIEW_STATUS_OPTIONS,
                index=REVIEW_STATUS_OPTIONS.index(review_status_default),
            )
        with r2:
            risk_label = st.selectbox(
                "CPO 위험도",
                risk_labels,
                index=risk_index,
            )

        exclude_flag = st.checkbox(
            "우선순위 제외 대상",
            value=bool(row.get("is_excluded")) or review_status == "제외",
        )
        exclude_reason = st.text_input("제외 사유", value=_safe_str(row.get("exclude_reason")))
        review_comment = st.text_area("검토 메모", value=_safe_str(row.get("review_comment")), height=100)
        docs_request_comment = st.text_area(
            "추가서류 요청 내용",
            value=_safe_str(row.get("docs_request_comment")),
            height=80,
            placeholder="예: 사업자등록증, 최근 매출현황 증빙자료 제출 요청",
        )
        submitted = st.form_submit_button("검토 저장", use_container_width=True)

        if submitted:
            try:
                _save_review(
                    supabase=supabase,
                    row=row,
                    reviewer_id=user_id,
                    reviewer_station_id=station_id,
                    risk_label=risk_label,
                    review_status_label=review_status,
                    exclude_flag=exclude_flag,
                    exclude_reason=exclude_reason,
                    review_comment=review_comment,
                    docs_request_comment=docs_request_comment,
                )
                st.success("검토 결과가 저장되었습니다.")
                st.rerun()
            except Exception as exc:
                st.error(f"저장 실패: {exc}")


def cpo_page(supabase, role: str, station: str, station_options: List[str]):
    selected_station = _safe_str(station)
    user_id = _safe_str(st.session_state.get("uid"))
    station_id = st.session_state.get("station_id")
    station_map = _fetch_station_map(supabase)
    station_label_options = _unique_station_options((station_options or []) + list(station_map.keys()))

    st.title("전남경찰청 CPO 관리시스템")

    raw_rows = _fetch_rows(supabase)

    today = date.today()
    default_from = today - timedelta(days=30)

    if role == "admin":
        admin_station_options = ["전체"] + station_label_options
        admin_station_default = st.session_state.get("admin_station_filter") or "전체"
        if admin_station_default not in admin_station_options:
            admin_station_default = "전체"

        st.caption(f"현재 선택 경찰서: {admin_station_default}")

        f0, f1, f2, f3, f4 = st.columns([2, 2, 2, 2, 3])
        with f0:
            selected_station = st.selectbox(
                "경찰서",
                admin_station_options,
                index=admin_station_options.index(admin_station_default),
                key="admin_station_filter",
            )
        with f1:
            status_filter = st.selectbox("상태", STATUS_FILTER_OPTIONS, index=0, key="status_filter")
        with f2:
            date_from = st.date_input("접수 시작일", value=default_from, key="date_from")
        with f3:
            date_to = st.date_input("접수 종료일", value=today, key="date_to")
        with f4:
            keyword = st.text_input("점포명 / 신청인 / 주소 검색", key="keyword")
    else:
        st.caption(f"관할 경찰서: {selected_station}")

        f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
        with f1:
            status_filter = st.selectbox("상태", STATUS_FILTER_OPTIONS, index=0, key="status_filter")
        with f2:
            date_from = st.date_input("접수 시작일", value=default_from, key="date_from")
        with f3:
            date_to = st.date_input("접수 종료일", value=today, key="date_to")
        with f4:
            keyword = st.text_input("점포명 / 신청인 / 주소 검색", key="keyword")

    filtered_rows = _apply_filters(
        rows=raw_rows,
        role=role,
        selected_station=selected_station,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
    )

    _render_top_metrics(filtered_rows)
    _render_score_guide()
    _render_priority_table(filtered_rows)

    checked_ids_for_download = st.session_state.get("list_checked_application_ids", [])
    checked_export_rows = [row for row in filtered_rows if row.get("application_id") in checked_ids_for_download]
    checked_export_df = _build_export_df(checked_export_rows) if checked_export_rows else pd.DataFrame()
    all_export_df = _build_export_df(filtered_rows) if filtered_rows else pd.DataFrame()

    list_title_col, list_btn1_col, list_btn2_col = st.columns([4, 1, 1])
    with list_title_col:
        st.markdown("### 접수 목록 현황")
        st.caption(
            f"목록에서 체크하면 해당 점포가 아래 지도와 상세정보에 바로 반영됩니다. 현재 체크 {len(checked_export_rows)}건 / 조회 결과 {len(filtered_rows)}건"
        )
    with list_btn1_col:
        st.write("")
        st.download_button(
            "체크한 건 다운로드",
            data=_df_to_excel_bytes(checked_export_df) if not checked_export_df.empty else b"",
            file_name=f"applications_checked_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_checked_applications_top",
            disabled=checked_export_df.empty,
        )
    with list_btn2_col:
        st.write("")
        st.download_button(
            "조회 결과 전체 다운로드",
            data=_df_to_excel_bytes(all_export_df) if not all_export_df.empty else b"",
            file_name=f"applications_all_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_all_applications_top",
            disabled=all_export_df.empty,
        )

    checked_ids = _render_list_table(filtered_rows)

    st.markdown("### 접수 현황 지도")
    selected_row = _selected_row(filtered_rows)

    if filtered_rows:
        _sync_selected_row_by_selectbox(filtered_rows)
        selected_row = _selected_row(filtered_rows)

        n1, n2, n3 = st.columns([1, 1, 3])
        with n1:
            if st.button("이전 점포", use_container_width=True):
                ids = [row.get("application_id") for row in filtered_rows]
                current_id = st.session_state.get("selected_application_id")
                if current_id not in ids:
                    st.session_state["selected_application_id"] = ids[0]
                    st.session_state["selected_application_selectbox"] = ids[0]
                else:
                    idx = ids.index(current_id)
                    st.session_state["selected_application_id"] = ids[max(0, idx - 1)]
                st.session_state["selected_application_selectbox"] = st.session_state.get("selected_application_id")
                st.rerun()
        with n2:
            if st.button("다음 점포", use_container_width=True):
                ids = [row.get("application_id") for row in filtered_rows]
                current_id = st.session_state.get("selected_application_id")
                if current_id not in ids:
                    st.session_state["selected_application_id"] = ids[0]
                    st.session_state["selected_application_selectbox"] = ids[0]
                else:
                    idx = ids.index(current_id)
                    st.session_state["selected_application_id"] = ids[min(len(ids) - 1, idx + 1)]
                st.session_state["selected_application_selectbox"] = st.session_state.get("selected_application_id")
                st.rerun()
        with n3:
            st.caption("접수 목록이나 선택 점포를 바꾸면 지도와 아래 상세정보가 함께 바뀝니다.")

        _render_map(filtered_rows, selected_row)

        if selected_row:
            st.caption(
                f"현재 선택: {_safe_str(selected_row.get('business_name'))} / "
                f"위도 {_format_coord(selected_row.get('latitude'))} / "
                f"경도 {_format_coord(selected_row.get('longitude'))}"
            )
    else:
        st.info("조회 결과가 없습니다.")

    if not filtered_rows or not selected_row:
        st.info("상세정보를 표시할 접수 건이 없습니다.")
    else:
        _render_detail(
            row=selected_row,
            supabase=supabase,
            user_id=user_id,
            station_id=station_id,
            station_map=station_map,
            station_options=station_label_options,
        )
