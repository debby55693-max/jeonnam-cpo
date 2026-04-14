from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


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
                "점포명": _safe_str(row.get("business_name")),
                "신청인": _safe_str(row.get("applicant_name")),
                "연락처": _safe_str(row.get("phone")),
                "경찰서": _safe_str(row.get("station_label")),
                "업종": _display_business_type(row),
                "주소": _full_address(row),
                "위도": _safe_float(row.get("latitude"), 0.0),
                "경도": _safe_float(row.get("longitude"), 0.0),
                "연매출구간": _safe_str(row.get("sales_band")),
                "연매출": _safe_int(row.get("annual_sales"), 0),
                "체감안전도": _safe_int(row.get("felt_safety_score"), 0),
                "CPO위험도": _safe_int(row.get("cpo_risk_score"), 0),
                "보안취약도": _safe_int(row.get("security_vulnerability_score"), 0),
                "총점": _safe_int(row.get("total_score"), 0),
                "상태": _status_label(row.get("current_status")),
                "점포내CCTV": "있음" if bool(row.get("has_cctv")) else "없음",
                "사설경비": "이용 중" if bool(row.get("uses_security_company")) else "이용하지 않음",
                "접수일시": _format_submitted_text(row.get("submitted_at")),
            }
        )
    return pd.DataFrame(data)


