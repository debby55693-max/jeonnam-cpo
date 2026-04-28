from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st
from pyproj import Transformer

try:
    from core.scoring import (
        FIELD_OPTIONS,
        compute_precas_scores_batch,
        compute_total_score,
        score_breakdown,
    )
    from core.report import generate_report, generate_report_zip
except Exception:
    from admin_app.core.scoring import (
        FIELD_OPTIONS,
        compute_precas_scores_batch,
        compute_total_score,
        score_breakdown,
    )
    from admin_app.core.report import generate_report, generate_report_zip


STATUS_LABELS = {
    "submitted": "접수완료",
    "under_review": "검토중",
    "docs_requested": "추가서류요청",
    "reviewed": "검토완료",
    "selection_considered": "선정고려",
    "excluded": "제외",
    "selected": "선정",
}

STATUS_DISPLAY_META = {
    "접수완료": {"icon": "⚪", "class": "submitted"},
    "검토중": {"icon": "🟣", "class": "under-review"},
    "추가서류요청": {"icon": "🟠", "class": "docs-requested"},
    "검토완료": {"icon": "🔵", "class": "reviewed"},
    "선정고려": {"icon": "🟡", "class": "reviewed"},
    "제외": {"icon": "⛔", "class": "excluded"},
    "선정": {"icon": "🟢", "class": "selected"},
}

STATUS_FILTER_OPTIONS = ["전체", "접수완료", "검토중", "추가서류요청", "검토완료", "선정고려", "제외", "선정"]
STATUS_VALUE_BY_LABEL = {v: k for k, v in STATUS_LABELS.items()}

CPO_RISK_OPTIONS = {
    "미입력": 0,
    "매우 높음": 50,
    "높음": 40,
    "보통": 25,
    "낮음": 10,
    "매우 낮음": 0,
}

REVIEW_STATUS_OPTIONS = ["검토중", "추가서류요청", "검토완료", "선정고려", "선정", "제외"]
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


def _status_display_text(value: Any) -> str:
    label = _status_label(_safe_str(value))
    meta = STATUS_DISPLAY_META.get(label)
    if not meta:
        return label or "-"
    return f"{meta['icon']} {label}"


def _status_badge_html(value: Any) -> str:
    label = _status_label(_safe_str(value))
    meta = STATUS_DISPLAY_META.get(label, {"class": "neutral"})
    css_class = meta.get("class", "neutral")
    return f'<span class="cpo-status-chip {css_class}">{label or "-"}</span>'


def _status_summary_html(counts: Dict[str, int]) -> str:
    ordered_labels = ["접수완료", "검토중", "추가서류요청", "검토완료", "선정고려", "제외", "선정"]
    chips = []
    for label in ordered_labels:
        meta = STATUS_DISPLAY_META.get(label, {"class": "neutral"})
        css_class = meta.get("class", "neutral")
        count = counts.get(label, 0)
        chips.append(f'<span class="cpo-status-chip {css_class}">{label} {count}건</span>')
    return '<div class="cpo-status-chip-row">' + ''.join(chips) + '</div>'


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


def _yes_no(value: Any) -> str:
    return "예" if bool(value) else "아니오"


def _security_company_text(value: Any) -> str:
    return "이용 중" if bool(value) else "이용하지 않음"


def _coord_for_export(value: Any) -> Any:
    num = _safe_float(value, 0.0)
    return round(num, 6) if num else ""


def _current_precas_scores() -> Dict[Any, Dict[str, Any]]:
    rows = st.session_state.get("current_filtered_rows_for_scoring", [])
    return compute_precas_scores_batch(rows)


def _score_bd(row: Dict[str, Any]) -> Dict[str, Any]:
    return score_breakdown(row, _current_precas_scores())


def _felt_safety_score(row: Dict[str, Any]) -> float:
    return float(_score_bd(row).get("felt_safety", 0.0))


def _survey_environment_score(row: Dict[str, Any]) -> float:
    return float(_score_bd(row).get("survey_env", 0.0))


def _field_survey_score(row: Dict[str, Any]) -> float:
    return float(_score_bd(row).get("field_total", 0.0))


def _precas_score(row: Dict[str, Any]) -> float:
    return float(_score_bd(row).get("precas_total", 0.0))


def _discretionary_score(row: Dict[str, Any]) -> float:
    return float(_score_bd(row).get("discretionary", 0.0))


def _total_score(row: Dict[str, Any]) -> float:
    return compute_total_score(row, _current_precas_scores())


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


def _inject_page_styles():
    st.markdown(
        """
        <style>
        .cpo-step-title {
            margin: 20px 0 12px 0;
            padding: 0 0 12px 0;
            border-bottom: 3px solid #D7E3F4;
        }
        .cpo-step-badge {
            display: inline-block;
            min-width: 34px;
            height: 34px;
            line-height: 34px;
            text-align: center;
            border-radius: 999px;
            background: #E8F1FF;
            color: #1E40AF;
            font-weight: 800;
            margin-right: 10px;
            font-size: 16px;
            vertical-align: middle;
        }
        .cpo-step-text {
            display: inline-block;
            font-size: 26px;
            font-weight: 800;
            color: #0F172A;
            letter-spacing: -0.2px;
            vertical-align: middle;
        }
        .cpo-step-help {
            margin-top: 7px;
            margin-left: 46px;
            color: #475569;
            font-size: 13px;
            line-height: 1.5;
        }
        .cpo-inline-guide {
            padding: 0 0 10px 0;
            color: #475569;
            font-size: 13px;
            line-height: 1.6;
        }
        .cpo-inline-guide a {
            color: #1D4ED8;
            text-decoration: none;
            font-weight: 700;
        }
        .cpo-page-note {
            margin: 2px 0 6px 0;
            color: #334155;
            font-size: 14px;
            font-weight: 600;
        }
        .cpo-subtle-note {
            margin: 4px 0 10px 0;
            color: #64748B;
            font-size: 12px;
        }
        .cpo-list-toolbar-label {
            margin-top: 10px;
            color: #334155;
            font-size: 13px;
            font-weight: 600;
        }
        .cpo-status-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 10px 0 2px 0;
        }
        .cpo-status-chip {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 30px;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            border: 1px solid transparent;
            white-space: nowrap;
        }
        .cpo-status-chip.neutral {
            background: #F8FAFC;
            color: #334155;
            border-color: #CBD5E1;
        }
        .cpo-status-chip.submitted {
            background: #F8FAFC;
            color: #475569;
            border-color: #CBD5E1;
        }
        .cpo-status-chip.under-review {
            background: #F5F3FF;
            color: #6D28D9;
            border-color: #DDD6FE;
        }
        .cpo-status-chip.docs-requested {
            background: #FFF7ED;
            color: #C2410C;
            border-color: #FED7AA;
        }
        .cpo-status-chip.reviewed {
            background: #EFF6FF;
            color: #1D4ED8;
            border-color: #BFDBFE;
        }
        .cpo-status-chip.excluded {
            background: #FEF2F2;
            color: #B91C1C;
            border-color: #FECACA;
        }
        .cpo-status-chip.selected {
            background: #F0FDF4;
            color: #15803D;
            border-color: #BBF7D0;
        }
        .cpo-status-current-row {
            margin: 4px 0 12px 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_section_heading(step_no: str, title: str, help_text: str = ""):
    help_html = f'<div class="cpo-step-help">{help_text}</div>' if help_text else ""
    st.markdown(
        f"""
        <div class="cpo-step-title">
            <span class="cpo-step-badge">{step_no}</span>
            <span class="cpo-step-text">{title}</span>
            {help_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


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
            -_total_score(x),
            _to_dt(x.get("submitted_at")) or datetime.min,
        ),
        reverse=False,
    )
    return result


