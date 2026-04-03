import json
import time
import uuid
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import folium
import requests
import streamlit as st
from streamlit_folium import st_folium

JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]

STORE_TYPE_OPTIONS = [
    "음식점", "카페", "편의점", "미용업", "숙박업", "서비스업", "소매점", "기타"
]
SALES_BAND_OPTIONS = [
    "5천만원 이하",
    "5천만원 초과 ~ 1억원 이하",
    "1억원 초과 ~ 2억원 이하",
    "2억원 초과",
]
CRIME_ANXIETY_SCORES = {"전혀 없음": 0, "거의 없음": 3, "가끔 있음": 7, "자주 있음": 10}
NIGHT_BUSINESS_SCORES = {"해당 없음": 0, "가끔 있음": 5, "자주 있음": 10}
SURROUNDINGS_SCORES = {"밝고 유동인구 많음": 0, "보통": 5, "어둡고 인적 드묾": 10}
SOLO_WORK_SCORES = {"거의 없음": 0, "가끔 있음": 5, "자주 있음": 10}
CCTV_OPTIONS = ["없음", "1~2대", "3대 이상"]
SECURITY_OPTIONS = ["이용하지 않음", "이용 중"]
PHONE_RE = re.compile(r"^01[0-9]-?\d{3,4}-?\d{4}$")


