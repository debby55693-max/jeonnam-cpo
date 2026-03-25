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

# ✅ 재시도 설정
JUSO_RETRY_COUNT = 2
JUSO_RETRY_WAIT_SEC = 1.0

VWORLD_RETRY_COUNT = 3
VWORLD_RETRY_WAIT_SEC = 1.0


def _clean_phone(v: str) -> str:
    v = (v or "").strip()
    return v.replace(" ", "")


# =========================================================
# JUSO: 도로명주소 검색
# =========================================================
def juso_search(keyword: str, page: int = 1, size: int = 10):
    """JUSO 도로명주소 검색 API (JSON)"""
    confm_key = str(st.secrets.get("JUSO_CONFM_KEY", "")).strip()
    if not confm_key:
        st.error("secrets.toml에 JUSO_CONFM_KEY가 없습니다.")
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
# JUSO 좌표제공 API (우선 사용)
# =========================================================
def _epsg5179_to_wgs84(x: float, y: float):
    """
    JUSO 좌표(entX, entY)는 EPSG:5179(UTM-K GRS80)
    -> WGS84 위경도(lat, lon)로 변환
    """
    try:
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
        lon, lat = transformer.transform(float(x), float(y))
        return float(lat), float(lon), None
    except Exception as e:
        return None, None, str(e)


def juso_coord_search(juso_item: dict):
    """
    JUSO 검색 결과의 admCd/rnMgtSn/udrtYn/buldMnnm/buldSlno를 이용해
    좌표제공 API(addrCoordApi.do) 호출
    반환: (lat, lon, debug_dict)
    """
    # ✅ 여기 핵심 수정: 주소검색용 키가 아니라 좌표제공용 키를 읽어야 함
    confm_key = str(st.secrets.get("JUSO_COORD_CONFM_KEY", "")).strip()

    debug = {
        "api": "juso_addrCoordApi",
        "has_key": bool(confm_key),
        "admCd": (juso_item or {}).get("admCd"),
        "rnMgtSn": (juso_item or {}).get("rnMgtSn"),
        "udrtYn": (juso_item or {}).get("udrtYn"),
        "buldMnnm": (juso_item or {}).get("buldMnnm"),
        "buldSlno": (juso_item or {}).get("buldSlno"),
        "http_status": None,
        "errorCode": None,
        "errorMessage": None,
        "entX": None,
        "entY": None,
        "lat": None,
        "lon": None,
        "transform_error": None,
        "raw_response": None,
        "exception": None,
        "attempts": [],
    }

    if not confm_key:
        debug["errorCode"] = "NO_KEY"
        debug["errorMessage"] = "JUSO_COORD_CONFM_KEY가 없습니다."
        return None, None, debug

    adm_cd = str((juso_item or {}).get("admCd") or "").strip()
    rn_mgt_sn = str((juso_item or {}).get("rnMgtSn") or "").strip()
    udrt_yn = str((juso_item or {}).get("udrtYn") or "0").strip()
    buld_mnnm = str((juso_item or {}).get("buldMnnm") or "").strip()
    buld_slno = str((juso_item or {}).get("buldSlno") or "0").strip()

    if not (adm_cd and rn_mgt_sn and buld_mnnm):
        debug["errorCode"] = "MISSING_PARAM"
        debug["errorMessage"] = "좌표 API 필수 파라미터(admCd/rnMgtSn/buldMnnm)가 부족합니다."
        return None, None, debug

    url = "https://www.juso.go.kr/addrlink/addrCoordApi.do"
    params = {
        "confmKey": confm_key,
        "admCd": adm_cd,
        "rnMgtSn": rn_mgt_sn,
        "udrtYn": udrt_yn,
        "buldMnnm": buld_mnnm,
        "buldSlno": buld_slno,
        "resultType": "json",
    }

    for attempt in range(1, JUSO_RETRY_COUNT + 1):
        attempt_log = {
            "attempt": attempt,
            "http_status": None,
            "exception": None,
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            attempt_log["http_status"] = r.status_code
            debug["http_status"] = r.status_code
            r.raise_for_status()

            data = r.json()
            debug["raw_response"] = data

            results = data.get("results", {}) if isinstance(data, dict) else {}
            common = results.get("common", {}) if isinstance(results, dict) else {}
            debug["errorCode"] = common.get("errorCode")
            debug["errorMessage"] = common.get("errorMessage")

            debug["attempts"].append(attempt_log)

            if str(common.get("errorCode")) != "0":
                return None, None, debug

            juso_list = results.get("juso", []) or []
            if not juso_list:
                debug["errorCode"] = "NO_RESULT"
                debug["errorMessage"] = "좌표 API 결과가 없습니다."
                return None, None, debug

            first = juso_list[0]
            ent_x = first.get("entX")
            ent_y = first.get("entY")
            debug["entX"] = ent_x
            debug["entY"] = ent_y

            if ent_x in [None, ""] or ent_y in [None, ""]:
                debug["errorCode"] = "NO_COORD"
                debug["errorMessage"] = "좌표 API 결과에 entX/entY가 없습니다."
                return None, None, debug

            lat, lon, transform_error = _epsg5179_to_wgs84(ent_x, ent_y)
            debug["transform_error"] = transform_error
            debug["lat"] = lat
            debug["lon"] = lon

            if lat is None or lon is None:
                debug["errorCode"] = "TRANSFORM_FAIL"
                debug["errorMessage"] = "EPSG:5179 → WGS84 변환 실패"
                return None, None, debug

            return lat, lon, debug

        except requests.HTTPError as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)

            if debug["http_status"] in [500, 502, 503, 504] and attempt < JUSO_RETRY_COUNT:
                time.sleep(JUSO_RETRY_WAIT_SEC)
                continue
            return None, None, debug

        except requests.RequestException as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)

            if attempt < JUSO_RETRY_COUNT:
                time.sleep(JUSO_RETRY_WAIT_SEC)
                continue
            return None, None, debug

        except Exception as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)
            return None, None, debug

    return None, None, debug


