import json
from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st

JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]
STATUS_OPTIONS = ["전체", "접수완료", "검토완료", "제외", "선정"]
CPO_RISK_OPTIONS = {
    "미입력": 0,
    "매우 높음": 50,
    "높음": 40,
    "보통": 25,
    "낮음": 10,
    "매우 낮음": 0,
}


# ==================================
# 공통 유틸
# ==================================
def _safe_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return int(v)
        return int(float(v))
    except Exception:
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _normalize_station(station: Optional[str]) -> str:
    s = _safe_str(station)
    if not s or s == "전체":
        return s
    if s.endswith("경찰서"):
        return s
    return f"{s}경찰서"


def _extract_meta(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("overall_comment")
    if not raw:
        return {
            "application_meta": {},
            "score_breakdown": {},
            "review_meta": {
                "status": "접수완료",
                "exclude": False,
                "exclude_reason": "",
                "memo": "",
                "reviewed_at": None,
                "reviewer_station": "",
                "cpo_risk_label": "",
                "cpo_risk_score": _safe_int(row.get("cpo_score"), 0),
            },
        }

    try:
        meta = json.loads(raw)
        if isinstance(meta, dict):
            meta.setdefault("application_meta", {})
            meta.setdefault("score_breakdown", {})
            meta.setdefault("review_meta", {})
            meta["review_meta"].setdefault("status", "접수완료")
            meta["review_meta"].setdefault("exclude", False)
            meta["review_meta"].setdefault("exclude_reason", "")
            meta["review_meta"].setdefault("memo", "")
            meta["review_meta"].setdefault("reviewed_at", None)
            meta["review_meta"].setdefault("reviewer_station", "")
            meta["review_meta"].setdefault("cpo_risk_label", "")
            meta["review_meta"].setdefault(
                "cpo_risk_score", _safe_int(row.get("cpo_score"), 0)
            )
            return meta
    except Exception:
        pass

    return {
        "application_meta": {"etc_note": _safe_str(raw)},
        "score_breakdown": {},
        "review_meta": {
            "status": "접수완료",
            "exclude": False,
            "exclude_reason": "",
            "memo": "",
            "reviewed_at": None,
            "reviewer_station": "",
            "cpo_risk_label": "",
            "cpo_risk_score": _safe_int(row.get("cpo_score"), 0),
        },
    }


def _felt_safety_score(row: Dict[str, Any], meta: Dict[str, Any]) -> int:
    score = _safe_int(meta.get("score_breakdown", {}).get("felt_safety_score"), -1)
    if score >= 0:
        return score
    raw = _safe_int(row.get("perceived_safety"), 0)
    return round(raw * 0.4) if raw > 40 else raw


def _security_vulnerability_score(row: Dict[str, Any], meta: Dict[str, Any]) -> int:
    score = _safe_int(
        meta.get("score_breakdown", {}).get("security_vulnerability_score"), -1
    )
    if score >= 0:
        return score
    cctv_score = 0 if bool(row.get("has_cctv")) else 5
    security_score = 0 if bool(row.get("uses_security_company")) else 5
    return cctv_score + security_score


def _review_meta_with_defaults(row: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    review = dict(meta.get("review_meta", {}) or {})
    review.setdefault("status", "접수완료")
    review.setdefault("exclude", False)
    review.setdefault("exclude_reason", "")
    review.setdefault("memo", "")
    review.setdefault("reviewed_at", None)
    review.setdefault("reviewer_station", "")
    review.setdefault("cpo_risk_label", "")
    review.setdefault("cpo_risk_score", _safe_int(row.get("cpo_score"), 0))
    return review


def _compute_total(row: Dict[str, Any], meta: Dict[str, Any]) -> Tuple[int, Dict[str, int], Dict[str, Any]]:
    felt = _felt_safety_score(row, meta)
    security = _security_vulnerability_score(row, meta)
    review = _review_meta_with_defaults(row, meta)
    cpo = _safe_int(review.get("cpo_risk_score"), _safe_int(row.get("cpo_score"), 0))
    total = felt + security + cpo
    breakdown = {
        "체감안전도": felt,
        "보안취약도": security,
        "CPO위험도": cpo,
        "총점": total,
    }
    return total, breakdown, review


def _submitted_at(row: Dict[str, Any], meta: Dict[str, Any]) -> datetime:
    submitted = _safe_str(meta.get("application_meta", {}).get("submitted_at")) or _safe_str(
        row.get("updated_at")
    )
    try:
        return datetime.fromisoformat(submitted.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except Exception:
        return datetime.min


def _row_for_export(
    row: Dict[str, Any],
    meta: Dict[str, Any],
    review: Dict[str, Any],
    breakdown: Dict[str, int],
) -> Dict[str, Any]:
    app = meta.get("application_meta", {}) or {}
    docs = app.get("documents", []) or []
    return {
        "접수일시": _safe_str(app.get("submitted_at")) or _safe_str(row.get("updated_at")),
        "점포명": _safe_str(row.get("shop_name")),
        "신청인": _safe_str(app.get("applicant_name")) or _safe_str(row.get("owner_name")),
        "연락처": _safe_str(app.get("contact")) or _safe_str(row.get("owner_phone")),
        "경찰서": _safe_str(row.get("officer_station") or row.get("station")),
        "업종": _safe_str(app.get("store_type") or row.get("employment_type")),
        "업종기타": _safe_str(app.get("store_type_other")),
        "연매출구간": _safe_str(app.get("sales_band")),
        "연매출": _safe_int(
            app.get("annual_sales_value"), _safe_int(row.get("annual_sales"), 0)
        ),
        "주소": _safe_str(row.get("address")),
        "위도": _safe_float(row.get("lat"), 0.0),
        "경도": _safe_float(row.get("lon") or row.get("lng"), 0.0),
        "점포내CCTV": _safe_str(app.get("cctv_inside"))
        or ("있음" if bool(row.get("has_cctv")) else "없음"),
        "사설경비": _safe_str(app.get("security_company"))
        or ("이용 중" if bool(row.get("uses_security_company")) else "이용하지 않음"),
        "체감안전도": breakdown["체감안전도"],
        "CPO위험도": breakdown["CPO위험도"],
        "보안취약도": breakdown["보안취약도"],
        "총점": breakdown["총점"],
        "상태": _safe_str(review.get("status")),
        "제외여부": "Y" if bool(review.get("exclude")) else "N",
        "제외사유": _safe_str(review.get("exclude_reason")),
        "첨부파일수": len(docs),
    }


def _df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="list")
    return output.getvalue()


# ==================================
# 데이터 조회
# ==================================
def _fetch_all_rows(supabase) -> List[Dict[str, Any]]:
    try:
        response = (
            supabase.table("shops")
            .select(
                "id, shop_name, address, station, officer_station, lat, lon, lng, annual_sales, employment_type, uses_security_company, has_cctv, owner_name, owner_phone, perceived_safety, cpo_score, overall_comment, updated_at"
            )
            .order("updated_at", desc=True)
            .limit(5000)
            .execute()
        )
        return response.data or []
    except Exception as exc:
        st.error(f"shops 조회 실패: {exc}")
        return []


def _build_records(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row in rows:
        meta = _extract_meta(row)
        total, breakdown, review = _compute_total(row, meta)
        records.append(
            {
                "row": row,
                "meta": meta,
                "review": review,
                "breakdown": breakdown,
                "submitted_at": _submitted_at(row, meta),
                "shop_name": _safe_str(row.get("shop_name")) or "(점포명 없음)",
                "station": _normalize_station(row.get("officer_station") or row.get("station")),
                "status": _safe_str(review.get("status")) or "접수완료",
                "exclude": bool(review.get("exclude")),
                "total_score": total,
            }
        )
    return records


def _apply_filters(
    records: List[Dict[str, Any]],
    role: str,
    station: str,
    station_filter: str,
    status_filter: str,
    date_from: date,
    date_to: date,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    my_station = _normalize_station(station)
    requested_station = _normalize_station(station_filter)

    for item in records:
        item_station = item["station"]
        if role != "admin" and my_station and item_station != my_station:
            continue
        if role == "admin" and requested_station and requested_station != "전체" and item_station != requested_station:
            continue

        submitted = item["submitted_at"]
        if submitted != datetime.min:
            if submitted.date() < date_from or submitted.date() > date_to:
                continue

        if status_filter != "전체" and item["status"] != status_filter:
            continue
        filtered.append(item)

    filtered.sort(key=lambda x: (x["exclude"], -x["total_score"], x["submitted_at"]), reverse=False)
    filtered.sort(key=lambda x: x["submitted_at"], reverse=True)
    filtered.sort(key=lambda x: (x["exclude"], -x["total_score"]))
    return filtered


# ==================================
# 저장
# ==================================
def _save_review(
    supabase,
    row: Dict[str, Any],
    meta: Dict[str, Any],
    cpo_risk_label: str,
    exclude_flag: bool,
    exclude_reason: str,
    memo: str,
    reviewer_station: str,
):
    review_meta = _review_meta_with_defaults(row, meta)
    review_meta["exclude"] = bool(exclude_flag)
    review_meta["exclude_reason"] = _safe_str(exclude_reason)
    review_meta["memo"] = _safe_str(memo)
    review_meta["reviewed_at"] = datetime.now().isoformat()
    review_meta["reviewer_station"] = _safe_str(reviewer_station)
    review_meta["cpo_risk_label"] = cpo_risk_label
    review_meta["cpo_risk_score"] = CPO_RISK_OPTIONS[cpo_risk_label]
    review_meta["status"] = "제외" if exclude_flag else "검토완료"

    meta = dict(meta)
    meta["review_meta"] = review_meta
    updated_at = datetime.now().isoformat()

    payload = {
        "cpo_score": CPO_RISK_OPTIONS[cpo_risk_label],
        "overall_comment": json.dumps(meta, ensure_ascii=False),
        "updated_at": updated_at,
    }

    supabase.table("shops").update(payload).eq("id", row["id"]).execute()


# ==================================
# UI 블록
# ==================================
def _render_score_guide():
    with st.expander("우선순위 산정 기준 보기", expanded=False):
        st.markdown(
            "**총점 = 체감안전도(40점) + CPO 위험도(50점) + 보안취약도(10점)**\n\n"
            "- 체감안전도: 신청 설문으로 자동 산출\n"
            "- CPO 위험도: 현장 판단에 따라 직접 입력\n"
            "- 보안취약도: 점포 내 CCTV 미설치 +5점, 사설경비 미이용 +5점\n\n"
            "※ 연매출 2억원 초과 및 제외업종은 CPO 검토 시 우선순위 제외로 처리할 수 있습니다."
        )


def _render_top_metrics(records: List[Dict[str, Any]]):
    total = len(records)
    completed = sum(1 for x in records if x["status"] == "검토완료")
    excluded = sum(1 for x in records if x["status"] == "제외")
    selected = sum(1 for x in records if x["status"] == "선정")
    pending = total - completed - excluded - selected

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("총 접수", f"{total}건")
    c2.metric("검토완료", f"{completed}건")
    c3.metric("제외", f"{excluded}건")
    c4.metric("선정", f"{selected}건")
    c5.metric("미검토", f"{pending}건")


def _render_download_buttons(filtered: List[Dict[str, Any]]):
    selected_ids = [
        shop_id
        for shop_id, checked in st.session_state.get("download_checks", {}).items()
        if checked
    ]
    selected_records = [item for item in filtered if item["row"]["id"] in selected_ids]

    col1, col2 = st.columns(2)
    with col1:
        if selected_records:
            df = pd.DataFrame(
                [
                    _row_for_export(
                        item["row"], item["meta"], item["review"], item["breakdown"]
                    )
                    for item in selected_records
                ]
            )
            st.download_button(
                "선택 점포 엑셀 다운로드",
                data=_df_to_excel_bytes(df),
                file_name=f"selected_shops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.button("선택 점포 엑셀 다운로드", disabled=True, use_container_width=True)

    with col2:
        if filtered:
            df_all = pd.DataFrame(
                [
                    _row_for_export(
                        item["row"], item["meta"], item["review"], item["breakdown"]
                    )
                    for item in filtered
                ]
            )
            st.download_button(
                "조회결과 전체 다운로드",
                data=_df_to_excel_bytes(df_all),
                file_name=f"filtered_shops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.button("조회결과 전체 다운로드", disabled=True, use_container_width=True)


def _render_store_map(lat: float, lon: float, key_suffix: str):
    import folium
    from streamlit_folium import st_folium

    fmap = folium.Map(location=[lat, lon], zoom_start=17, control_scale=True, prefer_canvas=True)
    folium.Marker([lat, lon], tooltip="점포 위치").add_to(fmap)
    st_folium(fmap, key=f"admin_map_{key_suffix}", height=280, width=None)


def _render_document_links(meta: Dict[str, Any]):
    docs = meta.get("application_meta", {}).get("documents", []) or []
    if not docs:
        st.caption("첨부서류 없음")
        return

    for doc in docs:
        name = _safe_str(doc.get("name")) or "첨부파일"
        status = _safe_str(doc.get("status")) or "unknown"
        url = _safe_str(doc.get("url"))
        if url:
            st.markdown(f"- [{name}]({url})")
        else:
            st.markdown(f"- {name} ({status})")


def _render_application_detail(item: Dict[str, Any], supabase, current_station: str):
    row = item["row"]
    meta = item["meta"]
    review = item["review"]
    app = meta.get("application_meta", {}) or {}
    breakdown = item["breakdown"]
    shop_id = row["id"]

    st.markdown("##### 기본정보")
    left, right = st.columns(2)
    with left:
        st.write(f"**점포명**: {item['shop_name']}")
        st.write(f"**신청인**: {_safe_str(app.get('applicant_name')) or _safe_str(row.get('owner_name'))}")
        st.write(f"**연락처**: {_safe_str(app.get('contact')) or _safe_str(row.get('owner_phone'))}")
        st.write(f"**업종**: {_safe_str(app.get('store_type') or row.get('employment_type'))}")
        if _safe_str(app.get("store_type_other")):
            st.write(f"**기타 업종**: {_safe_str(app.get('store_type_other'))}")
    with right:
        st.write(f"**연매출 구간**: {_safe_str(app.get('sales_band'))}")
        st.write(
            f"**연매출**: {_safe_int(app.get('annual_sales_value'), _safe_int(row.get('annual_sales'), 0)):,}원"
        )
        st.write(f"**접수일시**: {_safe_str(app.get('submitted_at')) or _safe_str(row.get('updated_at'))}")
        st.write(f"**현재 상태**: {item['status']}")

    st.markdown("##### 위치 정보")
    st.write(f"**주소**: {_safe_str(row.get('address'))}")
    lat = _safe_float(row.get("lat"), 0.0)
    lon = _safe_float(row.get("lon") or row.get("lng"), 0.0)
    st.write(f"**좌표**: {lat:.6f}, {lon:.6f}")
    if lat and lon:
        _render_store_map(lat, lon, str(shop_id))

    st.markdown("##### 설문 응답")
    st.write(f"- 범죄 불안 경험: {_safe_str(app.get('crime_anxiety'))}")
    st.write(f"- 야간 영업 여부: {_safe_str(app.get('night_business'))}")
    st.write(f"- 주변 환경: {_safe_str(app.get('surroundings'))}")
    st.write(f"- 혼자 근무: {_safe_str(app.get('solo_work'))}")
    st.write(
        f"- 점포 내 CCTV: {_safe_str(app.get('cctv_inside')) or ('있음' if bool(row.get('has_cctv')) else '없음')}"
    )
    st.write(
        f"- 사설경비 이용 여부: {_safe_str(app.get('security_company')) or ('이용 중' if bool(row.get('uses_security_company')) else '이용하지 않음')}"
    )
    if _safe_str(app.get("etc_note")):
        st.write(f"- 추가 의견: {_safe_str(app.get('etc_note'))}")

    st.markdown("##### 자동 산출 점수")
    st.write(f"- 체감안전도: {breakdown['체감안전도']}점")
    st.write(f"- 보안취약도: {breakdown['보안취약도']}점")
    st.write(f"- 현재 총점: {breakdown['총점']}점")

    st.markdown("##### 첨부서류")
    _render_document_links(meta)

    st.markdown("##### CPO 검토")
    form_key = f"review_form_{shop_id}"
    with st.form(form_key):
        current_label = _safe_str(review.get("cpo_risk_label")) or "미입력"
        risk_labels = list(CPO_RISK_OPTIONS.keys())
        risk_index = risk_labels.index(current_label) if current_label in risk_labels else 0

        cpo_risk_label = st.radio(
            "CPO 위험도",
            risk_labels,
            index=risk_index,
            horizontal=True,
            key=f"cpo_risk_label_{shop_id}",
        )
        exclude_flag = st.checkbox(
            "우선순위 제외 대상",
            value=bool(review.get("exclude")),
            key=f"exclude_flag_{shop_id}",
        )
        exclude_reason = st.text_input(
            "제외 사유",
            value=_safe_str(review.get("exclude_reason")),
            key=f"exclude_reason_{shop_id}",
        )
        memo = st.text_area(
            "검토 메모",
            value=_safe_str(review.get("memo")),
            height=100,
            key=f"memo_{shop_id}",
        )
        submitted = st.form_submit_button("입력 완료", use_container_width=True)

        if submitted:
            try:
                _save_review(
                    supabase=supabase,
                    row=row,
                    meta=meta,
                    cpo_risk_label=cpo_risk_label,
                    exclude_flag=exclude_flag,
                    exclude_reason=exclude_reason,
                    memo=memo,
                    reviewer_station=current_station,
                )
                st.success("검토 결과가 저장되었습니다.")
                st.rerun()
            except Exception as exc:
                st.error(f"저장 실패: {exc}")


def _render_priority_table(filtered: List[Dict[str, Any]]):
    rows = []
    for rank, item in enumerate([x for x in filtered if not x["exclude"]], start=1):
        rows.append(
            {
                "순위": rank,
                "점포명": item["shop_name"],
                "경찰서": item["station"],
                "체감안전도": item["breakdown"]["체감안전도"],
                "CPO위험도": item["breakdown"]["CPO위험도"],
                "보안취약도": item["breakdown"]["보안취약도"],
                "총점": item["breakdown"]["총점"],
                "상태": item["status"],
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("우선순위 현황에 표시할 점포가 없습니다.")


def _render_full_store_download(supabase, role: str, current_station: str, station_options: List[str]):
    st.markdown("### 소상공인 DB 전체 현황 다운로드")
    col1, col2 = st.columns([2, 2])
    with col1:
        if role == "admin":
            selected_station = st.selectbox(
                "시군(경찰서 기준)",
                ["전체"] + station_options,
                key="full_store_station",
            )
        else:
            selected_station = _normalize_station(current_station)
            st.text_input("관할 경찰서", value=selected_station, disabled=True)
    with col2:
        keyword = st.text_input("업종/점포명 검색(선택)", key="full_store_keyword")

    try:
        response = supabase.table("biz_stores").select("*").limit(5000).execute()
        data = response.data or []
    except Exception as exc:
        st.warning(f"biz_stores 조회 실패: {exc}")
        data = []

    if not data:
        st.info("전체 점포 DB 데이터가 없습니다.")
        return

    df = pd.DataFrame(data)

    station_col = None
    for col in ["station", "관할", "police_station"]:
        if col in df.columns:
            station_col = col
            break

    if selected_station and selected_station != "전체" and station_col:
        df = df[df[station_col].astype(str).str.contains(selected_station.replace("경찰서", ""), na=False)]

    if keyword.strip():
        mask = pd.Series([False] * len(df), index=df.index)
        for col in [
            "shop_name",
            "store_name",
            "bizesNm",
            "address",
            "rdnmAdr",
            "indsLclsNm",
            "indsMclsNm",
            "indsSclsNm",
        ]:
            if col in df.columns:
                mask = mask | df[col].astype(str).str.contains(keyword.strip(), case=False, na=False)
        df = df[mask]

    if df.empty:
        st.info("조회 조건에 해당하는 전체 점포 데이터가 없습니다.")
        return

    display_cols = [c for c in ["shop_name", "store_name", "bizesNm", "address", "rdnmAdr", "lat", "lon", "lng"] if c in df.columns]
    st.dataframe(df[display_cols].head(200), use_container_width=True, hide_index=True)

    st.download_button(
        "전체 점포 현황 엑셀 다운로드",
        data=_df_to_excel_bytes(df),
        file_name=f"all_stores_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


# ==================================
# 메인
# ==================================
def cpo_page(supabase, role: str, station: str, station_options: List[str]):
    current_station = _normalize_station(station)

    st.title("전남경찰청 CPO 관리시스템")
    raw_rows = _fetch_all_rows(supabase)
    all_records = _build_records(raw_rows)

    if role == "admin":
        selected_station = st.selectbox(
            "경찰서",
            ["전체"] + station_options,
            index=0,
            key="cpo_station_filter",
        )
    else:
        selected_station = current_station or station_options[0]
        st.text_input("관할 경찰서", value=selected_station, disabled=True)

    today = date.today()
    default_from = today - timedelta(days=30)

    col1, col2, col3 = st.columns(3)
    with col1:
        status_filter = st.selectbox("상태", STATUS_OPTIONS, index=0, key="status_filter")
    with col2:
        date_from = st.date_input("접수 시작일", value=default_from, key="date_from")
    with col3:
        date_to = st.date_input("접수 종료일", value=today, key="date_to")

    filtered = _apply_filters(
        records=all_records,
        role=role,
        station=current_station,
        station_filter=selected_station,
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
    )

    _render_top_metrics(filtered)
    _render_score_guide()
    _render_download_buttons(filtered)

    st.markdown("### 접수 점포 관리")
    if not filtered:
        st.info("조회 조건에 해당하는 접수 점포가 없습니다.")
    else:
        st.checkbox("전체 선택", key="select_all_download")
        if st.session_state.get("select_all_download"):
            st.session_state.setdefault("download_checks", {})
            for item in filtered:
                st.session_state["download_checks"][item["row"]["id"]] = True

        for item in filtered:
            row = item["row"]
            shop_id = row["id"]

            st.session_state.setdefault("download_checks", {})
            checked = st.checkbox(
                f"다운로드 선택 - {item['shop_name']} ({item['submitted_at'].strftime('%Y-%m-%d %H:%M') if item['submitted_at'] != datetime.min else '-'})",
                value=st.session_state["download_checks"].get(shop_id, False),
                key=f"download_check_{shop_id}",
            )
            st.session_state["download_checks"][shop_id] = checked

            header = (
                f"{item['shop_name']} | {item['station']} | 접수일시: "
                f"{item['submitted_at'].strftime('%Y-%m-%d %H:%M') if item['submitted_at'] != datetime.min else '-'} | "
                f"체감 {item['breakdown']['체감안전도']} | "
                f"CPO {item['breakdown']['CPO위험도']} | "
                f"총점 {item['breakdown']['총점']} | "
                f"{item['status']}"
            )
            with st.expander(header, expanded=False):
                _render_application_detail(item, supabase, current_station or selected_station)

    st.markdown("### 우선순위 현황")
    _render_priority_table(filtered)

    _render_full_store_download(
        supabase,
        role,
        current_station or selected_station,
        station_options,
    )