# ==============================
# 공통 유틸
# ==============================
def _safe_str(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", _safe_str(value))
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return value.strip()


def _format_coord(value: Any) -> str:
    try:
        return f"{float(value):.6f}"
    except Exception:
        return ""


def _asset_path(filename: str) -> Optional[Path]:
    here = Path(__file__).resolve()
    root = here.parents[2]
    candidate = root / "assets" / filename
    return candidate if candidate.exists() else None


def _render_logo_header():
    logo_path = _asset_path("jeonnam_police_logo.png")
    if logo_path:
        st.image(str(logo_path), width=120)
    else:
        st.markdown("### 전남경찰청")


# ==============================
# 주소 검색 / 좌표 변환
# ==============================
def juso_search(keyword: str, page: int = 1, size: int = 10) -> List[dict]:
    confm_key = st.secrets.get("JUSO_CONFM_KEY", "").strip()
    if not confm_key:
        raise RuntimeError("JUSO_CONFM_KEY가 secrets에 없습니다.")

    url = "https://www.juso.go.kr/addrlink/addrLinkApi.do"
    params = {
        "confmKey": confm_key,
        "currentPage": page,
        "countPerPage": size,
        "keyword": keyword,
        "resultType": "json",
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data.get("results", {}).get("juso", []) or []


def _get_vworld_key() -> str:
    for key in ["VWORLD_KEY", "VWORLD_API_KEY", "VWorld_KEY", "vworld_key"]:
        value = st.secrets.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _clean_address_for_geocode(address: str) -> str:
    cleaned = re.sub(r"\(.*?\)", "", _safe_str(address))
    return re.sub(r"\s+", " ", cleaned).strip()


def vworld_geocode(address: str, addr_type: str = "road") -> Tuple[Optional[float], Optional[float]]:
    key = _get_vworld_key()
    if not key:
        raise RuntimeError("VWORLD_KEY(또는 동등 키)가 secrets에 없습니다.")

    addr = _clean_address_for_geocode(address)
    if not addr:
        return None, None

    url = "https://api.vworld.kr/req/address"
    params = {
        "service": "address",
        "request": "getcoord",
        "format": "json",
        "crs": "epsg:4326",
        "address": addr,
        "type": addr_type,
        "key": key,
    }
    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    resp = data.get("response", {})
    if resp.get("status") != "OK":
        return None, None

    point = resp.get("result", {}).get("point", {})
    lon = point.get("x")
    lat = point.get("y")
    if lon is None or lat is None:
        return None, None
    return float(lat), float(lon)


def _resolve_address_to_coords(road_address: str, jibun_address: str) -> Tuple[Optional[float], Optional[float]]:
    lat, lon = vworld_geocode(road_address, "road")
    if lat is not None and lon is not None:
        return lat, lon
    if jibun_address:
        return vworld_geocode(jibun_address, "parcel")
    return None, None


# ==============================
# 파일 업로드
# ==============================
def _guess_bucket_name() -> Optional[str]:
    bucket = _safe_str(st.secrets.get("SUPABASE_DOCS_BUCKET"))
    if bucket:
        return bucket
    for candidate in ["shop-documents", "shop_documents", "documents"]:
        return candidate
    return None


def _upload_single_file(supabase, uploaded_file, station: str) -> Dict[str, Any]:
    bucket_name = _guess_bucket_name()
    if not bucket_name:
        return {"name": uploaded_file.name, "status": "bucket_missing", "url": None, "path": None}

    ext = Path(uploaded_file.name).suffix.lower()
    object_path = f"public/{station}/{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex}{ext}"

    try:
        file_bytes = uploaded_file.getvalue()
        try:
            supabase.storage.from_(bucket_name).upload(
                object_path,
                file_bytes,
                {"content-type": uploaded_file.type or "application/octet-stream", "upsert": "true"},
            )
        except TypeError:
            supabase.storage.from_(bucket_name).upload(
                object_path,
                file_bytes,
                file_options={"content-type": uploaded_file.type or "application/octet-stream", "upsert": "true"},
            )

        public_url = None
        try:
            public_url = supabase.storage.from_(bucket_name).get_public_url(object_path)
        except Exception:
            public_url = None

        return {
            "name": uploaded_file.name,
            "status": "uploaded",
            "url": public_url,
            "path": object_path,
            "size": len(file_bytes),
        }
    except Exception as exc:
        return {
            "name": uploaded_file.name,
            "status": "upload_failed",
            "url": None,
            "path": None,
            "error": str(exc),
        }


# ==============================
# 점수 계산
# ==============================
def calculate_felt_safety_score(
    crime_anxiety: str,
    night_business: str,
    surroundings: str,
    solo_work: str,
) -> Tuple[int, Dict[str, int]]:
    breakdown = {
        "범죄불안": CRIME_ANXIETY_SCORES[crime_anxiety],
        "야간영업": NIGHT_BUSINESS_SCORES[night_business],
        "주변환경": SURROUNDINGS_SCORES[surroundings],
        "단독근무": SOLO_WORK_SCORES[solo_work],
    }
    return sum(breakdown.values()), breakdown


def calculate_security_vulnerability(cctv_inside: str, security_company: str) -> Tuple[int, Dict[str, int]]:
    cctv_score = 5 if cctv_inside == "없음" else 0
    security_score = 5 if security_company == "이용하지 않음" else 0
    breakdown = {"CCTV미설치": cctv_score, "사설경비미이용": security_score}
    return cctv_score + security_score, breakdown


# ==============================
# 지도
# ==============================
def _render_single_point_map(lat: float, lon: float):
    fmap = folium.Map(location=[lat, lon], zoom_start=17, control_scale=True, prefer_canvas=True)
    folium.Marker([lat, lon], tooltip="점포 위치").add_to(fmap)
    st_folium(fmap, height=360, width=None, key="survey_point_map")


def _render_pin_picker_map(key_prefix: str = "survey"):
    pin_lat = st.session_state.get("pin_lat")
    pin_lon = st.session_state.get("pin_lon")
    addr_lat = st.session_state.get("addr_lat")
    addr_lon = st.session_state.get("addr_lon")

    if pin_lat is not None and pin_lon is not None:
        center_lat, center_lon, zoom = float(pin_lat), float(pin_lon), 18
    elif addr_lat is not None and addr_lon is not None:
        center_lat, center_lon, zoom = float(addr_lat), float(addr_lon), 17
    else:
        center_lat, center_lon, zoom = 34.85, 126.85, 11

    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        control_scale=True,
        prefer_canvas=True,
        tiles="OpenStreetMap",
    )

    if pin_lat is not None and pin_lon is not None:
        folium.Marker([float(pin_lat), float(pin_lon)], tooltip="선택 위치").add_to(fmap)

    map_data = st_folium(
        fmap,
        key=f"{key_prefix}_pin_picker_map",
        height=420,
        returned_objects=["last_clicked"],
    )

    clicked = (map_data or {}).get("last_clicked")
    if clicked and clicked.get("lat") is not None and clicked.get("lng") is not None:
        new_lat = round(float(clicked["lat"]), 8)
        new_lon = round(float(clicked["lng"]), 8)
        old_lat = st.session_state.get("pin_lat")
        old_lon = st.session_state.get("pin_lon")

        if (
            old_lat is None or old_lon is None
            or abs(float(old_lat) - new_lat) > 1e-10
            or abs(float(old_lon) - new_lon) > 1e-10
        ):
            st.session_state["pin_lat"] = new_lat
            st.session_state["pin_lon"] = new_lon
            st.rerun()


# ==============================
# 저장용 메타
# ==============================
def _build_payload(
    police_station: str,
    store_name: str,
    applicant_name: str,
    contact: str,
    store_type: str,
    store_type_other: str,
    full_address: str,
    detail_address: str,
    lat: float,
    lon: float,
    sales_band: str,
    annual_sales_value: int,
    cctv_inside: str,
    security_company: str,
    crime_anxiety: str,
    night_business: str,
    surroundings: str,
    solo_work: str,
    etc_note: str,
    document_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    felt_score, felt_breakdown = calculate_felt_safety_score(
        crime_anxiety, night_business, surroundings, solo_work
    )
    security_score, security_breakdown = calculate_security_vulnerability(
        cctv_inside, security_company
    )
    submitted_at = datetime.now().isoformat()

    meta = {
        "schema": "shop_application_v2",
        "application_meta": {
            "applicant_name": applicant_name,
            "contact": contact,
            "police_station": police_station,
            "store_type": store_type,
            "store_type_other": store_type_other,
            "sales_band": sales_band,
            "annual_sales_value": annual_sales_value,
            "cctv_inside": cctv_inside,
            "security_company": security_company,
            "crime_anxiety": crime_anxiety,
            "night_business": night_business,
            "surroundings": surroundings,
            "solo_work": solo_work,
            "detail_address": detail_address,
            "etc_note": etc_note,
            "submitted_at": submitted_at,
            "documents": document_list,
        },
        "score_breakdown": {
            "felt_safety_score": felt_score,
            "felt_safety_detail": felt_breakdown,
            "security_vulnerability_score": security_score,
            "security_vulnerability_detail": security_breakdown,
            "total_before_cpo": felt_score + security_score,
        },
        "review_meta": {
            "status": "접수완료",
            "exclude": False,
            "exclude_reason": "",
            "memo": "",
            "reviewed_at": None,
            "reviewer_station": "",
            "cpo_risk_label": "",
            "cpo_risk_score": 0,
        },
    }

    return {
        "shop_name": store_name,
        "address": full_address,
        "station": police_station,
        "officer_station": police_station,
        "lat": float(lat),
        "lon": float(lon),
        "lng": float(lon),
        "annual_sales": int(annual_sales_value or 0),
        "employment_type": store_type if store_type != "기타" else (store_type_other or "기타"),
        "uses_security_company": security_company == "이용 중",
        "has_cctv": cctv_inside != "없음",
        "has_emergency_bell": False,
        "other_security": etc_note or None,
        "perceived_safety": int(felt_score),
        "owner_name": applicant_name or None,
        "owner_phone": contact or None,
        "overall_comment": json.dumps(meta, ensure_ascii=False),
        "updated_at": submitted_at,
    }


# ==============================
# 메인 화면
# ==============================
def field_public_page(supabase):
    st.session_state.setdefault("last_submit_ts", 0.0)
    st.session_state.setdefault("addr_candidates", [])
    st.session_state.setdefault("selected_address", "")
    st.session_state.setdefault("selected_jibun", "")
    st.session_state.setdefault("selected_zipno", "")
    st.session_state.setdefault("addr_lat", None)
    st.session_state.setdefault("addr_lon", None)
    st.session_state.setdefault("pin_lat", None)
    st.session_state.setdefault("pin_lon", None)

    _render_logo_header()
    st.markdown("## 소상공인 방범지원 신청")
    st.caption(
        "제출된 정보와 서류는 지원 대상 검토 및 현장 확인 용도로만 활용됩니다. "
        "서류가 미비한 경우 추가 제출을 요청할 수 있으며, 최종 선정 결과는 개별 연락드립니다."
    )
    st.info("문의사항은 해당 시·군 관할 경찰서 범죄예방계로 문의하여 주시기 바랍니다.")

    police_station = st.selectbox("관할 경찰서", JEONNAM_POLICE_STATIONS, key="police_station")

    st.markdown("### 1. 기본 정보")
    col1, col2 = st.columns(2)
    with col1:
        applicant_name = st.text_input("신청인 성명 *", key="applicant_name")
    with col2:
        contact = st.text_input(
            "연락처 *",
            placeholder="010-1234-5678",
            key="applicant_contact",
        )

    store_name = st.text_input("점포명 *", key="store_name")

    st.markdown("### 2. 업종")
    store_type = st.selectbox("업종 선택 *", STORE_TYPE_OPTIONS, key="store_type")
    store_type_other = ""
    if store_type == "기타":
        store_type_other = st.text_input("기타 업종 입력 *", key="store_type_other")

    st.markdown("### 3. 점포 위치")
    location_mode = st.radio(
        "위치 입력 방식",
        ["주소검색", "지도에서 위치 지정"],
        horizontal=True,
        key="location_mode",
    )

    full_address = ""
    detail_address = ""
    lat: Optional[float] = None
    lon: Optional[float] = None

    if location_mode == "주소검색":
        keyword = st.text_input(
            "주소 검색",
            placeholder="예) 전남 무안군 삼향읍 남악3로 71",
            key="addr_query",
        )
        if st.button("주소 검색", key="addr_search_btn"):
            if not keyword.strip():
                st.warning("주소 검색어를 입력해 주세요.")
            else:
                try:
                    st.session_state["addr_candidates"] = juso_search(keyword.strip(), page=1, size=10)
                except Exception as exc:
                    st.error(f"주소 검색 실패: {exc}")
                    st.session_state["addr_candidates"] = []

        candidates = st.session_state.get("addr_candidates", []) or []
        if candidates:
            labels = []
            for item in candidates:
                labels.append(
                    f"{item.get('roadAddr', '')} | 지번: {item.get('jibunAddr', '')} | 우편: {item.get('zipNo', '')}"
                )
            picked = st.selectbox("검색 결과 선택", labels, key="addr_pick")
            selected = candidates[labels.index(picked)]
            st.session_state["selected_address"] = _safe_str(selected.get("roadAddr"))
            st.session_state["selected_jibun"] = _safe_str(selected.get("jibunAddr"))
            st.session_state["selected_zipno"] = _safe_str(selected.get("zipNo"))

            try:
                found_lat, found_lon = _resolve_address_to_coords(
                    st.session_state["selected_address"],
                    st.session_state["selected_jibun"],
                )
                st.session_state["addr_lat"] = found_lat
                st.session_state["addr_lon"] = found_lon
            except Exception as exc:
                st.error(f"좌표 변환 실패: {exc}")
                st.session_state["addr_lat"] = None
                st.session_state["addr_lon"] = None

        selected_address = st.session_state.get("selected_address", "")
        detail_address = st.text_input("상세주소", key="detail_address")
        if selected_address:
            full_address = f"{selected_address} {detail_address}".strip()
            st.text_input("선택된 주소", value=selected_address, disabled=True)

        lat = st.session_state.get("addr_lat")
        lon = st.session_state.get("addr_lon")

        if lat is not None and lon is not None:
            st.caption(f"확인 좌표: {_format_coord(lat)} / {_format_coord(lon)}")
            _render_single_point_map(float(lat), float(lon))

    else:
        st.caption("지도를 클릭해 점포 위치를 지정하세요. 필요한 경우 위치 설명도 함께 적어 주세요.")
        manual_location_note = st.text_input(
            "위치 설명 *",
            placeholder="예) 남악 ○○상가 1층",
            key="manual_location_note",
        )
        _render_pin_picker_map("survey")
        lat = st.session_state.get("pin_lat")
        lon = st.session_state.get("pin_lon")
        detail_address = st.text_input("상세 설명(선택)", key="manual_detail_address")
        if manual_location_note:
            full_address = f"{manual_location_note} {detail_address}".strip()

        colm1, colm2 = st.columns(2)
        with colm1:
            st.text_input("위도", value=_format_coord(lat), disabled=True)
        with colm2:
            st.text_input("경도", value=_format_coord(lon), disabled=True)

    st.markdown("### 4. 연매출")
    sales_band = st.radio("연매출 구간 *", SALES_BAND_OPTIONS, horizontal=False, key="sales_band")
    annual_sales_value = st.number_input(
        "연매출 기재(원) *",
        min_value=0,
        step=1000000,
        key="annual_sales_value",
    )

    st.markdown("### 5. 보안시설 현황")
    cctv_inside = st.radio(
        "점포 내 CCTV 설치 여부 *",
        CCTV_OPTIONS,
        horizontal=True,
        key="cctv_inside",
    )
    security_company = st.radio(
        "사설경비업체 이용 여부 *",
        SECURITY_OPTIONS,
        horizontal=True,
        key="security_company",
    )

    st.markdown("### 6. 점포 환경 설문")
    crime_anxiety = st.radio(
        "최근 점포 운영 중 범죄피해 또는 위협을 느낀 적이 있습니까? *",
        list(CRIME_ANXIETY_SCORES.keys()),
        horizontal=True,
        key="crime_anxiety",
    )
    night_business = st.radio(
        "야간 시간대(22시 이후) 영업 여부 *",
        list(NIGHT_BUSINESS_SCORES.keys()),
        horizontal=True,
        key="night_business",
    )
    surroundings = st.radio(
        "점포 주변 환경 *",
        list(SURROUNDINGS_SCORES.keys()),
        horizontal=True,
        key="surroundings",
    )
    solo_work = st.radio(
        "혼자 근무하는 시간 *",
        list(SOLO_WORK_SCORES.keys()),
        horizontal=True,
        key="solo_work",
    )
    etc_note = st.text_area("추가 의견(선택)", height=100, key="etc_note")

    st.markdown("### 7. 증빙서류 제출")
    business_file = st.file_uploader(
        "사업자등록증 *",
        type=["pdf", "jpg", "jpeg", "png"],
        key="business_file",
    )
    sales_file = st.file_uploader(
        "연매출 증빙서류 *",
        type=["pdf", "jpg", "jpeg", "png"],
        key="sales_file",
    )
    extra_files = st.file_uploader(
        "기타 증빙서류(선택)",
        type=["pdf", "jpg", "jpeg", "png"],
        accept_multiple_files=True,
        key="extra_files",
    )

    felt_score, felt_breakdown = calculate_felt_safety_score(
        crime_anxiety, night_business, surroundings, solo_work
    )
    security_score, security_breakdown = calculate_security_vulnerability(
        cctv_inside, security_company
    )
    preview_total = felt_score + security_score

    with st.expander("점수 산출 미리보기", expanded=True):
        st.write(f"체감안전도: {felt_score}점")
        st.write(
            f"- 범죄불안 {felt_breakdown['범죄불안']} / "
            f"야간영업 {felt_breakdown['야간영업']} / "
            f"주변환경 {felt_breakdown['주변환경']} / "
            f"단독근무 {felt_breakdown['단독근무']}"
        )
        st.write(f"보안취약도: {security_score}점")
        st.write(
            f"- CCTV미설치 {security_breakdown['CCTV미설치']} / "
            f"사설경비미이용 {security_breakdown['사설경비미이용']}"
        )
        st.write(f"현재 합계(체감안전도 + 보안취약도): {preview_total}점")

    st.markdown("### 8. 개인정보 수집·이용 동의")
    st.markdown(
        "<div style='height:220px; overflow-y:auto; border:1px solid #d9d9d9; padding:14px; border-radius:8px;'>"
        "<b>개인정보 수집·이용 동의</b><br><br>"
        "1. 수집 항목: 성명, 연락처, 점포명, 점포 주소, 업종, 연매출 정보, 제출서류 등<br>"
        "2. 수집 목적: 소상공인 방범지원 신청 접수, 대상자 검토, 현장 확인, 최종 선정 및 결과 안내<br>"
        "3. 보유 및 이용기간: 관련 법령 및 내부 기준에 따름<br>"
        "4. 동의 거부 권리: 개인정보 수집·이용에 대한 동의를 거부할 수 있으나, 이 경우 신청 접수가 제한될 수 있습니다.<br><br>"
        "※ 서류가 미비한 경우 추가 서류 제출을 요청할 수 있으며, 필요 시 현장 확인 또는 유선 연락이 진행될 수 있습니다."
        "</div>",
        unsafe_allow_html=True,
    )
    privacy_agreed = st.checkbox(
        "위 내용을 확인하였으며, 개인정보 수집·이용에 동의합니다. (필수)",
        key="privacy_agreed",
    )
    notice_agreed = st.checkbox(
        "서류 보완 요청 및 개별 연락 안내를 확인하였습니다. (필수)",
        key="notice_agreed",
    )

    if st.button("신청서 제출", use_container_width=True, type="primary"):
        now_ts = time.time()
        if now_ts - float(st.session_state.get("last_submit_ts", 0.0)) < 3:
            st.warning("잠시 후 다시 시도해 주세요.")
            st.stop()

        errors = []
        contact_normalized = _normalize_phone(contact)

        if not applicant_name.strip():
            errors.append("신청인 성명을 입력해 주세요.")
        if not contact.strip():
            errors.append("연락처를 입력해 주세요.")
        elif not PHONE_RE.match(contact_normalized.replace("-", "")) and not PHONE_RE.match(contact_normalized):
            errors.append("연락처 형식을 확인해 주세요. 예: 010-1234-5678")
        if not store_name.strip():
            errors.append("점포명을 입력해 주세요.")
        if store_type == "기타" and not store_type_other.strip():
            errors.append("기타 업종명을 입력해 주세요.")
        if not full_address.strip():
            errors.append("점포 위치를 입력해 주세요.")
        if lat is None or lon is None:
            errors.append("좌표를 확인할 수 없어 제출할 수 없습니다. 주소를 다시 선택하거나 지도를 클릭해 주세요.")
        if not business_file:
            errors.append("사업자등록증을 첨부해 주세요.")
        if not sales_file:
            errors.append("연매출 증빙서류를 첨부해 주세요.")
        if not privacy_agreed or not notice_agreed:
            errors.append("필수 동의 항목을 체크해 주세요.")

        if errors:
            for msg in errors:
                st.error(msg)
            st.stop()

        documents: List[Dict[str, Any]] = []
        upload_targets = [business_file, sales_file] + list(extra_files or [])
        for file_obj in upload_targets:
            documents.append(_upload_single_file(supabase, file_obj, police_station))

        payload = _build_payload(
            police_station=police_station,
            store_name=store_name.strip(),
            applicant_name=applicant_name.strip(),
            contact=contact_normalized,
            store_type=store_type,
            store_type_other=store_type_other.strip(),
            full_address=full_address.strip(),
            detail_address=detail_address.strip(),
            lat=float(lat),
            lon=float(lon),
            sales_band=sales_band,
            annual_sales_value=int(annual_sales_value),
            cctv_inside=cctv_inside,
            security_company=security_company,
            crime_anxiety=crime_anxiety,
            night_business=night_business,
            surroundings=surroundings,
            solo_work=solo_work,
            etc_note=etc_note.strip(),
            document_list=documents,
        )

        try:
            supabase.table("shops").insert(payload).execute()
            st.session_state["last_submit_ts"] = now_ts
            st.success("신청이 정상적으로 접수되었습니다. 검토 후 개별 연락드릴 예정입니다.")
            failed = [d for d in documents if d.get("status") != "uploaded"]
            if failed:
                st.warning(
                    "일부 첨부파일은 스토리지 버킷 설정 전이라 파일명만 저장되었습니다. "
                    "추후 버킷 설정 후 정상 업로드가 가능합니다."
                )
        except Exception as exc:
            st.error(f"저장 실패: {exc}")