def _summary_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {
        "총 접수": len(rows),
        "검토완료": 0,
        "선정고려": 0,
        "선정": 0,
        "제외": 0,
        "미검토": 0,
    }
    for row in rows:
        status = _status_label(row.get("current_status"))
        if status == "검토완료":
            counts["검토완료"] += 1
        elif status == "선정고려":
            counts["선정고려"] += 1
        elif status == "선정":
            counts["선정"] += 1
        elif status == "제외":
            counts["제외"] += 1
        elif status in ["접수완료", "검토중", "추가서류요청"]:
            counts["미검토"] += 1
    return counts


def _df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="data", index=False)
    return output.getvalue()


def _sanitize_filename_text(value: Any, fallback: str = "all") -> str:
    text = _safe_str(value)
    if not text or text == "전체":
        return fallback
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z가-힣_\-]", "", text)
    return text or fallback


def _build_download_filename(
    kind: str,
    selected_station: str,
    status_filter: str,
    date_from: date,
    date_to: date,
    row_count: int,
) -> str:
    station_part = _sanitize_filename_text(selected_station, fallback="all_station")
    status_part = _sanitize_filename_text(status_filter, fallback="all_status")
    date_part = f"{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}"
    return f"applications_{kind}_{station_part}_{status_part}_{date_part}_{row_count}건.xlsx"


def _bump_table_editor_nonce():
    st.session_state["applications_table_editor_nonce"] = int(st.session_state.get("applications_table_editor_nonce", 0)) + 1


def _bulk_check_rows(rows: List[Dict[str, Any]]):
    visible_ids = [row.get("application_id") for row in rows if row.get("application_id") is not None]
    st.session_state["list_checked_application_ids"] = visible_ids
    if visible_ids:
        st.session_state["selected_application_id"] = visible_ids[0]
        st.session_state["selected_application_selectbox"] = visible_ids[0]
    _bump_table_editor_nonce()


def _clear_checked_rows(rows: List[Dict[str, Any]]):
    visible_ids = {row.get("application_id") for row in rows if row.get("application_id") is not None}
    stored_ids = st.session_state.get("list_checked_application_ids", [])
    st.session_state["list_checked_application_ids"] = [x for x in stored_ids if x not in visible_ids]
    if rows and st.session_state.get("selected_application_id") not in visible_ids:
        first_id = rows[0].get("application_id")
        st.session_state["selected_application_id"] = first_id
        st.session_state["selected_application_selectbox"] = first_id
    _bump_table_editor_nonce()