def _set_selected_application(row: Dict[str, Any]):
    st.session_state["selected_application_id"] = row.get("application_id")
    st.session_state["selected_lat"] = _safe_float(row.get("latitude"), 0.0)
    st.session_state["selected_lon"] = _safe_float(row.get("longitude"), 0.0)
    st.session_state["selected_business_name"] = _safe_str(row.get("business_name"))


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

    id_to_label = {item["application_id"]: item["label"] for item in options}

    selected_id = st.selectbox(
        "선택 점포",
        option_ids,
        index=option_ids.index(current_id),
        format_func=lambda x: id_to_label.get(x, str(x)),
        key="selected_application_selectbox",
    )
    st.session_state["selected_application_id"] = selected_id


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
        icon = "red" if selected_row and row.get("application_id") == selected_row.get("application_id") else "blue"

        folium.Marker(
            [lat, lon],
            tooltip=tooltip,
            popup=folium.Popup(popup_html, max_width=300),
            icon=folium.Icon(color=icon),
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
    with st.expander("우선순위 산정 기준 보기", expanded=False):
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


def _render_list_table(rows: List[Dict[str, Any]]):
    if rows:
        st.dataframe(_build_list_df(rows), use_container_width=True, hide_index=True)
    else:
        st.info("조회 결과가 없습니다.")


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

    review_result = _review_status_value(review_status_label, exclude_flag)
    payload = {
        "application_id": application_id,
        "reviewer_id": reviewer_id,
        "station_id": reviewer_station_id,
        "review_result": review_result,
        "cpo_risk_label": risk_label,
        "cpo_risk_score": CPO_RISK_OPTIONS.get(risk_label, 0),
        "is_excluded": bool(exclude_flag),
        "exclude_reason": _safe_str(exclude_reason),
        "review_comment": _safe_str(review_comment),
        "docs_request_comment": _safe_str(docs_request_comment),
        "reviewed_at": datetime.now().isoformat(),
    }

    supabase.table("cpo_reviews").insert(payload).execute()
    supabase.table("applications").update({"status": review_result}).eq("id", application_id).execute()


def _render_detail_summary_cards(row: Dict[str, Any]):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("현재 상태", _status_label(row.get("current_status")) or "-")
    c2.metric("체감안전도", f"{_safe_int(row.get('felt_safety_score'), 0)}점")
    c3.metric("CPO위험도", f"{_safe_int(row.get('cpo_risk_score'), 0)}점")
    c4.metric("총점", f"{_safe_int(row.get('total_score'), 0)}점")


def _render_detail(row: Dict[str, Any], supabase, user_id: str, station_id: Any):
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
    st.caption("상세정보 안 지도는 제거했습니다. 위치 확인은 상단 '접수 현황 지도'와 '📍 지도에서 보기' 버튼으로 진행합니다.")

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


def _render_priority_table(rows: List[Dict[str, Any]]):
    st.markdown("### 우선순위 현황")
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


def _move_selected_by_step(rows: List[Dict[str, Any]], step: int):
    if not rows:
        return
    ids = [row.get("application_id") for row in rows]
    current_id = st.session_state.get("selected_application_id")
    if current_id not in ids:
        st.session_state["selected_application_id"] = ids[0]
        return
    idx = ids.index(current_id)
    next_idx = max(0, min(len(ids) - 1, idx + step))
    st.session_state["selected_application_id"] = ids[next_idx]


def cpo_page(supabase, role: str, station: str, station_options: List[str]):
    selected_station = _safe_str(station)
    user_id = _safe_str(st.session_state.get("uid"))
    station_id = st.session_state.get("station_id")

    st.title("전남경찰청 CPO 관리시스템")

    raw_rows = _fetch_rows(supabase)

    today = date.today()
    default_from = today - timedelta(days=30)

    if role == "admin":
        st.caption(f"현재 선택 경찰서: {selected_station or '전체'}")
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

    st.markdown("### 접수 현황 지도")
    if filtered_rows:
        _sync_selected_row_by_selectbox(filtered_rows)

        n1, n2, n3 = st.columns([1, 1, 3])
        with n1:
            if st.button("이전 점포", use_container_width=True):
                _move_selected_by_step(filtered_rows, -1)
                st.rerun()
        with n2:
            if st.button("다음 점포", use_container_width=True):
                _move_selected_by_step(filtered_rows, 1)
                st.rerun()
        with n3:
            st.caption("선택 점포를 바꾸면 지도 중심과 아래 상세정보가 함께 바뀝니다.")

    selected_row = _selected_row(filtered_rows)
    _render_map(filtered_rows, selected_row)

    if selected_row:
        st.caption(
            f"현재 선택: {_safe_str(selected_row.get('business_name'))} / "
            f"{_safe_str(selected_row.get('station_label')) or '-'} / "
            f"위도 {_format_coord(selected_row.get('latitude'))} / "
            f"경도 {_format_coord(selected_row.get('longitude'))}"
        )

    st.markdown("### 접수 목록 현황")
    _render_list_table(filtered_rows)

    if filtered_rows:
        export_df = _build_export_df(filtered_rows)
        st.download_button(
            "조회결과 전체 다운로드",
            data=_df_to_excel_bytes(export_df),
            file_name=f"applications_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.markdown("### 접수 상세 / 지도 이동")
    if not filtered_rows or not selected_row:
        st.info("조회 결과가 없습니다.")
    else:
        b1, b2 = st.columns([1, 3])
        with b1:
            if st.button("📍 지도에서 보기", key=f"move_map_selected_{selected_row.get('application_id')}", use_container_width=True):
                _set_selected_application(selected_row)
                st.rerun()
        with b2:
            st.caption(
                f"주소: {_full_address(selected_row)} / 위도 {_format_coord(selected_row.get('latitude'))} / "
                f"경도 {_format_coord(selected_row.get('longitude'))}"
            )

        _render_detail(selected_row, supabase, user_id, station_id)

        with st.expander("다른 접수 건 빠르게 보기", expanded=False):
            for row in filtered_rows:
                submitted_text = _format_submitted_text(row.get("submitted_at"))
                header = (
                    f"{_safe_str(row.get('business_name'))} | {_display_business_type(row)} | {submitted_text} | "
                    f"총점 {_safe_int(row.get('total_score'), 0)} | {_status_label(row.get('current_status'))}"
                )
                with st.container(border=True):
                    c1, c2 = st.columns([4, 1])
                    with c1:
                        st.markdown(f"**{header}**")
                        st.caption(
                            f"신청인 {_safe_str(row.get('applicant_name')) or '-'} / "
                            f"경찰서 {_safe_str(row.get('station_label')) or '-'} / "
                            f"주소 {_full_address(row)}"
                        )
                    with c2:
                        if st.button("선택", key=f"quick_select_{row.get('application_id')}", use_container_width=True):
                            _set_selected_application(row)
                            st.rerun()

    _render_priority_table(filtered_rows)