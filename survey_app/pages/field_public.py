import streamlit as st
from datetime import datetime
import re
import time
import requests
import folium
from streamlit_folium import st_folium

# ✅ 100m 국가지점번호 grid_id 계산
from core.national_point import latlon_to_grid_id_100m

# =========================================================
# 전남 22개 경찰서
# =========================================================
JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서", "고흥경찰서",
    "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서", "영광경찰서", "화순경찰서",
    "함평경찰서", "영암경찰서", "장성경찰서", "강진경찰서", "담양경찰서", "곡성경찰서",
    "완도경찰서", "진도경찰서", "구례경찰서", "신안경찰서",
]

PHONE_RE = re.compile(r"^01[0-9]-?\d{3,4}-?\d{4}$")


def _clean_phone(v: str) -> str:
    v = (v or "").strip()
    return v.replace(" ", "")


def _fmt_coord(v):
    try:
        return f"{float(v):.6f}"
    except Exception:
        return ""


# =========================================================
# JUSO: 도로명주소 검색
# =========================================================
def juso_search(keyword: str, page: int = 1, size: int = 10):
    """JUSO 도로명주소 검색 API (JSON)"""
    confm_key = st.secrets.get("JUSO_CONFM_KEY", "").strip()
    if not confm_key:
        st.error("secrets.toml에 JUSO_CONFM_KEY가 없습니다. (survey_app/.streamlit/secrets.toml 확인)")
        return []

    url = "https://www.juso.go.kr/addrlink/addrLinkApi.do"
    params = {
        "confmKey": confm_key,
        "currentPage": page,
        "countPerPage": size,
        "keyword": keyword,
        "resultType": "json",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get("results", {}).get("juso", []) or []


# =========================================================
# VWorld: 키 가져오기 & 주소 정리
# =========================================================
def _get_vworld_key() -> str:
    """프로젝트마다 키 이름이 다를 수 있어서 여러 후보를 허용"""
    for k in ["VWORLD_KEY", "VWORLD_API_KEY", "VWorld_KEY", "vworld_key"]:
        v = st.secrets.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _clean_addr_for_geocode(addr: str) -> str:
    """괄호 안(건물명 등) 제거 + 공백 정리"""
    a = (addr or "").strip()
    a = re.sub(r"\(.*?\)", "", a).strip()
    a = re.sub(r"\s+", " ", a).strip()
    return a


def vworld_geocode(address: str, addr_type: str = "road"):
    """
    VWorld 주소→좌표 변환
    - addr_type: "road"(도로명) / "parcel"(지번)
    - EPSG:4326(WGS84)
    - 반환: (lat, lon) 또는 (None, None)
    """
    key = _get_vworld_key()
    if not key:
        st.error("secrets.toml에 VWorld 키가 없습니다. (예: VWORLD_KEY)")
        return None, None

    addr = _clean_addr_for_geocode(address)
    if not addr:
        return None, None

    url = "https://api.vworld.kr/req/address"
    params = {
        "service": "address",
        "request": "getcoord",
        "format": "json",
        "crs": "epsg:4326",
        "address": addr,
        "type": addr_type,   # road / parcel
        "key": key,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        resp = data.get("response", {})
        if resp.get("status") != "OK":
            return None, None

        result = resp.get("result", {})
        point = result.get("point", {}) if isinstance(result, dict) else {}
        lon = point.get("x")
        lat = point.get("y")

        if lon is None or lat is None:
            return None, None

        return float(lat), float(lon)

    except Exception:
        return None, None


# =========================================================
# 핀 지정 지도
# =========================================================
def _render_pin_picker_map():
    """
    모바일 부담을 줄이기 위해:
    - 핀 지정 모드일 때만 렌더링
    - 격자/경계/레이어 없이 가벼운 기본 지도만 사용
    - 클릭 좌표 1개만 저장
    """
    pin_lat = st.session_state.get("pin_lat")
    pin_lon = st.session_state.get("pin_lon")
    auto_lat = st.session_state.get("auto_lat")
    auto_lon = st.session_state.get("auto_lon")

    # 초기 중심점:
    # 1) 이미 찍은 핀
    # 2) 주소검색 좌표가 있으면 그 위치
    # 3) 없으면 전남권 대략 중앙값
    if pin_lat is not None and pin_lon is not None:
        center_lat, center_lon = float(pin_lat), float(pin_lon)
        zoom = 18
    elif auto_lat is not None and auto_lon is not None:
        center_lat, center_lon = float(auto_lat), float(auto_lon)
        zoom = 17
    else:
        center_lat, center_lon = 34.85, 126.85
        zoom = 11

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        control_scale=True,
        prefer_canvas=True,
        tiles="OpenStreetMap",
    )

    if pin_lat is not None and pin_lon is not None:
        folium.Marker(
            [float(pin_lat), float(pin_lon)],
            tooltip="선택한 위치",
            popup="선택한 위치",
        ).add_to(m)

    map_data = st_folium(
        m,
        key="field_public_pin_map",
        height=420,
        width=None,
        returned_objects=["last_clicked"],
    )

    clicked = (map_data or {}).get("last_clicked")
    if clicked and clicked.get("lat") is not None and clicked.get("lng") is not None:
        new_lat = round(float(clicked["lat"]), 8)
        new_lon = round(float(clicked["lng"]), 8)

        old_lat = st.session_state.get("pin_lat")
        old_lon = st.session_state.get("pin_lon")

        # 같은 클릭으로 무한 rerun 방지
        changed = (
            old_lat is None or old_lon is None
            or abs(float(old_lat) - new_lat) > 1e-10
            or abs(float(old_lon) - new_lon) > 1e-10
        )

        if changed:
            st.session_state["pin_lat"] = new_lat
            st.session_state["pin_lon"] = new_lon
            try:
                st.session_state["pin_grid_id"] = latlon_to_grid_id_100m(new_lat, new_lon)
            except Exception:
                st.session_state["pin_grid_id"] = ""
            st.rerun()


# =========================================================
# 페이지 본문
# =========================================================
def field_public_page(supabase):
    st.title("📝 소상공인 방범물품 지원 설문 (현장 접수)")

    # 연속 제출 방지
    st.session_state.setdefault("last_submit_ts", 0)

    # 세션 초기화
    st.session_state.setdefault("addr_candidates", [])
    st.session_state.setdefault("selected_address", "")
    st.session_state.setdefault("selected_jibun", "")
    st.session_state.setdefault("selected_zipno", "")

    # 주소 기반 자동 좌표
    st.session_state.setdefault("auto_lat", None)
    st.session_state.setdefault("auto_lon", None)

    # 계산된 grid_id
    st.session_state.setdefault("auto_grid_id", "")

    # 핀 기반 좌표
    st.session_state.setdefault("pin_lat", None)
    st.session_state.setdefault("pin_lon", None)
    st.session_state.setdefault("pin_grid_id", "")

    # 핀 지도 열기 여부
    st.session_state.setdefault("show_pin_map", False)

    # ==================================================
    # 0) 위치 입력 방식
    # ==================================================
    st.subheader("📍 위치 입력 방식")
    location_input_mode = st.radio(
        "위치 입력 방식",
        ["주소검색", "핀 지정"],
        horizontal=True,
        key="location_input_mode",
        label_visibility="collapsed",
    )

    # ==================================================
    # 0-1) 주소검색 방식
    # ==================================================
    if location_input_mode == "주소검색":
        st.subheader("📍 주소 검색 (필수)")
        addr_query = st.text_input(
            "도로명주소 검색",
            placeholder="예) 전남 무안군 삼향읍 남악3로 71",
            key="addr_query",
        )

        col_s1, _ = st.columns([1, 3])
        with col_s1:
            do_search = st.button("🔎 검색")

        if do_search:
            if not addr_query.strip():
                st.warning("검색어를 입력하세요.")
            else:
                try:
                    candidates = juso_search(addr_query.strip(), page=1, size=10)
                    st.session_state["addr_candidates"] = candidates
                except Exception as e:
                    st.error(f"주소 검색 실패: {e}")
                    st.session_state["addr_candidates"] = []

        candidates = st.session_state.get("addr_candidates", []) or []
        if candidates:
            options = []
            for j in candidates:
                road = j.get("roadAddr", "")
                jibun = j.get("jibunAddr", "")
                zipno = j.get("zipNo", "")
                options.append(f"{road}  |  지번: {jibun}  |  우편: {zipno}")

            picked = st.selectbox("검색 결과 선택", options, key="addr_pick")
            idx = options.index(picked)
            picked_j = candidates[idx]

            st.session_state["selected_address"] = (picked_j.get("roadAddr") or "").strip()
            st.session_state["selected_jibun"] = (picked_j.get("jibunAddr") or "").strip()
            st.session_state["selected_zipno"] = (picked_j.get("zipNo") or "").strip()

            # ✅ 좌표 자동 계산 (road → 실패 시 parcel)
            addr_for_geo = st.session_state["selected_address"]
            lat, lon = vworld_geocode(addr_for_geo, "road")
            if lat is None or lon is None:
                jibun_for_geo = st.session_state.get("selected_jibun", "")
                lat, lon = vworld_geocode(jibun_for_geo, "parcel") if jibun_for_geo else (None, None)

            st.session_state["auto_lat"] = lat
            st.session_state["auto_lon"] = lon

            # grid_id 계산
            if lat is not None and lon is not None:
                try:
                    gid = latlon_to_grid_id_100m(float(lat), float(lon))
                    st.session_state["auto_grid_id"] = gid
                except Exception:
                    st.session_state["auto_grid_id"] = ""
            else:
                st.session_state["auto_grid_id"] = ""

            # 주소검색 모드에서 새 주소를 고르면 핀값은 건드리지 않음
            # (모드 전환 시 참고용으로 남겨둘 수 있게 함)

        selected_addr = st.session_state.get("selected_address", "").strip()

    # ==================================================
    # 0-2) 핀 지정 방식
    # ==================================================
    else:
        st.subheader("📍 핀 지정")
        st.caption("모바일 속도를 위해 지도를 상시 띄우지 않고, 필요할 때만 열도록 했습니다.")

        pin_location_note = st.text_input(
            "위치 설명(선택)",
            placeholder="예) 남악 ○○상가 1층 코너 점포 / 건물명 / 도로명주소",
            key="pin_location_note",
        )

        st.checkbox(
            "핀 지정 지도 열기",
            key="show_pin_map",
            help="체크했을 때만 지도를 표시합니다.",
        )

        if st.session_state.get("show_pin_map"):
            st.caption("지도를 클릭하면 해당 위치로 핀이 지정됩니다.")
            _render_pin_picker_map()

            pin_lat = st.session_state.get("pin_lat")
            pin_lon = st.session_state.get("pin_lon")
            pin_grid_id = (st.session_state.get("pin_grid_id") or "").strip()

            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.text_input(
                    "선택 위도",
                    value=_fmt_coord(pin_lat),
                    disabled=True,
                    key="pin_lat_preview",
                )
            with col_p2:
                st.text_input(
                    "선택 경도",
                    value=_fmt_coord(pin_lon),
                    disabled=True,
                    key="pin_lon_preview",
                )

            st.text_input(
                "계산된 국가지점번호(100m)",
                value=pin_grid_id,
                disabled=True,
                key="pin_grid_preview",
            )

            col_reset, _ = st.columns([1, 3])
            with col_reset:
                if st.button("핀 초기화"):
                    st.session_state["pin_lat"] = None
                    st.session_state["pin_lon"] = None
                    st.session_state["pin_grid_id"] = ""
                    st.rerun()

        selected_addr = (st.session_state.get("pin_location_note") or "").strip()

    st.divider()

    # ==================================================
    # 1) 설문 입력 (st.form 제거: 즉시 반응)
    # ==================================================
    st.subheader("① 현장 관서 정보 (필수)")
    officer_station = st.selectbox("관서 *", JEONNAM_POLICE_STATIONS)

    st.subheader("② 점포 기본 정보")
    shop_name = st.text_input("점포명 (선택)")

    if location_input_mode == "주소검색":
        st.text_input("점포 주소 *", value=selected_addr, disabled=True)
    else:
        pin_lat = st.session_state.get("pin_lat")
        pin_lon = st.session_state.get("pin_lon")
        pin_grid_id = (st.session_state.get("pin_grid_id") or "").strip()

        pin_addr_display = selected_addr if selected_addr else "핀 지정 위치"
        st.text_input("점포 위치 *", value=pin_addr_display, disabled=True)

        c_pos1, c_pos2 = st.columns(2)
        with c_pos1:
            st.text_input("위도", value=_fmt_coord(pin_lat), disabled=True, key="pin_lat_readonly")
        with c_pos2:
            st.text_input("경도", value=_fmt_coord(pin_lon), disabled=True, key="pin_lon_readonly")

        st.text_input("국가지점번호(100m)", value=pin_grid_id, disabled=True, key="pin_gid_readonly")

    colA, colB = st.columns(2)
    with colA:
        owner_name = st.text_input("점주 이름 (선택)")
    with colB:
        owner_phone = st.text_input("점주 전화번호 (선택)", placeholder="010-1234-5678")

    # ✅ 동글뱅이(라디오) 선택
    owner_gender = st.radio("성별", ["남", "여"], horizontal=True)

    st.caption("연령대(선택)")
    owner_age_group = st.radio(
        "연령대",
        ["10대", "20대", "30대", "40대", "50대", "60대+", "미상"],
        horizontal=True,
        index=6,
        key="owner_age_group",
        label_visibility="collapsed",
    )

    st.subheader("③ 운영/시설/보안 현황")

    # ✅ 영업시간(간략 라디오)
    st.caption("영업시간(간략 선택)")
    biz_hours = st.radio(
        "영업시간",
        ["24시간", "주간(09~18)", "야간(18~24)", "심야(22~02)", "직접입력"],
        horizontal=True,
        index=1,  # 기본값: 주간
        key="biz_hours",
        label_visibility="collapsed",
    )

    # 직접입력 선택 시만 시간 입력
    open_t, close_t = None, None
    if biz_hours == "직접입력":
        c1, c2 = st.columns(2)
        with c1:
            open_t = st.time_input("오픈", key="open_t")
        with c2:
            close_t = st.time_input("마감", key="close_t")

    annual_sales = st.number_input("연 매출(원) (선택)", min_value=0, value=0, step=1000000)

    st.caption("고용 형태(선택)")
    employment_type_choice = st.radio(
        "고용 형태",
        ["선택안함", "1인", "가족경영", "직원고용"],
        horizontal=True,
        index=0,
        key="employment_type_choice",
        label_visibility="collapsed",
    )
    employment_type = None if employment_type_choice == "선택안함" else employment_type_choice

    # ✅ 추가 설문(최소세트 6개) - 전부 라디오(동글뱅이)
    st.subheader("③-1 추가 점검 항목(간단 선택)")

    st.caption("업종")
    biz_type = st.radio(
        "업종",
        ["편의점", "음식점", "주점", "카페", "미용", "소매", "기타", "미상"],
        horizontal=True,
        index=7,
        key="biz_type",
        label_visibility="collapsed",
    )

    st.caption("야간 단독근무")
    night_alone = st.radio(
        "야간 단독근무",
        ["있음", "없음", "미상"],
        horizontal=True,
        index=2,
        key="night_alone",
        label_visibility="collapsed",
    )

    st.caption("주변 환경")
    주변환경_options = ["골목", "대로변", "주택가", "상가밀집", "유흥가 인접", "미상"]
    surroundings = st.radio(
        "주변 환경",
        주변환경_options,
        horizontal=True,
        index=5,
        key="surroundings",
        label_visibility="collapsed",
    )

    st.caption("사각지대 체감")
    blind_spot = st.radio(
        "사각지대",
        ["없음", "약간", "많음", "미상"],
        horizontal=True,
        index=3,
        key="blind_spot",
        label_visibility="collapsed",
    )

    st.caption("조명 상태(출입구/주변)")
    lighting = st.radio(
        "조명",
        ["양호", "보통", "불량", "확인 불가"],
        horizontal=True,
        index=3,
        key="lighting",
        label_visibility="collapsed",
    )

    st.caption("CCTV 작동 확인")
    cctv_check = st.radio(
        "CCTV 작동",
        ["미확인", "정상", "불량"],
        horizontal=True,
        index=0,
        key="cctv_check",
        label_visibility="collapsed",
    )

    # ✅ 사설경비(보안업체) 이용 여부: 라디오
    st.caption("사설경비(보안업체) 이용 여부(선택)")
    security_status = st.radio(
        "보안업체",
        ["미이용", "이용 중", "확인 불가"],
        horizontal=True,
        index=0,
        key="security_status",
        label_visibility="collapsed",
    )
    security_company_name = None
    if security_status == "이용 중":
        security_company_name = st.text_input("경비업체명(선택)", key="security_company_name")

    # 기존 점수 반영 체크는 유지
    has_emergency_bell = st.checkbox("비상벨 보유 여부 (체감안전도 점수에서 -10 반영)")
    has_cctv = st.checkbox("CCTV 보유 여부 (체감안전도 점수에서 -10 반영)")

    other_security = st.text_area("기타 보안시설 (선택)", placeholder="예) 방범창, 자동문, 출입통제 등")

    st.subheader("④ 체감안전도 (5단계)")
    LEVEL_TO_SCORE = {
        "매우 불안": 100,
        "불안": 75,
        "보통": 50,
        "안전": 25,
        "매우 안전": 0,
    }
    level = st.radio("점포주 체감안전도", list(LEVEL_TO_SCORE.keys()), horizontal=True)
    perceived_safety = int(LEVEL_TO_SCORE[level])

    overall_comment = st.text_area("추가 의견 (선택)")

    # ==================================================
    # ✅ 즉시 반응 미리보기
    # ==================================================
    resident_adj_preview = max(
        0,
        perceived_safety
        - (10 if has_emergency_bell else 0)
        - (10 if has_cctv else 0)
    )
    reflected_risk_preview = 100 - resident_adj_preview  # 우선순위 반영값(불안도)
    st.info(
        f"✅ 미리보기(즉시 반응)\n\n"
        f"- 저장될 체감안전도 점수(perceived_safety): {perceived_safety}\n"
        f"- 감점 반영 후 주관점수(resident_adj): {resident_adj_preview}\n"
        f"- 우선순위 반영값(불안도 = 100 - resident_adj): {reflected_risk_preview}"
    )

    st.divider()

    # ==================================================
    # 2) 제출 처리
    # ==================================================
    if st.button("✅ 설문 제출", use_container_width=True):
        now_ts = time.time()
        if now_ts - st.session_state["last_submit_ts"] < 3:
            st.warning("잠시 후 다시 시도해 주세요. (연속 제출 방지)")
            st.stop()

        # 위치 입력 방식별 저장값 결정
        if location_input_mode == "주소검색":
            if not selected_addr:
                st.error("주소 검색 후 결과에서 주소를 선택해야 합니다.")
                st.stop()

            lat = st.session_state.get("auto_lat")
            lon = st.session_state.get("auto_lon")
            if lat is None or lon is None:
                st.error("주소 기반 좌표 산출 실패로 저장할 수 없습니다. (주소를 더 정확히 검색/선택해 주세요)")
                st.stop()

            grid_id = (st.session_state.get("auto_grid_id") or "").strip()
            if not grid_id:
                try:
                    grid_id = latlon_to_grid_id_100m(float(lat), float(lon))
                except Exception as e:
                    st.error(f"grid_id(국가지점번호 100m) 계산 실패: {e}")
                    st.stop()

            address_to_save = selected_addr

        else:
            lat = st.session_state.get("pin_lat")
            lon = st.session_state.get("pin_lon")

            if lat is None or lon is None:
                st.error("핀 지정 모드에서는 지도에서 위치를 찍어야 합니다.")
                st.stop()

            grid_id = (st.session_state.get("pin_grid_id") or "").strip()
            if not grid_id:
                try:
                    grid_id = latlon_to_grid_id_100m(float(lat), float(lon))
                except Exception as e:
                    st.error(f"grid_id(국가지점번호 100m) 계산 실패: {e}")
                    st.stop()

            pin_location_note = (st.session_state.get("pin_location_note") or "").strip()
            if pin_location_note:
                address_to_save = pin_location_note
            else:
                address_to_save = f"핀 지정 위치 ({float(lat):.6f}, {float(lon):.6f})"

        phone = _clean_phone(owner_phone)
        if phone and not PHONE_RE.match(phone):
            st.warning("전화번호 형식이 이상합니다. 예: 010-1234-5678 (그래도 저장은 진행)")

        # ✅ DB 컬럼 깨질 위험 때문에 새 컬럼은 추가하지 않음
        # - uses_security_company: boolean 유지 (이용 중이면 True)
        uses_security_company = (security_status == "이용 중")

        # ✅ 추가 설문 결과를 overall_comment에 구조화 텍스트로 합침(DB 변경 없이 저장)
        extra_block_lines = [
            "[추가설문]",
            f"위치입력방식={location_input_mode}",
            f"업종={biz_type}",
            f"야간단독={night_alone}",
            f"주변환경={surroundings}",
            f"사각지대={blind_spot}",
            f"조명={lighting}",
            f"CCTV작동확인={cctv_check}",
            f"영업시간선택={biz_hours}",
        ]

        if location_input_mode == "핀 지정":
            extra_block_lines.append(f"핀위치={float(lat):.6f},{float(lon):.6f}")
            extra_block_lines.append(f"핑리드={grid_id}")

        if biz_hours == "직접입력" and open_t and close_t:
            extra_block_lines.append(f"영업시간직접입력={open_t.strftime('%H:%M')}~{close_t.strftime('%H:%M')}")

        if security_status:
            extra_block_lines.append(f"사설경비={security_status}")
        if security_company_name and security_company_name.strip():
            extra_block_lines.append(f"경비업체명={security_company_name.strip()}")

        extra_block = "\n".join(extra_block_lines)

        # overall_comment에 붙이기
        overall_comment_final = (overall_comment or "").strip()
        if overall_comment_final:
            overall_comment_final = f"{overall_comment_final}\n\n{extra_block}"
        else:
            overall_comment_final = extra_block

        # 경비업체명은 기존 other_security에도 합쳐 저장(혹시 현장에서 찾기 쉽게)
        other_security_final = (other_security or "").strip()
        if security_company_name and security_company_name.strip():
            line = f"경비업체명: {security_company_name.strip()}"
            if other_security_final:
                other_security_final = f"{other_security_final}\n{line}"
            else:
                other_security_final = line

        payload = {
            "shop_name": shop_name.strip() if shop_name else None,
            "address": address_to_save,
            "station": officer_station,

            # ✅ 저장 좌표
            "lat": float(lat),
            "lon": float(lon),
            "lng": float(lon),

            # ✅ 저장 grid_id
            "grid_id": grid_id,

            "annual_sales": int(annual_sales) if annual_sales else 0,
            "employment_type": employment_type,

            "uses_security_company": bool(uses_security_company),
            "has_emergency_bell": bool(has_emergency_bell),
            "has_cctv": bool(has_cctv),
            "other_security": other_security_final if other_security_final else None,

            # ✅ 설문 점수
            "perceived_safety": int(perceived_safety),

            "overall_comment": overall_comment_final if overall_comment_final else None,

            "owner_name": owner_name.strip() if owner_name else None,
            "owner_phone": phone if phone else None,
            "owner_gender": owner_gender,
            "owner_age_group": owner_age_group,

            "officer_station": officer_station,

            "updated_at": datetime.now().isoformat(),
        }

        try:
            supabase.table("shops").insert(payload).execute()
            st.session_state["last_submit_ts"] = now_ts
            st.success("✅ 설문이 정상적으로 제출되었습니다.")
        except Exception as e:
            st.error(f"저장 실패: {e}")