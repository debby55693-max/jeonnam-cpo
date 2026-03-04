import json
import base64
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import requests
import streamlit as st
import pandas as pd

import folium
from folium.features import GeoJsonPopup, GeoJsonTooltip
from streamlit_folium import st_folium


# =============================
# 기본 유틸
# =============================
def _to_float(v):
    try:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip().replace(",", "")
            if s == "":
                return None
            return float(s)
        return float(v)
    except Exception:
        return None


def _to_int(v, default=0):
    try:
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        if pd.isna(v):
            return default
        return int(float(v))
    except Exception:
        return default


def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    for c in candidates:
        if c in df.columns:
            return c
    return None


def _extract_sigungu_key(station: Optional[str]) -> str:
    """
    '무안경찰서' -> '무안' / '목포경찰서' -> '목포'
    """
    if not station:
        return ""
    s = str(station).strip()
    s = s.replace("전라남도", "").replace("전남", "").strip()
    s = s.replace("경찰서", "").replace("경찰청", "").strip()
    return s.strip()


def _station_key_to_sigungu(station_key: str) -> str:
    """
    도시(목포/여수/순천/나주/광양)는 '시', 나머지는 '군'
    """
    if station_key in ["목포", "여수", "순천", "나주", "광양"]:
        return f"{station_key}시"
    return f"{station_key}군"


def _guess_sigungu_prop(props: Dict[str, Any]) -> str:
    return (
        props.get("SIG_KOR_NM")
        or props.get("sigungu")
        or props.get("SIGUNGU")
        or props.get("sggnm")
        or props.get("SGGNM")
        or props.get("adm_nm")
        or props.get("ADM_NM")
        or props.get("name")
        or props.get("NAME")
        or ""
    )


# =============================
# 경로/로더(배포 대응)
# =============================
def _find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(20):
        if (cur / "streamlit_app.py").exists() or (cur / "requirements.txt").exists() or (cur / "admin_app").exists():
            return cur
        cur = cur.parent
    return start.resolve().parents[2]


