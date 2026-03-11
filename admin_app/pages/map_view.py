import json
import base64
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

import requests
import streamlit as st
import pandas as pd

import folium
from folium.features import GeoJsonTooltip
from streamlit_folium import st_folium


# =============================
# 설정
# =============================
DEBUG = False  # True면 캡션 디버그 표시


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


def _norm(s: str) -> str:
    return (
        str(s or "")
        .replace(" ", "")
        .replace("전라남도", "")
        .replace("전남", "")
        .strip()
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


def _filter_hotspot_by_station(features: List[Dict[str, Any]], station: Optional[str]) -> List[Dict[str, Any]]:
    """
    hotspot features를 관서(시군) 기준으로 필터
    - 포함 매칭
    - 0개면 안전장치로 필터 해제
    """
    if not features:
        return []
    station_key = _extract_sigungu_key(station)
    if not station_key:
        return features

    target_sigungu = _station_key_to_sigungu(station_key)
    sk = _norm(station_key)
    ts = _norm(target_sigungu)

    filtered = []
    for ft in features:
        p = ft.get("properties", {}) or {}
        sgg = _norm(p.get("sigungu", ""))
        if (ts and ts in sgg) or (sk and sk in sgg):
            filtered.append(ft)

    return filtered if filtered else features


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

    for _, fts in groups.items():
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
    - need_score에 따라 빨강 농도 차등 표시
    """
    gj = _load_hotspot_geojson()
    if not gj:
        if DEBUG:
            st.caption("🟧 핫스팟 격자: hotspot_grids.geojson 로드 실패")
        return

    feats = gj.get("features", []) or []
    if not feats:
        return

    feats = _filter_hotspot_by_station(feats, station)
    feats = _filter_top_percent_by_sigungu(feats, top_ratio=0.10)
    if not feats:
        return

    scores = []
    for ft in feats:
        p = ft.setdefault("properties", {})
        if "grid_id" not in p:
            p["grid_id"] = ""
        try:
            s = float(p.get("need_score", 0) or 0)
        except Exception:
            s = 0.0
        p["need_score"] = s
        scores.append(s)

    min_score = min(scores) if scores else 0.0
    max_score = max(scores) if scores else 1.0
    span = (max_score - min_score) if (max_score - min_score) > 0 else 1.0

    def _score_to_color(v: float) -> str:
        try:
            ratio = (float(v) - min_score) / span
        except Exception:
            ratio = 0.0
        ratio = max(0.0, min(1.0, ratio))

        light = (255, 235, 238)
        dark = (183, 28, 28)
        r = int(light[0] + (dark[0] - light[0]) * ratio)
        g = int(light[1] + (dark[1] - light[1]) * ratio)
        b = int(light[2] + (dark[2] - light[2]) * ratio)
        return f"#{r:02X}{g:02X}{b:02X}"

    def style_function(feature):
        v = (feature.get("properties", {}) or {}).get("need_score", 0)
        return {
            "fillColor": _score_to_color(v),
            "color": "#8B1E1E",
            "weight": 1,
            "fillOpacity": 0.55,
        }

    folium.GeoJson(
        {"type": "FeatureCollection", "features": feats},
        name="🟧 집중관리 우선점포 격자",
        style_function=style_function,
        highlight_function=lambda _: {"weight": 2, "color": "#5A0F0F", "fillOpacity": 0.65},
    ).add_to(m)


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
            clicked_gid = None

            active = map_state.get("last_active_drawing") or {}
            if isinstance(active, dict):
                props = active.get("properties") or {}
                if isinstance(props, dict):
                    clicked_gid = str(props.get("grid_id") or "").strip() or None

            if not clicked_gid:
                popup_txt = str(map_state.get("last_object_clicked_popup") or "")
                tip_txt = str(map_state.get("last_object_clicked_tooltip") or "")
                combined = f"{popup_txt} {tip_txt}"
                m_gid = re.search(r"([가-힣]{2}\d{6})", combined)
                if m_gid:
                    clicked_gid = m_gid.group(1)

            if clicked_gid and str(st.session_state.get("selected_grid_id") or "") != str(clicked_gid):
                st.session_state["selected_grid_id"] = str(clicked_gid)
                st.session_state["selected_shop_id"] = None
                st.rerun()
    except Exception:
        pass

    return map_state