def _build_export_df(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    data = []
    for idx, row in enumerate(rows, start=1):
        bd = _score_bd(row)
        data.append(
            {
                "번호": idx,
                "신청ID": _safe_str(row.get("application_id")),
                "현재상태": _status_label(row.get("current_status")),
                "접수일시": _format_submitted_text(row.get("submitted_at")),
                "관할경찰서": _safe_str(row.get("station_label")),
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "연락처": _safe_str(row.get("phone")),
                "업종": _display_business_type(row),
                "연매출구간": _safe_str(row.get("sales_band")),
                "연매출(원)": _safe_int(row.get("annual_sales"), 0),
                "주소": _full_address(row),
                "도로명주소": _safe_str(row.get("address_road")),
                "상세주소": _safe_str(row.get("address_detail")),
                "지번주소": _safe_str(row.get("address_jibun")),
                "위도": _coord_for_export(row.get("latitude")),
                "경도": _coord_for_export(row.get("longitude")),
                "프리카스_112신고건수": row.get("precas_112_count"),
                "프리카스_위험도등급": row.get("precas_risk_grade"),
                "프리카스_탄력순찰수": row.get("precas_patrol_count"),
                "프리카스점수": bd.get("precas_total", 0),
                "환경조사점수": bd.get("field_total", 0),
                "점포환경설문": bd.get("survey_env", 0),
                "체감안전도": bd.get("felt_safety", 0),
                "CPO재량점수": bd.get("discretionary", 0),
                "총점": bd.get("total", 0),
                "범죄불안경험": _safe_str(row.get("survey_crime_anxiety")),
                "야간영업여부": _safe_str(row.get("survey_late_night")),
                "주변환경": _safe_str(row.get("survey_dark_area")),
                "단독근무": _safe_str(row.get("survey_single_worker")),
                "점포내CCTV": _yes_no(row.get("has_cctv")),
                "비상벨설치": _yes_no(row.get("has_emergency_bell")),
                "사설경비이용": _security_company_text(row.get("uses_security_company")),
                "희망물품": _safe_str(row.get("requested_item")),
                "기타방범시설": _safe_str(row.get("other_security")),
                "신청사유": _safe_str(row.get("apply_reason")),
                "기타메모": _safe_str(row.get("etc_note")),
                "검토의견": _safe_str(row.get("review_comment")),
                "추가서류요청내용": _safe_str(row.get("docs_request_comment")),
                "제외사유": _safe_str(row.get("exclude_reason")),
                "CPO재량사유": _safe_str(row.get("cpo_discretionary_reason")),
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
                    f"{_status_display_text(row.get('current_status'))} | 총점 {_total_score(row)}점 | "
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
            f"총점: {_total_score(row)}점"
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
    with st.expander("점수 산정 기준 보기", expanded=True):
        st.markdown(
            """
**우선순위는 아래 항목을 합산하여 산정합니다.**

**총점 = 프리카스 데이터(40점) + CPO 현장 환경조사(20점) + 신청인 설문(30점) + CPO 재량점수(10점)**

- **프리카스 데이터(40점)**: 112신고 건수 16점, 위험도 등급 14점, 탄력순찰 수 10점
- **CPO 현장 환경조사(20점)**: 주변 환경, 위치, 조명, 파출소 거리, 취약시설, 공공 CCTV, 심야 유동인구, 건물 노후도
- **신청인 설문(30점)**: 점포환경 7항목 25점 + 체감안전도 5문항 5점
- **CPO 재량점수(10점)**: 객관지표 외 현장 위험도 반영. 5점 초과 시 사유 필수, 8점 이상 시 구체 사유 필수

※ 프리카스 점수는 112신고건수, 위험도등급, 탄력순찰수를 모두 입력한 건만 상대평가로 산정됩니다.
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

    filtered.sort(key=lambda x: _total_score(x), reverse=True)
    filtered = filtered[:top_n]

    table_rows = []
    for idx, row in enumerate(filtered, start=1):
        bd = _score_bd(row)
        table_rows.append(
            {
                "순위": idx,
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "경찰서": _safe_str(row.get("station_label")),
                "업종": _display_business_type(row),
                "희망물품": _safe_str(row.get("requested_item")) or "-",
                "프리카스": bd.get("precas_total", 0),
                "환경조사": bd.get("field_total", 0),
                "점포환경설문": bd.get("survey_env", 0),
                "체감안전도": bd.get("felt_safety", 0),
                "CPO재량": bd.get("discretionary", 0),
                "총점": bd.get("total", 0),
                "상태": _status_display_text(row.get("current_status")),
            }
        )

    if table_rows:
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)
    else:
        st.info("우선 검토 대상이 없습니다.")


def _render_metric_card(value: int, label: str, css_class: str, unit: str = "건") -> str:
    return (
        f'<div class="cpo-metric-card {css_class}">'
        f'<div class="cpo-mc-label">{label}</div>'
        f'<div class="cpo-mc-value">{value}<span class="cpo-mc-unit">{unit}</span></div>'
        f'</div>'
    )


def _render_top_metrics(rows: List[Dict[str, Any]]):
    counts = _summary_counts(rows)
    cards_html = (
        '<div class="cpo-metrics-row">'
        + _render_metric_card(counts["총 접수"],  "📋 총 접수",   "cpo-mc-total")
        + _render_metric_card(counts["검토완료"],  "✅ 검토완료",  "cpo-mc-reviewed")
        + _render_metric_card(counts["선정고려"],  "⭐ 선정고려",  "cpo-mc-consider")
        + _render_metric_card(counts["선정"],      "🎯 선정",      "cpo-mc-selected")
        + _render_metric_card(counts["제외"],      "🚫 제외",      "cpo-mc-excluded")
        + _render_metric_card(counts["미검토"],    "⏳ 미검토",    "cpo-mc-pending")
        + '</div>'
    )
    st.markdown(cards_html, unsafe_allow_html=True)


def _render_page_ui_css():
    st.markdown(
        """
        <style>
        /* ── 전체 레이아웃 ── */
        .block-container {
            max-width: 1520px;
            padding-top: 0.6rem;
            padding-bottom: 2.4rem;
        }
        h1, h2, h3 { letter-spacing: -0.3px; }

        /* ── 페이지 헤더 배너 ── */
        .cpo-page-header {
            background: linear-gradient(135deg, #1a3f7a 0%, #2563eb 60%, #3b82f6 100%);
            border-radius: 18px;
            padding: 22px 28px;
            margin-bottom: 20px;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
        }
        .cpo-page-header-title {
            font-size: 22px;
            font-weight: 800;
            letter-spacing: -0.3px;
        }
        .cpo-page-header-sub {
            margin-top: 4px;
            font-size: 13px;
            opacity: 0.85;
        }
        .cpo-page-header-badge {
            background: rgba(255,255,255,0.18);
            border: 1px solid rgba(255,255,255,0.3);
            border-radius: 12px;
            padding: 8px 18px;
            font-size: 13px;
            font-weight: 700;
            white-space: nowrap;
        }

        /* ── 컬러 메트릭 카드 ── */
        .cpo-metrics-row {
            display: flex;
            gap: 10px;
            margin: 12px 0 20px 0;
            flex-wrap: wrap;
        }
        .cpo-metric-card {
            flex: 1;
            min-width: 120px;
            border-radius: 14px;
            padding: 14px 16px 12px;
            border: 1px solid transparent;
            position: relative;
            overflow: hidden;
        }
        .cpo-metric-card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            border-radius: 14px 14px 0 0;
        }
        .cpo-metric-card .cpo-mc-label {
            font-size: 12px;
            font-weight: 700;
            letter-spacing: 0.2px;
            margin-bottom: 6px;
        }
        .cpo-metric-card .cpo-mc-value {
            font-size: 26px;
            font-weight: 800;
            line-height: 1;
        }
        .cpo-metric-card .cpo-mc-unit {
            font-size: 12px;
            font-weight: 600;
            opacity: 0.7;
            margin-left: 2px;
        }
        /* 색상 변형 */
        .cpo-mc-total    { background:#f0f6ff; border-color:#bfdbfe; }
        .cpo-mc-total::before    { background:#2563eb; }
        .cpo-mc-total    .cpo-mc-label { color:#1e40af; }
        .cpo-mc-total    .cpo-mc-value { color:#1e3a8a; }

        .cpo-mc-reviewed { background:#f0fdf4; border-color:#bbf7d0; }
        .cpo-mc-reviewed::before { background:#16a34a; }
        .cpo-mc-reviewed .cpo-mc-label { color:#15803d; }
        .cpo-mc-reviewed .cpo-mc-value { color:#14532d; }

        .cpo-mc-consider { background:#fffbeb; border-color:#fde68a; }
        .cpo-mc-consider::before { background:#d97706; }
        .cpo-mc-consider .cpo-mc-label { color:#92400e; }
        .cpo-mc-consider .cpo-mc-value { color:#78350f; }

        .cpo-mc-selected { background:#ecfdf5; border-color:#6ee7b7; }
        .cpo-mc-selected::before { background:#059669; }
        .cpo-mc-selected .cpo-mc-label { color:#065f46; }
        .cpo-mc-selected .cpo-mc-value { color:#064e3b; }

        .cpo-mc-excluded { background:#fff1f2; border-color:#fecdd3; }
        .cpo-mc-excluded::before { background:#dc2626; }
        .cpo-mc-excluded .cpo-mc-label { color:#991b1b; }
        .cpo-mc-excluded .cpo-mc-value { color:#7f1d1d; }

        .cpo-mc-pending  { background:#f8fafc; border-color:#cbd5e1; }
        .cpo-mc-pending::before  { background:#94a3b8; }
        .cpo-mc-pending  .cpo-mc-label { color:#475569; }
        .cpo-mc-pending  .cpo-mc-value { color:#334155; }

        /* ── 리포트 패널 ── */
        .cpo-report-panel {
            background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
            border-radius: 16px;
            padding: 18px 22px;
            margin-bottom: 12px;
            display: flex;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }
        .cpo-report-panel-icon {
            font-size: 28px;
            flex-shrink: 0;
        }
        .cpo-report-panel-text {
            flex: 1;
        }
        .cpo-report-panel-title {
            font-size: 15px;
            font-weight: 800;
            color: #ffffff;
        }
        .cpo-report-panel-desc {
            font-size: 12px;
            color: rgba(255,255,255,0.75);
            margin-top: 3px;
        }

        /* ── 필터 영역 ── */
        .cpo-filter-area {
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 14px;
            padding: 14px 18px;
            margin-bottom: 16px;
        }

        /* ── 섹션 헤딩 ── */
        .cpo-step-title {
            margin: 20px 0 12px 0;
            padding: 0 0 10px 0;
            border-bottom: 2px solid #e2e8f0;
        }
        .cpo-step-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: linear-gradient(135deg, #2563eb, #3b82f6);
            color: #ffffff;
            font-weight: 800;
            margin-right: 10px;
            font-size: 14px;
            vertical-align: middle;
        }
        .cpo-step-text {
            display: inline-block;
            font-size: 22px;
            font-weight: 800;
            color: #0f172a;
            letter-spacing: -0.3px;
            vertical-align: middle;
        }
        .cpo-step-help {
            margin-top: 6px;
            margin-left: 42px;
            color: #64748b;
            font-size: 13px;
        }

        /* ── 공통 텍스트 ── */
        .cpo-inline-guide { padding: 0 0 8px 0; color: #64748b; font-size: 13px; line-height: 1.6; }
        .cpo-inline-guide a { color: #2563eb; text-decoration: none; font-weight: 700; }
        .cpo-page-note { margin: 2px 0 4px; color: #334155; font-size: 14px; font-weight: 600; }
        .cpo-subtle-note { margin: 3px 0 8px; color: #64748b; font-size: 12px; }
        .cpo-list-toolbar-label { margin-top: 8px; color: #334155; font-size: 13px; font-weight: 600; }

        /* ── 상태 배지 ── */
        .cpo-status-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 2px; }
        .cpo-status-chip {
            display: inline-flex; align-items: center; justify-content: center;
            min-height: 28px; padding: 3px 12px; border-radius: 999px;
            font-size: 12px; font-weight: 700; border: 1px solid transparent; white-space: nowrap;
        }
        .cpo-status-chip.neutral   { background:#f8fafc; color:#334155; border-color:#cbd5e1; }
        .cpo-status-chip.submitted { background:#f8fafc; color:#475569; border-color:#cbd5e1; }
        .cpo-status-chip.under-review    { background:#f5f3ff; color:#6d28d9; border-color:#ddd6fe; }
        .cpo-status-chip.docs-requested  { background:#fff7ed; color:#c2410c; border-color:#fed7aa; }
        .cpo-status-chip.reviewed        { background:#eff6ff; color:#1d4ed8; border-color:#bfdbfe; }
        .cpo-status-chip.excluded        { background:#fef2f2; color:#b91c1c; border-color:#fecaca; }
        .cpo-status-chip.selected        { background:#f0fdf4; color:#15803d; border-color:#bbf7d0; }
        .cpo-status-current-row { margin: 4px 0 10px; }

        /* ── 버튼 ── */
        div[data-testid="stButton"] > button,
        div[data-testid="stDownloadButton"] > button {
            min-height: 40px; font-weight: 600; border-radius: 10px;
        }
        /* ── 라벨 ── */
        div[data-testid="stTextInput"] label,
        div[data-testid="stSelectbox"] label,
        div[data-testid="stDateInput"] label,
        div[data-testid="stNumberInput"] label,
        div[data-testid="stTextArea"] label,
        div[data-testid="stCheckbox"] label,
        div[data-testid="stRadio"] label { font-weight: 600; }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
                "희망물품": _safe_str(row.get("requested_item")) or "-",
                "프리카스": _score_bd(row).get("precas_total", 0),
                "환경조사": _score_bd(row).get("field_total", 0),
                "점포환경설문": _score_bd(row).get("survey_env", 0),
                "체감안전도": _score_bd(row).get("felt_safety", 0),
                "CPO재량": _score_bd(row).get("discretionary", 0),
                "총점": _total_score(row),
                "상태": _status_display_text(row.get("current_status")),
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
            "희망물품",
            "프리카스",
            "환경조사",
            "점포환경설문",
            "체감안전도",
            "CPO재량",
            "총점",
            "상태",
        ],
        column_config={
            "_application_id": None,
            "선택": st.column_config.CheckboxColumn(
                "선택",
                help="체크하면 해당 점포가 아래 지도와 상세정보에 바로 반영되고, 체크한 점포만 다운로드할 수 있습니다.",
            ),
            "희망물품": st.column_config.TextColumn(
                "희망물품",
                help="점주가 신청서에서 선택한 지원 물품",
                width="medium",
            ),
        },
        key=f"applications_table_editor_{int(st.session_state.get('applications_table_editor_nonce', 0))}",
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


def _to_nullable_int(value: Any) -> Optional[int]:
    text = _safe_str(value)
    if text == "":
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _to_nullable_float(value: Any) -> Optional[float]:
    text = _safe_str(value)
    if text == "":
        return None
    try:
        return float(text)
    except Exception:
        return None


def _normalize_field_value(value: Any) -> Optional[str]:
    text = _safe_str(value)
    if not text or text == "미입력":
        return None
    return text


def _save_review(
    supabase,
    row: Dict[str, Any],
    reviewer_id: str,
    reviewer_station_id: Any,
    review_status_label: str,
    exclude_flag: bool,
    exclude_reason: str,
    review_comment: str,
    docs_request_comment: str,
    precas_112_count: Any,
    precas_risk_grade: Any,
    precas_patrol_count: Any,
    field_neighborhood_type: str,
    field_location_type: str,
    field_lighting: str,
    field_police_distance: str,
    field_vulnerable_facilities: str,
    field_public_cctv: str,
    field_foot_traffic: str,
    field_building_condition: str,
    cpo_discretionary_score: Any,
    cpo_discretionary_reason: str,
):
    application_id = row.get("application_id")
    if not application_id:
        raise Exception("application_id가 없습니다.")

    review_result = _review_status_value(review_status_label, exclude_flag)
    final_excluded = bool(exclude_flag) or review_result == "excluded"

    payload = {
        "application_id": application_id,
        "reviewer_id": reviewer_id,
        "station_id": _to_nullable_int(reviewer_station_id),
        "review_result": review_result,

        # 예전 컬럼 호환용: 새 점수체계에서는 사용하지 않음
        "cpo_risk_label": None,
        "cpo_risk_score": None,

        "is_excluded": final_excluded,
        "exclude_reason": _safe_str(exclude_reason),
        "review_comment": _safe_str(review_comment),
        "docs_request_comment": _safe_str(docs_request_comment),
        "reviewed_at": datetime.now().isoformat(),

        # 프리카스: 0도 실제 값이므로 None과 구분
        "precas_112_count": _to_nullable_int(precas_112_count),
        "precas_risk_grade": _to_nullable_int(precas_risk_grade),
        "precas_patrol_count": _to_nullable_int(precas_patrol_count),

        # CPO 현장 환경조사
        "field_neighborhood_type": _normalize_field_value(field_neighborhood_type),
        "field_location_type": _normalize_field_value(field_location_type),
        "field_lighting": _normalize_field_value(field_lighting),
        "field_police_distance": _normalize_field_value(field_police_distance),
        "field_vulnerable_facilities": _normalize_field_value(field_vulnerable_facilities),
        "field_public_cctv": _normalize_field_value(field_public_cctv),
        "field_foot_traffic": _normalize_field_value(field_foot_traffic),
        "field_building_condition": _normalize_field_value(field_building_condition),

        # CPO 재량
        "cpo_discretionary_score": _to_nullable_float(cpo_discretionary_score) or 0,
        "cpo_discretionary_reason": _safe_str(cpo_discretionary_reason),
    }

    supabase.table("cpo_reviews").insert(payload).execute()
    supabase.table("applications").update({"status": review_result}).eq("id", application_id).execute()


def _update_application(
    supabase,
    application_id: Any,
    station_map: Dict[str, Any],
    station_options: List[str],
    payload: Dict[str, Any],
):
    if not application_id:
        raise Exception("application_id가 없습니다.")

    station_label = _safe_str(payload.pop("station_label", ""))
    address_road = _safe_str(payload.get("address_road"))
    inferred_station_label = _infer_station_label_from_address(address_road, station_options)
    final_station_label = inferred_station_label or station_label

    if final_station_label:
        station_id = station_map.get(final_station_label)
        if not station_id:
            raise Exception(f"관할 경찰서 '{final_station_label}'의 station_id를 찾지 못했습니다.")
        payload["station_id"] = station_id
    else:
        payload["station_id"] = None

    supabase.table("applications").update(payload).eq("id", application_id).execute()
    return final_station_label


def _delete_application(supabase, application_id: Any):
    if not application_id:
        raise Exception("application_id가 없습니다.")
    supabase.table("cpo_reviews").delete().eq("application_id", application_id).execute()
    supabase.table("applications").delete().eq("id", application_id).execute()


def _render_detail_summary_cards(row: Dict[str, Any]):
    bd = _score_bd(row)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재 상태", _status_label(row.get("current_status")) or "-")
    c1.markdown(f'<div class="cpo-status-current-row">{_status_badge_html(row.get("current_status"))}</div>', unsafe_allow_html=True)
    c2.metric("프리카스", f"{bd.get('precas_total', 0)}점")
    c3.metric("환경조사+설문", f"{round(bd.get('field_total', 0) + bd.get('survey_total', 0), 1)}점")
    c4.metric("총점", f"{bd.get('total', 0)}점")


def _edit_widget_key(prefix: str, field_name: str) -> str:
    return f"{prefix}{field_name}__widget"


def _sync_edit_state_to_widgets(prefix: str):
    sync_fields = ["address_query", "resolved_address", "station_label", "latitude", "longitude", "selected_search_idx"]
    for field_name in sync_fields:
        canonical_key = f"{prefix}{field_name}"
        widget_key = _edit_widget_key(prefix, field_name)
        if field_name in ["latitude", "longitude"]:
            st.session_state[widget_key] = _safe_float(st.session_state.get(canonical_key), 0.0)
        elif field_name == "selected_search_idx":
            st.session_state[widget_key] = _safe_int(st.session_state.get(canonical_key), 0)
        else:
            st.session_state[widget_key] = _safe_str(st.session_state.get(canonical_key))


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
        f"{prefix}pending_address_apply": None,
        f"{prefix}sync_widgets": False,
    }

    bound_id = st.session_state.get("edit_state_bound_application_id")
    needs_widget_sync = False

    if bound_id != application_id:
        for key, value in defaults.items():
            st.session_state[key] = value
        st.session_state["edit_state_bound_application_id"] = application_id
        needs_widget_sync = True
    else:
        for key, value in defaults.items():
            if key not in st.session_state:
                st.session_state[key] = value

    pending_apply = st.session_state.pop(f"{prefix}pending_address_apply", None)
    if isinstance(pending_apply, dict):
        if "search_message" in pending_apply:
            st.session_state[f"{prefix}search_message"] = pending_apply.get("search_message") or ""
        if "selected_search_idx" in pending_apply:
            st.session_state[f"{prefix}selected_search_idx"] = _safe_int(pending_apply.get("selected_search_idx"), 0)
        if "address_query" in pending_apply:
            st.session_state[f"{prefix}address_query"] = _safe_str(pending_apply.get("address_query"))
        if "resolved_address" in pending_apply:
            st.session_state[f"{prefix}resolved_address"] = _safe_str(pending_apply.get("resolved_address"))
        if "latitude" in pending_apply:
            st.session_state[f"{prefix}latitude"] = _safe_float(pending_apply.get("latitude"), 0.0)
        if "longitude" in pending_apply:
            st.session_state[f"{prefix}longitude"] = _safe_float(pending_apply.get("longitude"), 0.0)
        if "station_label" in pending_apply:
            st.session_state[f"{prefix}station_label"] = _safe_str(pending_apply.get("station_label"))
        needs_widget_sync = True

    if st.session_state.pop(f"{prefix}sync_widgets", False):
        needs_widget_sync = True

    if needs_widget_sync:
        _sync_edit_state_to_widgets(prefix)
    else:
        for field_name in ["address_query", "resolved_address", "station_label", "latitude", "longitude", "selected_search_idx"]:
            widget_key = _edit_widget_key(prefix, field_name)
            canonical_key = f"{prefix}{field_name}"
            if widget_key not in st.session_state:
                if field_name in ["latitude", "longitude"]:
                    st.session_state[widget_key] = _safe_float(st.session_state.get(canonical_key), 0.0)
                elif field_name == "selected_search_idx":
                    st.session_state[widget_key] = _safe_int(st.session_state.get(canonical_key), 0)
                else:
                    st.session_state[widget_key] = _safe_str(st.session_state.get(canonical_key))


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

    address_query_widget_key = _edit_widget_key(prefix, "address_query")
    resolved_address_widget_key = _edit_widget_key(prefix, "resolved_address")
    station_label_widget_key = _edit_widget_key(prefix, "station_label")
    latitude_widget_key = _edit_widget_key(prefix, "latitude")
    longitude_widget_key = _edit_widget_key(prefix, "longitude")
    selected_search_idx_widget_key = _edit_widget_key(prefix, "selected_search_idx")

    st.markdown(
        """
        <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:12px 16px;margin:16px 0 8px;">
          <span style="font-size:15px;font-weight:800;color:#c2410c;">✏️ 접수 정보 수정 · 삭제</span>
          <span style="font-size:12px;color:#92400e;margin-left:10px;">주소 검색 후 반영 → 저장 버튼을 누르면 실제 DB에 반영됩니다.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown("##### 점포 위치")
        st.caption("설문지처럼 주소를 검색한 뒤 결과를 선택하면 선택된 주소와 좌표가 자동 반영됩니다. 저장하면 지도 위치도 함께 바뀝니다.")

        c_addr1, c_addr2 = st.columns([5, 1])
        with c_addr1:
            st.text_input(
                "주소 입력",
                key=address_query_widget_key,
                placeholder="예: 전라남도 목포시 ○○로 123",
            )
        with c_addr2:
            search_clicked = st.button("주소 검색", key=f"{prefix}search_btn", use_container_width=True)

        if search_clicked:
            try:
                query = _safe_str(st.session_state.get(address_query_widget_key))
                st.session_state[f"{prefix}address_query"] = query
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
                st.session_state[f"{prefix}sync_widgets"] = True
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
            current_search_idx = min(
                _safe_int(st.session_state.get(selected_search_idx_widget_key), 0),
                len(search_results) - 1,
            )
            st.radio(
                "검색 결과",
                list(range(len(search_results))),
                index=current_search_idx,
                format_func=lambda i: (
                    f"{_safe_str(search_results[i].get('roadAddr'))} "
                    f"(지번: {_safe_str(search_results[i].get('jibunAddr')) or '-'})"
                ),
                key=selected_search_idx_widget_key,
            )

            if st.button("선택한 주소 반영", key=f"{prefix}apply_selected_address_btn", use_container_width=True):
                try:
                    selected_idx = _safe_int(st.session_state.get(selected_search_idx_widget_key), 0)
                    selected = search_results[selected_idx]
                    chosen_address, lat, lon = _resolve_candidate_to_address_and_coord(selected)
                    inferred_station_label = _infer_station_label_from_address(chosen_address, station_label_options)
                    st.session_state[f"{prefix}pending_address_apply"] = {
                        "search_message": "선택한 주소를 반영했습니다. 저장하면 지도 위치도 함께 변경됩니다.",
                        "selected_search_idx": selected_idx,
                        "address_query": chosen_address,
                        "resolved_address": chosen_address,
                        "latitude": float(lat),
                        "longitude": float(lon),
                        "station_label": inferred_station_label,
                    }
                    st.rerun()
                except Exception as exc:
                    st.session_state[f"{prefix}search_message"] = f"주소 반영 실패: {exc}"
                    st.rerun()

        st.text_input(
            "선택된 주소",
            key=resolved_address_widget_key,
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
        current_station_widget_value = _safe_str(st.session_state.get(station_label_widget_key))
        st.selectbox(
            "관할 경찰서",
            station_label_options,
            index=station_label_options.index(current_station_widget_value) if current_station_widget_value in station_label_options else 0,
            key=station_label_widget_key,
        )
        st.number_input("위도", format="%.6f", key=latitude_widget_key)
        st.number_input("경도", format="%.6f", key=longitude_widget_key)
        st.checkbox("점포 내 CCTV 있음", key=f"{prefix}has_cctv")
        st.checkbox("비상벨 설치됨", key=f"{prefix}has_emergency_bell")
        st.checkbox("사설경비 이용 중", key=f"{prefix}uses_security_company")
        st.text_input("기타 방범시설", key=f"{prefix}other_security")

    b1, b2 = st.columns(2)

    with b1:
        save_clicked = st.button("상세정보 수정 저장", key=f"{prefix}save_btn", use_container_width=True)

    with b2:
        delete_clicked = st.button("접수건 바로 삭제", key=f"delete_application_btn_{application_id}", use_container_width=True)

    if save_clicked:
        try:
            final_address = _safe_str(st.session_state.get(resolved_address_widget_key)) or _safe_str(st.session_state.get(address_query_widget_key))
            lat_to_save = _safe_float(st.session_state.get(latitude_widget_key), 0.0)
            lon_to_save = _safe_float(st.session_state.get(longitude_widget_key), 0.0)

            if final_address and (not lat_to_save or not lon_to_save):
                lat, lon, official = _coord_from_vworld(final_address)
                if lat is not None and lon is not None:
                    lat_to_save = lat
                    lon_to_save = lon
                    final_address = official or final_address

            inferred_station_label = _infer_station_label_from_address(final_address, station_label_options)
            manual_station_label = _safe_str(st.session_state.get(station_label_widget_key))
            final_station_label = inferred_station_label or manual_station_label

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
                "latitude": lat_to_save,
                "longitude": lon_to_save,
                "has_cctv": bool(st.session_state.get(f"{prefix}has_cctv")),
                "has_emergency_bell": bool(st.session_state.get(f"{prefix}has_emergency_bell")),
                "uses_security_company": bool(st.session_state.get(f"{prefix}uses_security_company")),
                "other_security": _safe_str(st.session_state.get(f"{prefix}other_security")) or None,
                "station_label": final_station_label,
            }
            final_station_label = _update_application(
                supabase=supabase,
                application_id=application_id,
                station_map=station_map,
                station_options=station_label_options,
                payload=update_payload,
            )
            st.success(f"상세정보가 수정되었습니다. 관할 경찰서는 '{final_station_label or '-'}'로 반영되었습니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"상세정보 수정 실패: {exc}")

    if delete_clicked:
        try:
            _delete_application(supabase, application_id)
            st.session_state.pop("selected_application_id", None)
            st.session_state.pop("selected_application_selectbox", None)
            checked_ids = st.session_state.get("list_checked_application_ids", [])
            st.session_state["list_checked_application_ids"] = [x for x in checked_ids if x != application_id]
            st.success("접수건이 삭제되었습니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"삭제 실패: {exc}")


def _fetch_review_history(supabase, application_id: Any) -> List[Dict[str, Any]]:
    if not application_id:
        return []

    try:
        resp = (
            supabase.table("cpo_reviews")
            .select(
                "reviewed_at, review_result, cpo_risk_label, cpo_risk_score, is_excluded, "
                "exclude_reason, review_comment, docs_request_comment, reviewer_id"
            )
            .eq("application_id", application_id)
            .order("reviewed_at", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        st.warning(f"검토 이력 조회 실패: {exc}")
        return []


def _render_review_history(supabase, application_id: Any):
    st.markdown("#### 검토 이력")
    history_rows = _fetch_review_history(supabase, application_id)
    if not history_rows:
        st.info("저장된 검토 이력이 없습니다.")
        return

    history_data = []
    for idx, item in enumerate(history_rows, start=1):
        history_data.append(
            {
                "번호": idx,
                "검토일시": _format_submitted_text(item.get("reviewed_at")),
                "검토상태": _status_display_text(item.get("review_result")),
                "CPO위험도": _safe_str(item.get("cpo_risk_label")) or "-",
                "제외여부": "예" if bool(item.get("is_excluded")) else "아니오",
                "제외사유": _safe_str(item.get("exclude_reason")) or "-",
                "추가서류요청": _safe_str(item.get("docs_request_comment")) or "-",
                "검토메모": _safe_str(item.get("review_comment")) or "-",
                "검토자ID": _safe_str(item.get("reviewer_id")) or "-",
            }
        )

    st.dataframe(pd.DataFrame(history_data), use_container_width=True, hide_index=True)


def _render_semas_reference_box():
    st.markdown(
        """
        <div class="cpo-inline-guide">
            🔎 <strong>정책자금 지원 제외업종 참고</strong>
            · <a href="https://ols.semas.or.kr/ols/pfa/SPFA207P/page.do" target="_blank">SEMAS 제외업종 바로가기</a>
            <span style="margin-left:8px;">제외 여부가 애매하면 저장 전에 바로 확인하세요.</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _validate_review_inputs(
    review_status: str,
    exclude_flag: bool,
    exclude_reason: str,
    docs_request_comment: str,
    precas_112_count: Any,
    precas_risk_grade: Any,
    precas_patrol_count: Any,
    cpo_discretionary_score: Any,
    cpo_discretionary_reason: str,
):
    if review_status == "추가서류요청" and not _safe_str(docs_request_comment):
        raise Exception("추가서류요청 상태로 저장하려면 요청 내용을 입력해주세요.")

    if (review_status == "제외" or exclude_flag) and not _safe_str(exclude_reason):
        raise Exception("제외로 저장하려면 제외 사유를 입력해주세요.")

    precas_values = [
        _safe_str(precas_112_count),
        _safe_str(precas_risk_grade),
        _safe_str(precas_patrol_count),
    ]
    entered_count = sum(1 for x in precas_values if x != "")

    if 0 < entered_count < 3:
        raise Exception("프리카스 점수는 112신고건수, 위험도등급, 탄력순찰수를 모두 입력해야 산정됩니다.")

    if _safe_str(precas_risk_grade):
        risk_grade = _safe_int(precas_risk_grade, 0)
        if risk_grade < 1 or risk_grade > 9:
            raise Exception("프리카스 위험도 등급은 1~9 사이로 입력해주세요.")

    disc_score = _safe_float(cpo_discretionary_score, 0.0)

    if disc_score < 0 or disc_score > 10:
        raise Exception("CPO 재량점수는 0~10점 사이로 입력해주세요.")

    if disc_score > 5 and not _safe_str(cpo_discretionary_reason):
        raise Exception("CPO 재량점수가 5점을 초과하면 사유를 입력해야 합니다.")

    if disc_score >= 8 and len(_safe_str(cpo_discretionary_reason)) < 10:
        raise Exception("CPO 재량점수가 8점 이상이면 구체 사유를 10자 이상 입력해주세요.")


def _render_detail(
    row: Dict[str, Any],
    supabase,
    user_id: str,
    station_id: Any,
    station_map: Dict[str, Any],
    station_options: List[str],
):
    # ── 상세 헤더 ──
    biz_name = _safe_str(row.get("business_name")) or "미입력"
    station_name = _safe_str(row.get("station_label")) or "-"
    bd_header = _score_bd(row)
    st.markdown(
        f"""
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:14px;padding:16px 20px;margin-bottom:14px;">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;">
            <div>
              <div style="font-size:20px;font-weight:800;color:#0f172a;">{biz_name}</div>
              <div style="font-size:13px;color:#64748b;margin-top:3px;">관할: {station_name} &nbsp;·&nbsp; 접수: {_format_submitted_text(row.get("submitted_at"))}</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              {_status_badge_html(row.get("current_status"))}
              <span style="font-size:18px;font-weight:800;color:#1e3a8a;">{bd_header.get("total", 0)}점</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
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
    bd = _score_bd(row)

    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("프리카스", f"{bd.get('precas_total', 0)} / 40점")
    a2.metric("환경조사", f"{bd.get('field_total', 0)} / 20점")
    a3.metric("점포환경설문", f"{bd.get('survey_env', 0)} / 20점")
    a4.metric("체감안전도", f"{bd.get('felt_safety', 0)} / 10점")
    a5.metric("총점", f"{bd.get('total', 0)} / 100점")

    st.caption(
        f"프리카스 상세: 112 {bd.get('precas_112', 0)}점, "
        f"위험등급 {bd.get('precas_risk', 0)}점, "
        f"탄력순찰 {bd.get('precas_patrol', 0)}점 / "
        f"CPO 재량 {bd.get('discretionary', 0)}점"
    )


    _render_application_edit_section(
        row=row,
        supabase=supabase,
        station_map=station_map,
        station_options=station_options,
    )

    _render_review_history(supabase, row.get("application_id"))

    st.markdown("#### CPO 검토 입력")
    st.markdown(f'<div class="cpo-status-current-row">저장 전 현재 상태 {_status_badge_html(row.get("current_status"))}</div>', unsafe_allow_html=True)
    st.caption("검토 결과를 저장하면 cpo_reviews에 이력이 쌓이고, applications의 현재 상태도 함께 변경됩니다.")

    with st.form(f"review_form_{row.get('application_id')}"):
        review_status_default = _status_label(row.get("current_status"))
        if review_status_default not in REVIEW_STATUS_OPTIONS:
            review_status_default = "검토완료"

        st.markdown("##### 1. 프리카스 격자 데이터 입력")
        st.caption("프리카스 100m 격자 기준 조회값을 입력합니다. 3개 값을 모두 입력한 경우에만 프리카스 40점이 산정됩니다.")

        p1, p2, p3 = st.columns(3)
        with p1:
            precas_112_count = st.text_input(
                "112신고 건수",
                value="" if row.get("precas_112_count") is None else str(row.get("precas_112_count")),
                placeholder="예: 0, 3, 12",
            )
        with p2:
            precas_risk_grade = st.text_input(
                "위험도 등급(1~9)",
                value="" if row.get("precas_risk_grade") is None else str(row.get("precas_risk_grade")),
                placeholder="1=최위험, 9=낮음",
            )
        with p3:
            precas_patrol_count = st.text_input(
                "탄력순찰 수",
                value="" if row.get("precas_patrol_count") is None else str(row.get("precas_patrol_count")),
                placeholder="예: 0, 1, 5",
            )

        st.markdown("##### 2. CPO 현장 환경조사 체크리스트")

        f1, f2 = st.columns(2)

        with f1:
            field_neighborhood_type = st.selectbox(
                "주변 환경 유형",
                FIELD_OPTIONS["field_neighborhood_type"],
                index=FIELD_OPTIONS["field_neighborhood_type"].index(row.get("field_neighborhood_type"))
                if row.get("field_neighborhood_type") in FIELD_OPTIONS["field_neighborhood_type"] else 0,
            )
            field_location_type = st.selectbox(
                "위치 유형",
                FIELD_OPTIONS["field_location_type"],
                index=FIELD_OPTIONS["field_location_type"].index(row.get("field_location_type"))
                if row.get("field_location_type") in FIELD_OPTIONS["field_location_type"] else 0,
            )
            field_lighting = st.selectbox(
                "야간 가로등·조명",
                FIELD_OPTIONS["field_lighting"],
                index=FIELD_OPTIONS["field_lighting"].index(row.get("field_lighting"))
                if row.get("field_lighting") in FIELD_OPTIONS["field_lighting"] else 0,
            )
            field_police_distance = st.selectbox(
                "파출소·지구대 거리",
                FIELD_OPTIONS["field_police_distance"],
                index=FIELD_OPTIONS["field_police_distance"].index(row.get("field_police_distance"))
                if row.get("field_police_distance") in FIELD_OPTIONS["field_police_distance"] else 0,
            )

        with f2:
            field_vulnerable_facilities = st.selectbox(
                "주변 취약시설",
                FIELD_OPTIONS["field_vulnerable_facilities"],
                index=FIELD_OPTIONS["field_vulnerable_facilities"].index(row.get("field_vulnerable_facilities"))
                if row.get("field_vulnerable_facilities") in FIELD_OPTIONS["field_vulnerable_facilities"] else 0,
            )
            field_public_cctv = st.selectbox(
                "공공 CCTV 현황",
                FIELD_OPTIONS["field_public_cctv"],
                index=FIELD_OPTIONS["field_public_cctv"].index(row.get("field_public_cctv"))
                if row.get("field_public_cctv") in FIELD_OPTIONS["field_public_cctv"] else 0,
            )
            field_foot_traffic = st.selectbox(
                "심야 유동인구",
                FIELD_OPTIONS["field_foot_traffic"],
                index=FIELD_OPTIONS["field_foot_traffic"].index(row.get("field_foot_traffic"))
                if row.get("field_foot_traffic") in FIELD_OPTIONS["field_foot_traffic"] else 0,
            )
            field_building_condition = st.selectbox(
                "건물 노후·고립도",
                FIELD_OPTIONS["field_building_condition"],
                index=FIELD_OPTIONS["field_building_condition"].index(row.get("field_building_condition"))
                if row.get("field_building_condition") in FIELD_OPTIONS["field_building_condition"] else 0,
            )

        st.markdown("##### 3. CPO 재량점수")
        d1, d2 = st.columns([1, 3])
        with d1:
            cpo_discretionary_score = st.number_input(
                "재량점수(0~10)",
                min_value=0.0,
                max_value=10.0,
                step=0.5,
                value=float(_safe_float(row.get("cpo_discretionary_score"), 0.0)),
            )
        with d2:
            cpo_discretionary_reason = st.text_input(
                "재량점수 사유",
                value=_safe_str(row.get("cpo_discretionary_reason")),
                placeholder="예: 인근 여성 1인 점포 밀집, 최근 반복 신고, 현장 체감 위험 높음 등",
            )

        st.markdown("##### 4. 최종 검토 의견 및 상태")
        r1, r2 = st.columns(2)
        with r1:
            review_status = st.selectbox(
                "검토 상태",
                REVIEW_STATUS_OPTIONS,
                index=REVIEW_STATUS_OPTIONS.index(review_status_default),
            )
        with r2:
            exclude_flag = st.checkbox(
                "우선순위 제외 대상",
                value=bool(row.get("is_excluded")) or review_status_default == "제외",
            )

        exclude_reason = st.text_input("제외 사유", value=_safe_str(row.get("exclude_reason")))
        review_comment = st.text_area("최종 검토 의견", value=_safe_str(row.get("review_comment")), height=100)
        docs_request_comment = st.text_area(
            "추가서류 요청 내용",
            value=_safe_str(row.get("docs_request_comment")),
            height=80,
            placeholder="예: 사업자등록증, 최근 매출현황 증빙자료 제출 요청",
        )

        submitted = st.form_submit_button("검토 저장", use_container_width=True)

        if submitted:
            try:
                _validate_review_inputs(
                    review_status=review_status,
                    exclude_flag=exclude_flag,
                    exclude_reason=exclude_reason,
                    docs_request_comment=docs_request_comment,
                    precas_112_count=precas_112_count,
                    precas_risk_grade=precas_risk_grade,
                    precas_patrol_count=precas_patrol_count,
                    cpo_discretionary_score=cpo_discretionary_score,
                    cpo_discretionary_reason=cpo_discretionary_reason,
                )

                _save_review(
                    supabase=supabase,
                    row=row,
                    reviewer_id=user_id,
                    reviewer_station_id=station_id,
                    review_status_label=review_status,
                    exclude_flag=exclude_flag,
                    exclude_reason=exclude_reason,
                    review_comment=review_comment,
                    docs_request_comment=docs_request_comment,
                    precas_112_count=precas_112_count,
                    precas_risk_grade=precas_risk_grade,
                    precas_patrol_count=precas_patrol_count,
                    field_neighborhood_type=field_neighborhood_type,
                    field_location_type=field_location_type,
                    field_lighting=field_lighting,
                    field_police_distance=field_police_distance,
                    field_vulnerable_facilities=field_vulnerable_facilities,
                    field_public_cctv=field_public_cctv,
                    field_foot_traffic=field_foot_traffic,
                    field_building_condition=field_building_condition,
                    cpo_discretionary_score=cpo_discretionary_score,
                    cpo_discretionary_reason=cpo_discretionary_reason,
                )

                st.success("검토 결과가 저장되었습니다.")
                st.rerun()

            except Exception as exc:
                st.error(f"저장 실패: {exc}")


def cpo_page(supabase, role: str, station: str, station_options: List[str]):
    _render_page_ui_css()
    selected_station = _safe_str(station)
    user_id = _safe_str(st.session_state.get("uid"))
    station_id = st.session_state.get("station_id")
    station_map = _fetch_station_map(supabase)
    station_label_options = _unique_station_options((station_options or []) + list(station_map.keys()))

    _inject_page_styles()

    raw_rows_for_header = _fetch_rows(supabase)
    total_for_header = len(raw_rows_for_header)
    st.markdown(
        f"""
        <div class="cpo-page-header">
          <div>
            <div class="cpo-page-header-title">🛡️ 전남경찰청 CPO 관리시스템</div>
            <div class="cpo-page-header-sub">소상공인 방범물품 지원 신청 · 심사 · 선정 통합 관리</div>
          </div>
          <div class="cpo-page-header-badge">총 접수 {total_for_header:,}건</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    raw_rows = raw_rows_for_header  # 헤더에서 이미 조회됨

    today = date.today()
    default_from = today - timedelta(days=30)

    if role == "admin":
        admin_station_options = ["전체"] + station_label_options
        admin_station_default = st.session_state.get("admin_station_filter") or "전체"
        if admin_station_default not in admin_station_options:
            admin_station_default = "전체"

        st.markdown(f'<div class="cpo-page-note">현재 선택 경찰서: {admin_station_default}</div>', unsafe_allow_html=True)

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
        st.markdown(f'<div class="cpo-page-note">관할 경찰서: {selected_station}</div>', unsafe_allow_html=True)

        f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
        with f1:
            status_filter = st.selectbox("상태", STATUS_FILTER_OPTIONS, index=0, key="status_filter")
        with f2:
            date_from = st.date_input("접수 시작일", value=default_from, key="date_from")
        with f3:
            date_to = st.date_input("접수 종료일", value=today, key="date_to")
        with f4:
            keyword = st.text_input("점포명 / 신청인 / 주소 검색", key="keyword")

    _render_section_heading("1", "접수 조회", "경찰서·상태·기간·검색어를 먼저 정한 뒤 아래 목록과 지도 대상을 확인합니다.")

    filtered_rows = _apply_filters(
        rows=raw_rows,
        role=role,
        selected_station=selected_station,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
    )

    st.session_state["current_filtered_rows_for_scoring"] = filtered_rows

    _render_top_metrics(filtered_rows)

    _render_section_heading("2", "우선 검토 대상 확인", "점수가 높은 점포를 먼저 살펴보고 제외업종 여부를 함께 확인합니다.")
    _render_score_guide()
    _render_semas_reference_box()
    _render_priority_table(filtered_rows)

    checked_ids_for_download = st.session_state.get("list_checked_application_ids", [])
    checked_export_rows = [row for row in filtered_rows if row.get("application_id") in checked_ids_for_download]
    checked_export_df = _build_export_df(checked_export_rows) if checked_export_rows else pd.DataFrame()
    all_export_df = _build_export_df(filtered_rows) if filtered_rows else pd.DataFrame()

    checked_filename = _build_download_filename(
        kind="checked",
        selected_station=selected_station if role != "admin" else st.session_state.get("admin_station_filter", "전체"),
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        row_count=len(checked_export_rows),
    )
    all_filename = _build_download_filename(
        kind="all",
        selected_station=selected_station if role != "admin" else st.session_state.get("admin_station_filter", "전체"),
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        row_count=len(filtered_rows),
    )

    _render_section_heading("3", "접수 목록 선택 · 다운로드", f"선택 {len(checked_export_rows)}건 / 조회 결과 {len(filtered_rows)}건")

    # ── 위원회 리포트 패널 ──────────────────────────────────
    precas_scores_for_report = compute_precas_scores_batch(filtered_rows)
    consideration_rows = [
        r for r in filtered_rows
        if _status_label(r.get("current_status")) in ("선정고려", "선정")
    ]
    checked_rows_for_report = [
        r for r in filtered_rows
        if r.get("application_id") in st.session_state.get("list_checked_application_ids", [])
    ]

    st.markdown(
        f"""
        <div class="cpo-report-panel">
          <div class="cpo-report-panel-icon">📋</div>
          <div class="cpo-report-panel-text">
            <div class="cpo-report-panel-title">위원회 심사 리포트 다운로드</div>
            <div class="cpo-report-panel-desc">선정고려·선정 {len(consideration_rows)}건 | 현재 체크된 항목 {len(checked_rows_for_report)}건 · Word(.docx) 개별 파일을 ZIP으로 묶어 제공합니다.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    report_col1, report_col2 = st.columns([3, 1])
    with report_col1:
        try:
            zip_bytes = generate_report_zip(consideration_rows, precas_scores_for_report) if consideration_rows else b""
        except Exception:
            zip_bytes = b""
        st.download_button(
            f"📥 선정고려·선정 전체 ZIP ({len(consideration_rows)}건)",
            data=zip_bytes,
            file_name=f"위원회_리포트_{date_from.strftime('%Y%m%d')}_{date_to.strftime('%Y%m%d')}.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not consideration_rows,
            key="download_report_zip",
        )
    with report_col2:
        try:
            checked_zip = generate_report_zip(checked_rows_for_report, precas_scores_for_report) if checked_rows_for_report else b""
        except Exception:
            checked_zip = b""
        st.download_button(
            f"선택 건 ZIP ({len(checked_rows_for_report)}건)",
            data=checked_zip,
            file_name=f"선택리포트_{len(checked_rows_for_report)}건.zip",
            mime="application/zip",
            use_container_width=True,
            disabled=not checked_rows_for_report,
            key="download_checked_report_zip",
        )

    st.divider()
    list_title_col, list_select_all_col, list_clear_col, list_btn1_col, list_btn2_col = st.columns([4, 1, 1, 1, 1])
    with list_title_col:
        st.markdown('<div class="cpo-page-note">조회된 접수를 선택하고 바로 다운로드할 수 있습니다.</div>', unsafe_allow_html=True)
    with list_select_all_col:
        st.write("")
        if st.button("조회 결과 전체 선택", use_container_width=True, key="bulk_check_visible_rows"):
            _bulk_check_rows(filtered_rows)
            st.rerun()
    with list_clear_col:
        st.write("")
        if st.button("선택 해제", use_container_width=True, key="bulk_clear_visible_rows"):
            _clear_checked_rows(filtered_rows)
            st.rerun()
    with list_btn1_col:
        st.write("")
        st.download_button(
            "선택 항목 다운로드",
            data=_df_to_excel_bytes(checked_export_df) if not checked_export_df.empty else b"",
            file_name=checked_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_checked_applications_top",
            disabled=checked_export_df.empty,
        )
    with list_btn2_col:
        st.write("")
        st.download_button(
            "전체 결과 다운로드",
            data=_df_to_excel_bytes(all_export_df) if not all_export_df.empty else b"",
            file_name=all_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="download_all_applications_top",
            disabled=all_export_df.empty,
        )

    _render_list_table(filtered_rows)

    _render_section_heading("4", "지도 확인 · 상세 검토 저장", "목록에서 선택한 점포의 위치를 확인하고 아래에서 검토 내용을 저장합니다.")
    st.markdown("### 선택 접수 지도")
    st.markdown('<div class="cpo-subtle-note">목록에서 체크한 항목이 아니라 현재 선택된 1건을 중심으로 지도와 상세정보가 바뀝니다.</div>', unsafe_allow_html=True)
    selected_row = _selected_row(filtered_rows)

    if filtered_rows:
        _sync_selected_row_by_selectbox(filtered_rows)
        selected_row = _selected_row(filtered_rows)

        n1, n2, n3 = st.columns([1, 1, 2.5])
        with n1:
            if st.button("이전 신청", use_container_width=True):
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
            if st.button("다음 신청", use_container_width=True):
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
            st.markdown('<div class="cpo-subtle-note">접수 목록에서 선택을 바꾸면 지도와 아래 상세정보가 함께 바뀝니다.</div>', unsafe_allow_html=True)

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
