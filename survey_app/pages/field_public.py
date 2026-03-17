import streamlit as st
from datetime import datetime
import re
import time
import requests

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

    # ==================================================
    # 0) 주소 검색/선택
    # ==================================================
    st.subheader("📍 주소 검색 (필수)")
    addr_query = st.text_input("도로명주소 검색", placeholder="예) 전남 무안군 삼향읍 남악3로 71")

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

    selected_addr = st.session_state.get("selected_address", "").strip()

    st.divider()

    # ==================================================
    # 1) 설문 입력 (st.form 제거: 즉시 반응)
    # ==================================================
    st.subheader("① 현장 관서 정보 (필수)")
    officer_station = st.selectbox("관서 *", JEONNAM_POLICE_STATIONS)

    st.subheader("② 점포 기본 정보")
    shop_name = st.text_input("점포명 (선택)")
    st.text_input("점포 주소 *", value=selected_addr, disabled=True)

    colA, colB = st.columns(2)
    with colA:
        owner_name = st.text_input("점주 이름 (선택)")
    with colB:
        owner_phone = st.text_input("점주 전화번호 (선택)", placeholder="010-1234-5678")

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

    st.caption("영업시간(간략 선택)")
    biz_hours = st.radio(
        "영업시간",
        ["24시간", "주간(09~18)", "야간(18~24)", "심야(22~02)", "직접입력"],
        horizontal=True,
        index=1,
        key="biz_hours",
        label_visibility="collapsed",
    )

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

    # ✅ 변경: CCTV 작동확인 -> 매장 내 CCTV 보유 여부
    has_cctv = st.checkbox("매장 내 CCTV 보유 여부")

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

    # ✅ 변경: 괄호 문구 제거
    has_emergency_bell = st.checkbox("비상벨 보유 여부")

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

    st.divider()

    # ==================================================
    # 2) 제출 처리
    # ==================================================
    if st.button("✅ 설문 제출", use_container_width=True):
        now_ts = time.time()
        if now_ts - st.session_state["last_submit_ts"] < 3:
            st.warning("잠시 후 다시 시도해 주세요. (연속 제출 방지)")
            st.stop()

        # 필수 체크
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

        phone = _clean_phone(owner_phone)
        if phone and not PHONE_RE.match(phone):
            st.warning("전화번호 형식이 이상합니다. 예: 010-1234-5678 (그래도 저장은 진행)")

        uses_security_company = (security_status == "이용 중")

        # ✅ 추가 설문 결과를 overall_comment에 구조화 텍스트로 합침(DB 변경 없이 저장)
        extra_block_lines = [
            "[추가설문]",
            f"업종={biz_type}",
            f"야간단독={night_alone}",
            f"주변환경={surroundings}",
            f"사각지대={blind_spot}",
            f"조명={lighting}",
            f"매장내CCTV={'있음' if has_cctv else '없음'}",
            f"영업시간선택={biz_hours}",
        ]

        if biz_hours == "직접입력" and open_t and close_t:
            extra_block_lines.append(f"영업시간직접입력={open_t.strftime('%H:%M')}~{close_t.strftime('%H:%M')}")

        if security_status:
            extra_block_lines.append(f"사설경비={security_status}")
        if security_company_name and security_company_name.strip():
            extra_block_lines.append(f"경비업체명={security_company_name.strip()}")

        extra_block = "\n".join(extra_block_lines)

        overall_comment_final = (overall_comment or "").strip()
        if overall_comment_final:
            overall_comment_final = f"{overall_comment_final}\n\n{extra_block}"
        else:
            overall_comment_final = extra_block

        other_security_final = (other_security or "").strip()
        if security_company_name and security_company_name.strip():
            line = f"경비업체명: {security_company_name.strip()}"
            if other_security_final:
                other_security_final = f"{other_security_final}\n{line}"
            else:
                other_security_final = line

        payload = {
            "shop_name": shop_name.strip() if shop_name else None,
            "address": selected_addr,
            "station": officer_station,

            "lat": float(lat),
            "lon": float(lon),
            "lng": float(lon),

            "grid_id": grid_id,

            "annual_sales": int(annual_sales) if annual_sales else 0,
            "employment_type": employment_type,

            "uses_security_company": bool(uses_security_company),
            "has_emergency_bell": bool(has_emergency_bell),
            "has_cctv": bool(has_cctv),
            "other_security": other_security_final if other_security_final else None,

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