def _find_asset_or_data_path(rel_path: str) -> Optional[Path]:
    here = Path(__file__).resolve()
    root = _find_project_root(here)
    candidates = [
        root / "assets" / rel_path,
        root / "data" / rel_path,
        root / "admin_app" / "assets" / rel_path,
        root / "admin_app" / "data" / rel_path,
        root / "survey_app" / "assets" / rel_path,
        root / "survey_app" / "data" / rel_path,
        here.parents[1] / "assets" / rel_path,
        here.parents[1] / "data" / rel_path,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


@st.cache_data(show_spinner=False)
def _load_geojson_path(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _load_geojson_url(url: str) -> Optional[Dict[str, Any]]:
    try:
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def load_sigungu_geojson() -> Optional[Dict[str, Any]]:
    # 1) 로컬(assets/data) 우선
    p = _find_asset_or_data_path("jeonnam_sig.geojson")
    if p:
        gj = _load_geojson_path(str(p))
        if gj:
            return gj

    # 2) Streamlit Secrets URL
    for key in ("JEONNAM_SIG_GEOJSON_URL", "JEONNAM_SGG_GEOJSON_URL"):
        url = st.secrets.get(key)
        if url:
            gj = _load_geojson_url(url)
            if gj:
                return gj
    return None


def _png_to_data_uri(png_path: str) -> Optional[str]:
    p = Path(png_path)
    if not p.exists():
        return None
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


# =============================
# 핫스팟(위험도) 격자 로드
# =============================
@st.cache_data(show_spinner=False)
def _load_hotspot_geojson() -> Optional[Dict[str, Any]]:
    """
    hotspot_grids.geojson 파일을 배포/로컬 어디서든 찾기.
    찾으면 _loaded_from 키에 경로를 넣어서 디버깅 캡션에 표시.
    """
    here = Path(__file__).resolve()
    root = _find_project_root(here)

    candidates = [
        root / "output" / "hotspot_grids.geojson",
        root / "admin_app" / "output" / "hotspot_grids.geojson",
        root / "survey_app" / "output" / "hotspot_grids.geojson",
        here.parents[1] / "output" / "hotspot_grids.geojson",
        here.parents[2] / "output" / "hotspot_grids.geojson",
    ]

    for p in candidates:
        if p.exists():
            gj = _load_geojson_path(str(p))
            if gj and isinstance(gj, dict):
                gj["_loaded_from"] = str(p)
                return gj
    return None


def _feature_centroid_latlon(feature: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    try:
        geom = feature.get("geometry", {}) or {}
        if geom.get("type") != "Polygon":
            return None
        coords = geom.get("coordinates")
        if not coords or not coords[0]:
            return None
        ring = coords[0]
        lons = [pt[0] for pt in ring if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        lats = [pt[1] for pt in ring if isinstance(pt, (list, tuple)) and len(pt) >= 2]
        if not lons or not lats:
            return None
        return (float(sum(lats) / len(lats)), float(sum(lons) / len(lons)))
    except Exception:
        return None


def _get_hotspot_feature_by_grid_id(grid_id: str) -> Optional[Dict[str, Any]]:
    gj = _load_hotspot_geojson()
    if not gj:
        return None
    for ft in gj.get("features", []) or []:
        props = ft.get("properties", {}) or {}
        if str(props.get("grid_id", "")).strip() == str(grid_id).strip():
            return ft
    return None


# ✅ 시군별 상위 10%만 남기기(모바일 성능 핵심)
def _filter_top_percent_by_sigungu(features: List[Dict[str, Any]], top_ratio: float = 0.10) -> List[Dict[str, Any]]:
    if not features:
        return []

    groups: Dict[str, List[Dict[str, Any]]] = {}
    for ft in features:
        p = (ft.get("properties", {}) or {})
        sgg = str(p.get("sigungu", "") or "").strip()
        if not sgg:
            sgg = "UNKNOWN"
        groups.setdefault(sgg, []).append(ft)

    kept: List[Dict[str, Any]] = []

    def score_of(x):
        p = (x.get("properties", {}) or {})
        try:
            return float(p.get("need_score", 0) or 0)
        except Exception:
            return 0.0

    for sgg, fts in groups.items():
        fts_sorted = sorted(fts, key=score_of, reverse=True)
        n = len(fts_sorted)
        k = int(n * top_ratio)
        if k < 1:
            k = 1
        kept.extend(fts_sorted[:k])

    return kept


def _add_hotspot_grid_layer(m: folium.Map, station: Optional[str]):
    """
    🟧 위험도/핫스팟 격자 레이어
    - 관서(시군)로 필터
    - 시군별 상위 10%만 표시
    - 지도 아래 캡션으로 "왜 안 뜨는지" 원인 표시
    """
    gj = _load_hotspot_geojson()
    if not gj:
        st.caption("🟧 핫스팟 격자: hotspot_grids.geojson 로드 실패(파일 경로/배포 위치 확인 필요)")
        return

    feats = gj.get("features", []) or []
    loaded_from = gj.get("_loaded_from", "unknown")

    if not feats:
        st.caption(f"🟧 핫스팟 격자: features=0 (loaded_from={loaded_from})")
        return

    # ✅ 관서(시군) 필터: 완전일치 말고 포함 매칭(데이터 표기 흔들려도 잡히게)
    def _norm(s: str) -> str:
        return (str(s or "")
                .replace(" ", "")
                .replace("전라남도", "")
                .replace("전남", "")
                .strip())

    station_key = _extract_sigungu_key(station)  # 예: '광양'
    target_sigungu = _station_key_to_sigungu(station_key) if station_key else ""  # 예: '광양시'

    before_cnt = len(feats)

    if station_key:
        sk = _norm(station_key)
        ts = _norm(target_sigungu)

        filtered = []
        for ft in feats:
            p = ft.get("properties", {}) or {}
            sgg = _norm(p.get("sigungu", ""))

            # 1) '광양시' 포함, 2) '광양' 포함 둘 다 허용
            if (ts and ts in sgg) or (sk and sk in sgg):
                filtered.append(ft)

        # ✅ 필터가 0개면 -> 안전장치로 "필터 해제"
        if filtered:
            feats = filtered

    after_station_cnt = len(feats)

    # ✅ 시군별 상위 10%만
    feats = _filter_top_percent_by_sigungu(feats, top_ratio=0.10)
    after_top_cnt = len(feats)

    if not feats:
        st.caption(
            f"🟧 핫스팟 격자: 필터 후 0개 "
            f"(before={before_cnt}, after_station={after_station_cnt}, after_top10%={after_top_cnt}, loaded_from={loaded_from})"
        )
        return

    # ✅ 디버그 캡션(원인 진단용) — 문제 해결되면 원하면 제거 가능
    st.caption(
        f"🟧 핫스팟 격자 표시: {len(feats)}개 "
        f"(before={before_cnt}, after_station={after_station_cnt}, loaded_from={loaded_from})"
    )

    def style_function(feature):
        v = (feature.get("properties", {}) or {}).get("need_score", 0)
        try:
            v = float(v)
        except Exception:
            v = 0.0
        if v >= 80:
            fc = "#D94C00"
        elif v >= 60:
            fc = "#FF7A1A"
        elif v >= 40:
            fc = "#FFA65C"
        elif v >= 20:
            fc = "#FFC999"
        else:
            fc = "#FFE6CC"
        return {"fillColor": fc, "color": "#444444", "weight": 1, "fillOpacity": 0.35}

    # ✅ 가장 안전한 최소 툴팁(필드 누락으로 레이어가 죽는 것 방지)
    layer = folium.GeoJson(
        {"type": "FeatureCollection", "features": feats},
        name="🟧 핫스팟 격자(시군 상위10%)",
        style_function=style_function,
        tooltip=GeoJsonTooltip(fields=["grid_id", "need_score"], aliases=["grid", "필요도"], sticky=True),
    )
    layer.add_to(m)


def _add_selected_grid_highlight(m: folium.Map, grid_id: str):
    ft = _get_hotspot_feature_by_grid_id(grid_id)
    if not ft:
        return

    def style_hi(_):
        return {"fillOpacity": 0.0, "weight": 5, "color": "#00AAFF"}

    folium.GeoJson(ft, name="선택 격자", style_function=style_hi).add_to(m)


# =============================
# 메인 지도
# =============================
def map_page(station=None, shops_df: Optional[pd.DataFrame] = None):
    if shops_df is None:
        shops_df = pd.DataFrame()

    df0 = shops_df.copy()

    base_center_lat, base_center_lon, zoom = 34.816, 126.900, 10
    valid = pd.DataFrame()

    if not df0.empty:
        lat_col = _pick_col(df0, ["lat", "LAT", "latitude", "Latitude", "위도", "y", "Y"])
        lon_primary_col = _pick_col(df0, ["lon", "LON", "longitude", "Longitude"])
        lon_alt_col = _pick_col(df0, ["lng", "LNG", "경도", "x", "X"])

        if lat_col and (lon_primary_col or lon_alt_col):
            df = df0.copy()
            df["__lat"] = df[lat_col].apply(_to_float)
            if lon_primary_col is not None:
                df["__lon"] = df[lon_primary_col].apply(_to_float)
                if lon_alt_col is not None:
                    df["__lon"] = df["__lon"].fillna(df[lon_alt_col].apply(_to_float))
            else:
                df["__lon"] = df[lon_alt_col].apply(_to_float)

            valid = df.dropna(subset=["__lat", "__lon"]).copy()
            if not valid.empty:
                base_center_lat = float(valid["__lat"].mean())
                base_center_lon = float(valid["__lon"].mean())
                zoom = 12

    sel_grid = st.session_state.get("selected_grid_id")
    sel_id = st.session_state.get("selected_shop_id")

    center_lat, center_lon = base_center_lat, base_center_lon

    if sel_id and (not valid.empty) and ("id" in valid.columns):
        hit = valid[valid["id"].astype(str) == str(sel_id)]
        if not hit.empty:
            center_lat = float(hit.iloc[0]["__lat"])
            center_lon = float(hit.iloc[0]["__lon"])
            zoom = 16
    elif sel_grid:
        ft = _get_hotspot_feature_by_grid_id(str(sel_grid))
        if ft:
            cen = _feature_centroid_latlon(ft)
            if cen:
                center_lat, center_lon = cen
                zoom = 16

    # ✅ prefer_canvas=True: 모바일 렌더 성능 개선
    m = folium.Map(location=[center_lat, center_lon], zoom_start=zoom, control_scale=True, prefer_canvas=True)

    # ✅ 시군 경계
    gj = load_sigungu_geojson()
    if gj is not None:
        gj_filtered = gj
        station_key = _extract_sigungu_key(station)
        if station_key:
            filtered = []
            target = station_key
            for feature in gj.get("features", []) or []:
                props = feature.get("properties", {}) or {}
                nm = _guess_sigungu_prop(props)
                if nm and (target in str(nm)):
                    filtered.append(feature)
            if filtered:
                gj_filtered = {"type": "FeatureCollection", "features": filtered}

        folium.GeoJson(
            gj_filtered,
            name="시군경계",
            style_function=lambda _: {"fillOpacity": 0.03, "weight": 6, "color": "#000000"},
        ).add_to(m)

    # ✅ 🟧 핫스팟/위험도 격자(시군 상위 10%)
    _add_hotspot_grid_layer(m, station)

    # ✅ 선택 격자 강조
    if sel_grid:
        _add_selected_grid_highlight(m, str(sel_grid))

    # ✅ 점포 마커(원래 방식 유지)
    if not valid.empty:
        default_icon = _find_asset_or_data_path("icons/shop_default.png")
        gold_icon = _find_asset_or_data_path("icons/shop_gold.png")
        silver_icon = _find_asset_or_data_path("icons/shop_silver.png")
        bronze_icon = _find_asset_or_data_path("icons/shop_bronze.png")

        def make_icon(path: Optional[Path], size: int):
            if not path:
                return None
            uri = _png_to_data_uri(str(path))
            if not uri:
                return None
            try:
                return folium.CustomIcon(uri, icon_size=(size, size), icon_anchor=(size // 2, size // 2))
            except Exception:
                return None

        for _, r in valid.iterrows():
            name = str(r.get("shop_name", "") or "")
            addr = str(r.get("address", "") or "")
            lat = float(r["__lat"])
            lon = float(r["__lon"])
            rank = _to_int(r.get("priority_rank"), 999)

            if rank == 1:
                icon_use = make_icon(gold_icon, 56)
            elif rank == 2:
                icon_use = make_icon(silver_icon, 54)
            elif rank == 3:
                icon_use = make_icon(bronze_icon, 52)
            else:
                icon_use = make_icon(default_icon, 46)

            popup_html = f"<b>{name}</b><br/>{addr}<br/>순위: {rank}"

            folium.Marker(
                location=[lat, lon],
                icon=icon_use,
                tooltip=name if name else None,
                popup=folium.Popup(popup_html, max_width=320),
                z_index_offset=10000,
            ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    map_state = st_folium(
        m,
        height=520,
        width=None,
        key=f"shops_map_{sel_id or sel_grid or 'init'}",
    )

    # ✅ 격자 클릭 → grid_id 추출
    try:
        if isinstance(map_state, dict):
            popup_txt = str(map_state.get("last_object_clicked_popup") or "")
            tip_txt = str(map_state.get("last_object_clicked_tooltip") or "")
            combined = f"{popup_txt} {tip_txt}"

            m_gid = re.search(r"([가-힣]{2}\d{6})", combined)
            if m_gid:
                clicked_gid = m_gid.group(1)
                if str(st.session_state.get("selected_grid_id") or "") != str(clicked_gid):
                    st.session_state["selected_grid_id"] = str(clicked_gid)
                    st.session_state["selected_shop_id"] = None
                    st.rerun()
    except Exception:
        pass