# =========================================================
# VWorld: 키 가져오기 & 주소 정리 (fallback 전용)
# =========================================================
def _get_vworld_key() -> str:
    # ✅ 별칭 남겨두긴 하지만, 실제론 VWORLD_KEY 하나만 쓰는 걸 권장
    for k in ["VWORLD_KEY", "VWORLD_API_KEY", "VWorld_KEY", "vworld_key"]:
        v = st.secrets.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _clean_addr_for_geocode(addr: str) -> str:
    a = (addr or "").strip()
    a = re.sub(r"\(.*?\)", "", a).strip()
    a = re.sub(r"\s+", " ", a).strip()
    return a


def vworld_geocode(address: str, addr_type: str = "road"):
    """
    VWorld 주소→좌표 변환
    - addr_type: road / parcel
    - 반환: (lat, lon, debug_dict)
    """
    key = _get_vworld_key()
    debug = {
        "api": "vworld_getcoord",
        "request_address_raw": address,
        "request_address_cleaned": _clean_addr_for_geocode(address),
        "request_type": addr_type,
        "has_key": bool(key),
        "http_status": None,
        "response_status": None,
        "error_code": None,
        "error_text": None,
        "refined_text": None,
        "point_x": None,
        "point_y": None,
        "exception": None,
        "raw_response": None,
        "attempts": [],
    }

    if not key:
        debug["error_code"] = "NO_KEY"
        debug["error_text"] = "secrets.toml에 VWorld 키가 없습니다. (예: VWORLD_KEY)"
        return None, None, debug

    addr = debug["request_address_cleaned"]
    if not addr:
        debug["error_code"] = "EMPTY_ADDRESS"
        debug["error_text"] = "좌표 변환용 주소가 비어 있습니다."
        return None, None, debug

    url = "https://api.vworld.kr/req/address"
    params = {
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "format": "json",
        "errorformat": "json",
        "crs": "epsg:4326",
        "refine": "true",
        "simple": "false",
        "address": addr,
        "type": addr_type,
        "key": key,
    }

    for attempt in range(1, VWORLD_RETRY_COUNT + 1):
        attempt_log = {
            "attempt": attempt,
            "http_status": None,
            "exception": None,
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            attempt_log["http_status"] = r.status_code
            debug["http_status"] = r.status_code
            r.raise_for_status()

            data = r.json()
            debug["raw_response"] = data

            resp = data.get("response", {}) if isinstance(data, dict) else {}
            debug["response_status"] = resp.get("status")

            err = resp.get("error", {}) if isinstance(resp, dict) else {}
            if isinstance(err, dict):
                debug["error_code"] = err.get("code")
                debug["error_text"] = err.get("text")

            refined = resp.get("refined", {}) if isinstance(resp, dict) else {}
            if isinstance(refined, dict):
                debug["refined_text"] = refined.get("text")

            debug["attempts"].append(attempt_log)

            if resp.get("status") != "OK":
                return None, None, debug

            result = resp.get("result", {}) if isinstance(resp, dict) else {}
            point = result.get("point", {}) if isinstance(result, dict) else {}

            lon = point.get("x")
            lat = point.get("y")
            debug["point_x"] = lon
            debug["point_y"] = lat

            if lon is None or lat is None:
                debug["error_code"] = debug["error_code"] or "NO_POINT"
                debug["error_text"] = debug["error_text"] or "응답은 왔지만 좌표(point)가 없습니다."
                return None, None, debug

            return float(lat), float(lon), debug

        except requests.HTTPError as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)

            if debug["http_status"] in [500, 502, 503, 504] and attempt < VWORLD_RETRY_COUNT:
                time.sleep(VWORLD_RETRY_WAIT_SEC)
                continue
            return None, None, debug

        except requests.RequestException as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)

            # ✅ 연결 끊김도 재시도
            if attempt < VWORLD_RETRY_COUNT:
                time.sleep(VWORLD_RETRY_WAIT_SEC)
                continue
            return None, None, debug

        except Exception as e:
            attempt_log["exception"] = str(e)
            debug["exception"] = str(e)
            debug["attempts"].append(attempt_log)
            return None, None, debug

    return None, None, debug


def _render_geo_debug():
    debug = st.session_state.get("geo_debug") or {}
    if not debug:
        return

    with st.expander("좌표 변환 디버그 보기", expanded=False):
        juso_debug = debug.get("juso_coord", {})
        road_debug = debug.get("road", {})
        parcel_debug = debug.get("parcel", {})

        st.markdown("**JUSO 좌표제공 API 시도**")
        if juso_debug:
            st.json(juso_debug)
        else:
            st.caption("JUSO 좌표 시도 정보 없음")

        st.markdown("**VWorld 도로명 주소 변환 시도**")
        if road_debug:
            st.json(road_debug)
        else:
            st.caption("VWorld 도로명 시도 정보 없음")

        st.markdown("**VWorld 지번 주소 변환 시도**")
        if parcel_debug:
            st.json(parcel_debug)
        else:
            st.caption("VWorld 지번 시도 정보 없음")


def _make_geo_request_key(juso_item: dict) -> str:
    """
    같은 주소에 대해 rerun 때마다 좌표 API를 반복 호출하지 않기 위한 키
    """
    j = juso_item or {}
    parts = [
        str(j.get("roadAddr") or "").strip(),
        str(j.get("jibunAddr") or "").strip(),
        str(j.get("zipNo") or "").strip(),
        str(j.get("admCd") or "").strip(),
        str(j.get("rnMgtSn") or "").strip(),
        str(j.get("udrtYn") or "").strip(),
        str(j.get("buldMnnm") or "").strip(),
        str(j.get("buldSlno") or "").strip(),
    ]
    return "|".join(parts)


def _run_geocode_once(picked_j: dict):
    """
    실제 좌표 변환 수행 (한 번만)
    """
    lat, lon, juso_debug = juso_coord_search(picked_j)
    road_debug = {}
    parcel_debug = {}
    coord_source = ""

    if lat is not None and lon is not None:
        coord_source = "JUSO 좌표제공 API"
    else:
        addr_for_geo = st.session_state.get("selected_address", "")
        lat, lon, road_debug = vworld_geocode(addr_for_geo, "road")
        if lat is not None and lon is not None:
            coord_source = "VWorld 도로명"
        else:
            jibun_for_geo = st.session_state.get("selected_jibun", "")
            if jibun_for_geo:
                lat, lon, parcel_debug = vworld_geocode(jibun_for_geo, "parcel")
                if lat is not None and lon is not None:
                    coord_source = "VWorld 지번"
            else:
                parcel_debug = {
                    "error_code": "NO_JIBUN",
                    "error_text": "지번 주소가 없어 parcel 재시도를 하지 않았습니다."
                }

    st.session_state["geo_debug"] = {
        "juso_coord": juso_debug,
        "road": road_debug,
        "parcel": parcel_debug,
    }
    st.session_state["coord_source"] = coord_source
    st.session_state["auto_lat"] = lat
    st.session_state["auto_lon"] = lon

    if lat is not None and lon is not None:
        try:
            gid = latlon_to_grid_id_100m(float(lat), float(lon))
            st.session_state["auto_grid_id"] = gid
        except Exception as e:
            st.session_state["auto_grid_id"] = ""
            st.warning(f"좌표는 얻었지만 grid_id 계산 실패: {e}")
    else:
        st.session_state["auto_grid_id"] = ""


# =========================================================
# 페이지 본문
# =========================================================
def field_public_page(supabase):
    st.title("📝 소상공인 방범물품 지원 설문 (현장 접수)")

    st.session_state.setdefault("last_submit_ts", 0)
    st.session_state.setdefault("addr_candidates", [])
    st.session_state.setdefault("selected_address", "")
    st.session_state.setdefault("selected_jibun", "")
    st.session_state.setdefault("selected_zipno", "")
    st.session_state.setdefault("auto_lat", None)
    st.session_state.setdefault("auto_lon", None)
    st.session_state.setdefault("auto_grid_id", "")
    st.session_state.setdefault("geo_debug", {})
    st.session_state.setdefault("coord_source", "")
    st.session_state.setdefault("last_geo_request_key", "")

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

                # ✅ 새 검색 시 이전 좌표 상태 초기화
                st.session_state["selected_address"] = ""
                st.session_state["selected_jibun"] = ""
                st.session_state["selected_zipno"] = ""
                st.session_state["auto_lat"] = None
                st.session_state["auto_lon"] = None
                st.session_state["auto_grid_id"] = ""
                st.session_state["geo_debug"] = {}
                st.session_state["coord_source"] = ""
                st.session_state["last_geo_request_key"] = ""

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

        # ✅ 핵심 수정: 같은 주소에 대해 rerun마다 좌표 API를 다시 호출하지 않음
        current_geo_request_key = _make_geo_request_key(picked_j)
        last_geo_request_key = st.session_state.get("last_geo_request_key", "")

        if current_geo_request_key != last_geo_request_key:
            _run_geocode_once(picked_j)
            st.session_state["last_geo_request_key"] = current_geo_request_key

    selected_addr = st.session_state.get("selected_address", "").strip()
    auto_lat = st.session_state.get("auto_lat")
    auto_lon = st.session_state.get("auto_lon")
    auto_grid_id = st.session_state.get("auto_grid_id", "")
    coord_source = st.session_state.get("coord_source", "")

    if selected_addr:
        if auto_lat is not None and auto_lon is not None:
            st.success(
                f"좌표 변환 성공 ({coord_source}) : lat={auto_lat}, lon={auto_lon}, grid_id={auto_grid_id}"
            )
        else:
            st.error("주소 선택은 되었지만 좌표 변환이 실패했습니다. 아래 디버그를 확인해 주세요.")
            _render_geo_debug()

    st.divider()

    # ==================================================
    # 1) 설문 입력
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

    has_cctv = st.checkbox("매장 내 CCTV 보유 여부")
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

        if not selected_addr:
            st.error("주소 검색 후 결과에서 주소를 선택해야 합니다.")
            st.stop()

        lat = st.session_state.get("auto_lat")
        lon = st.session_state.get("auto_lon")
        if lat is None or lon is None:
            st.error("외부 좌표 변환 서비스 응답 실패로 저장할 수 없습니다. 잠시 후 다시 시도해 주세요.")
            _render_geo_debug()
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

        extra_block_lines = [
            "[추가설문]",
            f"업종={biz_type}",
            f"야간단독={night_alone}",
            f"주변환경={surroundings}",
            f"사각지대={blind_spot}",
            f"조명={lighting}",
            f"사설경비={security_status}",
            f"매장내CCTV={'있음' if has_cctv else '없음'}",
            f"비상벨보유={'있음' if has_emergency_bell else '없음'}",
            f"영업시간선택={biz_hours}",
        ]

        if biz_hours == "직접입력" and open_t and close_t:
            extra_block_lines.append(f"영업시간직접입력={open_t.strftime('%H:%M')}~{close_t.strftime('%H:%M')}")

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