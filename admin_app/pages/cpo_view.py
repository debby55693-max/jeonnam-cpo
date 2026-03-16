import json
import streamlit as st
import pandas as pd
from datetime import datetime
import re
import inspect
from pathlib import Path
from typing import Optional
from io import BytesIO
import hashlib
import time
import math

from pages.map_view import map_page


# -----------------------------
# map_page 안전 호출 유틸
# -----------------------------
def call_map_page(**kwargs):
    try:
        sig = inspect.signature(map_page)
        allowed = set(sig.parameters.keys())
        filtered = {k: v for k, v in kwargs.items() if k in allowed}
        return map_page(**filtered)
    except TypeError:
        return map_page()
    except Exception:
        return map_page()


# -----------------------------
# 유틸
# -----------------------------
def safe_int(v, default=0):
    try:
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        if pd.isna(v):
            return default
        return int(float(v))
    except:
        return default


def safe_float(v, default=0.0):
    try:
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        if pd.isna(v):
            return default
        return float(v)
    except:
        return default


def safe_str(v, default=""):
    try:
        if v is None:
            return default
        if isinstance(v, float) and pd.isna(v):
            return default
        if pd.isna(v):
            return default
        return str(v)
    except:
        return default


def safe_bool(v, default=False):
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = str(v).strip().lower()
        if s in ["true", "1", "y", "yes", "예", "있음"]:
            return True
        if s in ["false", "0", "n", "no", "아니오", "없음", ""]:
            return False
        return default
    except:
        return default


def clean_phone(phone: str) -> str:
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("010"):
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return digits


def pick_current_score(shop_row: dict, default: int = 50) -> int:
    """
    perceived_safety가 0이어도 정상값으로 인정해야 해서 'or' 금지.
    """
    if shop_row.get("perceived_safety") is not None:
        return safe_int(shop_row.get("perceived_safety"), default)
    if shop_row.get("subjective_score") is not None:
        return safe_int(shop_row.get("subjective_score"), default)
    if shop_row.get("safety_score") is not None:
        return safe_int(shop_row.get("safety_score"), default)
    return default


# -----------------------------
# 다운로드/리스트 유틸
# -----------------------------
def _gid_key(gid: str) -> str:
    h = hashlib.md5(str(gid).encode("utf-8")).hexdigest()[:10]
    return f"gid_{h}"


def df_to_xlsx_bytes_safe(df: pd.DataFrame) -> Optional[bytes]:
    """openpyxl 없으면 None 반환 -> CSV로 대체"""
    try:
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="list")
        return output.getvalue()
    except Exception:
        return None


def _fetch_grid_store_list(supabase, grid_id: str) -> tuple[pd.DataFrame, str]:
    """
    ✅ 원천 점포리스트(biz_stores) 우선
    ✅ 없으면 설문등록점포(shops) fallback
    """
    gid = str(grid_id).strip()

    # 1) biz_stores(원천) 시도
    try:
        data = (
            supabase.table("biz_stores")
            .select("*")
            .eq("grid_id", gid)
            .limit(20000)
            .execute()
            .data
            or []
        )
        if data:
            df = pd.DataFrame(data)
            return df, "biz_stores"
        return pd.DataFrame(), "biz_stores"
    except Exception:
        pass

    # 2) shops(설문등록) fallback
    try:
        data = (
            supabase.table("shops")
            .select("id, station, grid_id, shop_name, address, phone, tel, owner_phone, lat, lon, updated_at")
            .eq("grid_id", gid)
            .limit(20000)
            .execute()
            .data
            or []
        )
        return (pd.DataFrame(data) if data else pd.DataFrame()), "shops"
    except Exception:
        return pd.DataFrame(), "none"


def _normalize_store_df(df: pd.DataFrame, grid_id: str, station: str, source: str) -> pd.DataFrame:
    """
    다운로드용 표준 컬럼: 점포명/주소/전화 (+그리드ID)
    ✅ pandas index 정렬로 '관서/그리드ID'가 NaN 되는 현상 방지
    """
    grid_id = ("" if grid_id is None else str(grid_id)).strip()

    if df is None or df.empty:
        return pd.DataFrame([{
            "관서": station or "",
            "그리드ID": grid_id,
            "점포명": "",
            "주소": "",
            "전화": "",
            "방문여부(Y/N)": "",
            "담당자": "",
            "비고": f"source={source}",
        }])

    def pick(cands):
        for c in cands:
            if c in df.columns:
                return c
        return None

    name_col = pick(["store_name", "shop_name", "name", "bizesNm", "상호명", "점포명"])
    addr_col = pick(["address", "rdnmAdr", "lnoAdr", "addr", "도로명주소", "지번주소"])
    phone_col = pick(["phone", "tel", "owner_phone", "전화번호"])
    cat_col = pick(["category", "업종", "indsLclsNm", "indsMclsNm", "indsSclsNm"])

    out = pd.DataFrame(index=df.index)

    out["관서"] = station or ""
    out["그리드ID"] = grid_id
    out["점포명"] = df[name_col].astype(str) if name_col else ""
    out["주소"] = df[addr_col].astype(str) if addr_col else ""

    if cat_col:
        out["업종"] = df[cat_col].astype(str)

    out["전화"] = df[phone_col].apply(lambda x: clean_phone(safe_str(x, ""))) if phone_col else ""
    out["방문여부(Y/N)"] = ""
    out["담당자"] = ""
    out["비고"] = f"source={source}"

    return out.reset_index(drop=True)


def _cell(text, selected=False, bold=False, align="left"):
    t = "" if text is None else str(text)
    if bold:
        t = f"<b>{t}</b>"
    if selected:
        return f"<div style='background:#FFF4CC; padding:6px 8px; border-radius:10px; text-align:{align};'>{t}</div>"
    return f"<div style='padding:6px 8px; text-align:{align};'>{t}</div>"


# -------------------------
# 핫스팟 격자 TOP 목록 유틸
# -------------------------
def _find_project_root(start: Path) -> Path:
    cur = start.resolve()
    for _ in range(20):
        if (cur / "streamlit_app.py").exists() or (cur / "requirements.txt").exists() or (cur / "admin_app").exists():
            return cur
        cur = cur.parent
    return start.resolve().parents[1]


def _find_output_file(rel_name: str) -> Optional[Path]:
    here = Path(__file__).resolve()
    root = _find_project_root(here)
    for p in [
        root / "output" / rel_name,
        root / "admin_app" / "output" / rel_name,
        root / "survey_app" / "output" / rel_name,
        here.parents[1] / "output" / rel_name,
        here.parents[2] / "output" / rel_name,
    ]:
        if p.exists():
            return p
    return None


def _extract_station_key(station: str) -> str:
    s = (station or "").strip()
    s = s.replace("전라남도", "").replace("전남", "").strip()
    s = s.replace("경찰서", "").replace("경찰청", "").strip()
    s = s.replace("군", "").replace("시", "").strip()
    return s


def _station_key_to_sigungu(station_key: str) -> str:
    if station_key in ["목포", "여수", "순천", "나주", "광양"]:
        return f"{station_key}시"
    return f"{station_key}군"


def _gid_str(x) -> str:
    return "" if pd.isna(x) else str(x).strip()


def _find_feat_props_by_gid(features: list, gid: str) -> Optional[dict]:
    gid = str(gid).strip()
    for ft in features or []:
        p = (ft.get("properties", {}) or {})
        if str(p.get("grid_id", "")).strip() == gid:
            return p
    return None


def _build_top10pct_grid_df(gdf: pd.DataFrame, station_key: str = "", top_ratio: float = 0.10) -> pd.DataFrame:
    if gdf is None or gdf.empty:
        return pd.DataFrame()

    work = gdf.copy()
    work["grid_id"] = work["grid_id"].apply(_gid_str)
    work = work[work["grid_id"] != ""].copy()
    work["need_score"] = pd.to_numeric(work["need_score"], errors="coerce")
    work = work.dropna(subset=["need_score"]).copy()
    if work.empty:
        return pd.DataFrame()

    if station_key:
        target_sigungu = _station_key_to_sigungu(station_key)
        work = work[work["sigungu"].astype(str).str.strip() == target_sigungu].copy()
        if work.empty:
            return pd.DataFrame()
        k = max(1, math.ceil(len(work) * top_ratio))
        return work.sort_values(["need_score", "grid_id"], ascending=[False, True]).head(k).reset_index(drop=True)

    selected = []
    for sigungu, group in work.groupby("sigungu", dropna=False):
        group = group.copy()
        if str(sigungu or "").strip() == "":
            continue
        k = max(1, math.ceil(len(group) * top_ratio))
        selected.append(
            group.sort_values(["need_score", "grid_id"], ascending=[False, True]).head(k)
        )

    if not selected:
        return pd.DataFrame()

    out = pd.concat(selected, ignore_index=True)
    out = out.sort_values(["need_score", "sigungu", "grid_id"], ascending=[False, True, True]).reset_index(drop=True)
    return out


# -----------------------------
# ✅ 다운로드 기준 점포수(DB 카운트) - 세션 캐시
# -----------------------------
def _get_store_count_download_basis(supabase, gid: str, ttl_sec: int = 300) -> int:
    gid = str(gid).strip()
    cache = st.session_state.setdefault("__store_cnt_cache", {})
    now = time.time()

    hit = cache.get(gid)
    if hit and (now - hit.get("ts", 0) < ttl_sec):
        return int(hit.get("cnt", 0))

    cnt = 0
    try:
        res = (
            supabase.table("biz_stores")
            .select("grid_id", count="exact")
            .eq("grid_id", gid)
            .limit(1)
            .execute()
        )
        cnt = getattr(res, "count", None)
        if cnt is None:
            data = (res.data or [])
            cnt = len(data)
        cnt = int(cnt)
    except Exception:
        cnt = 0

    cache[gid] = {"cnt": cnt, "ts": now}
    return cnt


# =========================================================
# CPO 화면
# =========================================================
def cpo_page(supabase, station: str, role: str):
    st.title("🗂️ CPO 관리 (우선순위 / 설문 수정 / 점수 정보 / 진단)")

    try:
        qp = dict(st.query_params)
    except Exception:
        qp = st.experimental_get_query_params()

    move_shop = qp.get("move_shop")
    if isinstance(move_shop, list):
        move_shop = move_shop[0] if move_shop else None

    if move_shop:
        st.session_state["selected_shop_id"] = str(move_shop)
        st.session_state["selected_grid_id"] = None
        st.session_state["MV_FAST_MODE"] = True
        try:
            st.query_params.clear()
        except Exception:
            st.experimental_set_query_params()
        st.rerun()

    # shops 로드
    try:
        q = supabase.table("shops").select("*").order("updated_at", desc=True)
        if role == "cpo" and station:
            q = q.eq("station", station)
        shops = q.execute().data or []
    except Exception as e:
        st.error(f"점포 로드 실패: {e}")
        shops = []

    shops_df = pd.DataFrame(shops) if shops else pd.DataFrame()

    # ranked 뷰 로드
    try:
        qv = supabase.table("v_shops_priority_ranked").select("*")
        if station:
            qv = qv.eq("station", station)
        ranked = qv.execute().data or []
    except Exception:
        ranked = []

    ranked_df = pd.DataFrame(ranked) if ranked else pd.DataFrame()

    # 지도용 DF
    map_df = shops_df.copy()
    if (not ranked_df.empty) and (not map_df.empty) and ("id" in ranked_df.columns) and ("id" in map_df.columns):
        keep = [c for c in ["id", "priority_rank", "priority_score", "cnt_patrol", "grid_id"] if c in ranked_df.columns]
        if keep:
            map_df = map_df.merge(ranked_df[keep], on="id", how="left", suffixes=("_shop", "_view"))
            if "cnt_patrol_view" in map_df.columns:
                map_df["cnt_patrol"] = map_df["cnt_patrol_view"].fillna(map_df.get("cnt_patrol_shop"))
            if "grid_id_view" in map_df.columns:
                map_df["grid_id"] = map_df["grid_id_view"].fillna(map_df.get("grid_id_shop"))
            if "priority_rank" not in map_df.columns and "priority_rank_view" in map_df.columns:
                map_df["priority_rank"] = map_df["priority_rank_view"]

    # 지도
    st.subheader("🗺️ 지도")
    if shops_df.empty:
        st.info("등록된 점포(설문)가 없어도 지도/시군경계/핫스팟 격자는 표시됩니다.")
    call_map_page(station=station, shops_df=map_df)

    st.divider()

    # =========================================================
    # 집중관리 우선점포
    # =========================================================
    st.subheader("🟧 집중관리 우선점포")

    station_key = _extract_station_key(station)
    sel_grid = st.session_state.get("selected_grid_id")

    hot_path = _find_output_file("hotspot_grids.geojson")
    feats = []
    if hot_path:
        try:
            with open(hot_path, "r", encoding="utf-8") as f:
                hot = json.load(f)
            feats = hot.get("features", []) or []
        except Exception:
            feats = []

    if feats and station_key:
        target = _station_key_to_sigungu(station_key)
        feats = [ft for ft in feats if (ft.get("properties", {}) or {}).get("sigungu") == target]

    # 1) 선택 격자 패널
    if sel_grid:
        st.markdown("### 📌 선택 격자(지도 클릭)")
        p = _find_feat_props_by_gid(feats, sel_grid) if feats else None

        raw_df, sel_src = _fetch_grid_store_list(supabase, str(sel_grid))
        dl_cnt = len(raw_df) if raw_df is not None else 0

        sel_out_df = _normalize_store_df(raw_df, str(sel_grid), station, sel_src)
        sel_xlsx = df_to_xlsx_bytes_safe(sel_out_df)
        sel_csv = sel_out_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        need = safe_float(p.get("need_score"), None) if p else None
        info = None
        if p:
            info = (
                f"점포 {dl_cnt} | "
                f"112 {safe_int(p.get('cnt_112'), 0)} | "
                f"5대 {safe_int(p.get('cnt_5crime'), 0)} | "
                f"CCTV {safe_int(p.get('cnt_cctv'), 0)} | "
                f"순찰 {safe_int(p.get('cnt_patrol'), 0)}"
            )

        cA, cB, cC = st.columns([3, 5, 2])
        with cA:
            st.markdown(_cell(str(sel_grid), selected=True, bold=True), unsafe_allow_html=True)
        with cB:
            st.markdown(
                _cell(
                    (f"need_score {need:.2f} / {info}" if (need is not None and info) else f"점포 {dl_cnt} (다운로드 기준)"),
                    selected=True
                ),
                unsafe_allow_html=True
            )
        with cC:
            if sel_xlsx:
                st.download_button(
                    "⬇ 선택 격자 다운",
                    data=sel_xlsx,
                    file_name=f"{station_key or '전체'}_{str(sel_grid)}_점포리스트.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_sel_panel_x_{str(sel_grid)}",
                    use_container_width=True,
                )
            else:
                st.download_button(
                    "⬇ 선택 격자 다운",
                    data=sel_csv,
                    file_name=f"{station_key or '전체'}_{str(sel_grid)}_점포리스트.csv",
                    mime="text/csv",
                    key=f"dl_sel_panel_c_{str(sel_grid)}",
                    use_container_width=True,
                )

        st.caption(f"다운로드 원천: {sel_src}")
        st.divider()

    # 2) TOP10 목록 + 체크 합본 다운로드
    if not hot_path or not feats:
        st.caption("hotspot_grids.geojson 파일이 없습니다. (tools/make_hotspot_geojson.py 실행 필요)")
    else:
        rows = []
        for ft in feats:
            p = ft.get("properties", {}) or {}
            rows.append({
                "grid_id": p.get("grid_id"),
                "sigungu": p.get("sigungu"),
                "need_score": p.get("need_score"),
                "cnt_store": p.get("cnt_store"),
                "cnt_112": p.get("cnt_112"),
                "cnt_5crime": p.get("cnt_5crime"),
                "cnt_cctv": p.get("cnt_cctv"),
                "cnt_patrol": p.get("cnt_patrol"),
            })

        gdf = pd.DataFrame(rows)
        if gdf.empty:
            st.info("표시할 격자 우선순위 데이터가 없습니다.")
        else:
            gdf_top = _build_top10pct_grid_df(gdf, station_key=station_key, top_ratio=0.10)
            top_gids = gdf_top["grid_id"].tolist()
            store_cnt_map = {gid: _get_store_count_download_basis(supabase, gid) for gid in top_gids}

            if sel_grid and str(sel_grid).strip() in top_gids:
                k = f"chk_{_gid_key(str(sel_grid).strip())}"
                if k not in st.session_state:
                    st.session_state[k] = True

            def _toggle_all():
                v = st.session_state.get("chk_all_top10", False)
                for gid in top_gids:
                    st.session_state[f"chk_{_gid_key(gid)}"] = v

            if "chk_all_top10" not in st.session_state:
                st.session_state["chk_all_top10"] = all(
                    st.session_state.get(f"chk_{_gid_key(gid)}", False) for gid in top_gids
                )

            checked_gids = [gid for gid in top_gids if st.session_state.get(f"chk_{_gid_key(gid)}", False)]

            combined_df = None
            combined_xlsx = None
            combined_csv = None
            if checked_gids:
                frames = []
                for gid in checked_gids:
                    raw_df, src = _fetch_grid_store_list(supabase, gid)
                    frames.append(_normalize_store_df(raw_df, gid, station, src))
                combined_df = pd.concat(frames, ignore_index=True)
                combined_xlsx = df_to_xlsx_bytes_safe(combined_df)
                combined_csv = combined_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

            sel_hash = hashlib.md5(("|".join(checked_gids)).encode("utf-8")).hexdigest()[:8]

            h = st.columns([1.0, 2.6, 1.3, 3.2, 1.4, 0.6])
            with h[-2]:
                if combined_df is not None:
                    if combined_xlsx:
                        st.download_button(
                            "점포리스트 다운",
                            data=combined_xlsx,
                            file_name=f"{station_key or '전체'}_선택그리드_점포리스트.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_selected_xlsx_{sel_hash}",
                            use_container_width=True,
                        )
                    else:
                        st.download_button(
                            "점포리스트 다운",
                            data=combined_csv,
                            file_name=f"{station_key or '전체'}_선택그리드_점포리스트.csv",
                            mime="text/csv",
                            key=f"dl_selected_csv_{sel_hash}",
                            use_container_width=True,
                        )
                else:
                    st.caption("체크 후 다운로드")
            with h[-1]:
                st.checkbox("", key="chk_all_top10", on_change=_toggle_all, label_visibility="collapsed")

            st.caption(f"현재 선택 기준 상위 10% 격자 {len(top_gids)}개 — (체크 {len(checked_gids)}개)")

            for i, r in gdf_top.iterrows():
                grid_id_str = _gid_str(r.get("grid_id"))
                is_sel = (str(sel_grid or "").strip() == grid_id_str)

                need = r.get("need_score")
                need_txt = f"{float(need):.2f}" if need == need else str(need)

                dl_cnt = int(store_cnt_map.get(grid_id_str, 0))

                info = (
                    f"점포 {dl_cnt} | "
                    f"112 {safe_int(r.get('cnt_112'), 0)} | "
                    f"5대 {safe_int(r.get('cnt_5crime'), 0)} | "
                    f"CCTV {safe_int(r.get('cnt_cctv'), 0)} | "
                    f"순찰 {safe_int(r.get('cnt_patrol'), 0)}"
                )

                c1, c2, c3, c4, c5, c6 = st.columns([1.0, 2.6, 1.3, 3.2, 1.4, 0.6])

                with c1:
                    st.markdown(_cell(f"#{i+1}", selected=is_sel), unsafe_allow_html=True)
                with c2:
                    st.markdown(_cell(grid_id_str, selected=is_sel, bold=is_sel), unsafe_allow_html=True)
                with c3:
                    st.markdown(_cell(need_txt, selected=is_sel, align="right"), unsafe_allow_html=True)
                with c4:
                    st.markdown(_cell(info, selected=is_sel), unsafe_allow_html=True)

                with c5:
                    if st.button("📍 이동", key=f"move_{grid_id_str}_{i}"):
                        st.session_state["selected_grid_id"] = grid_id_str
                        st.session_state["selected_shop_id"] = None
                        st.session_state[f"chk_{_gid_key(grid_id_str)}"] = True
                        st.session_state["MV_FAST_MODE"] = True
                        st.rerun()

                with c6:
                    st.checkbox("", key=f"chk_{_gid_key(grid_id_str)}", label_visibility="collapsed")

    # 기존 return 제거
    if shops_df.empty:
        st.caption("※ 현재 관서에 등록된 설문 점포가 없어 일부 연계 기능은 제한될 수 있습니다.")

    # =========================================================
    # TOP5
    # =========================================================
    st.subheader("🏆 우선순위 TOP5")

    if not ranked_df.empty:
        if "priority_rank" in ranked_df.columns and ranked_df["priority_rank"].notna().any():
            top = ranked_df.dropna(subset=["priority_rank"]).sort_values(["priority_rank"]).head(5).copy()
        elif "priority_score" in ranked_df.columns:
            top = ranked_df.sort_values(["priority_score"], ascending=False).head(5).copy()
            top["priority_rank"] = range(1, len(top) + 1)
        else:
            top = ranked_df.head(5).copy()
            top["priority_rank"] = range(1, len(top) + 1)

        for i, r in top.reset_index(drop=True).iterrows():
            shop_id = r.get("id")

            rank = safe_int(r.get("priority_rank"), 0)
            station_name = safe_str(r.get("station"), "")
            shop_name = safe_str(r.get("shop_name"), "")
            score = safe_float(r.get("priority_score"), 0.0)

            c1, c2, c3, c4 = st.columns([0.9, 5.5, 1.2, 1.6], vertical_alignment="center")
            with c1:
                st.markdown(f"**#{rank}**")
            with c2:
                st.markdown(f"**{station_name}** · {shop_name}")
            with c3:
                st.markdown(f"**{score:.1f}**")
            with c4:
                if st.button("📍 이동", key=f"top_move_{shop_id}_{i}", use_container_width=True):
                    st.session_state["selected_shop_id"] = str(shop_id)
                    st.session_state["selected_grid_id"] = None
                    st.session_state["MV_FAST_MODE"] = True
                    st.rerun()
    else:
        st.info("TOP5를 표시할 데이터가 없습니다. (v_shops_priority_ranked 확인)")

    st.divider()

    # =========================================================
    # 전체 현황표
    # =========================================================
    st.subheader("📋 전체 현황표")

    if ranked_df.empty:
        st.info("현황표 데이터가 없습니다.")
    else:
        officers = pd.DataFrame()
        cols = [c for c in ["id", "officer_rank", "officer_name"] if c in shops_df.columns]
        if cols:
            officers = shops_df[cols].copy()

        view_df = ranked_df.copy()
        if not officers.empty and "id" in view_df.columns:
            view_df = view_df.merge(officers, on="id", how="left", suffixes=("", "_shop"))

        want_cols = [
            "priority_rank", "station", "shop_name", "address",
            "grid_id",
            "priority_score", "cpo_score", "resident_adj", "env_score",
            "grid_risk", "cnt_112", "cnt_cctv", "cnt_patrol",
            "uses_security_company", "has_emergency_bell", "has_cctv",
            "other_security", "cpo_comment",
            "officer_rank", "officer_name",
            "updated_at"
        ]
        cols2 = [c for c in want_cols if c in view_df.columns]

        view_df = view_df.reset_index(drop=True)
        show = view_df[cols2].copy()

        rename = {
            "priority_rank": "순위",
            "station": "관서",
            "shop_name": "점포명",
            "priority_score": "최종점수(100점)",
            "cpo_score": "CPO점수(50%)",
            "resident_adj": "주관점수(30%)",
            "env_score": "환경점수(20%)",
            "grid_risk": "위험도",
            "cnt_112": "112신고",
            "cnt_cctv": "CCTV",
            "cnt_patrol": "탄력순찰",
            "uses_security_company": "보안업체이용",
            "has_emergency_bell": "점포비상벨보유",
            "has_cctv": "점포CCTV보유",
            "other_security": "기타보안시설",
            "cpo_comment": "CPO의견",
            "officer_rank": "계급",
            "officer_name": "성명",
        }

        display_df = show.rename(columns=rename)

        try:
            ev = st.dataframe(
                display_df,
                use_container_width=True,
                height=420,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key="rank_table",
            )
            try:
                if ev.selection.rows:
                    idx = ev.selection.rows[0]
                    if "id" in view_df.columns:
                        st.session_state["selected_shop_id"] = str(view_df.iloc[idx]["id"])
                        st.session_state["selected_grid_id"] = None
                        st.session_state["MV_FAST_MODE"] = True
            except Exception:
                pass

        except TypeError:
            st.dataframe(display_df, use_container_width=True, height=420, hide_index=True)
            st.caption("※ 표 클릭으로 지도 이동 기능은 Streamlit 최신 버전에서만 동작합니다.")

    st.divider()

    # =========================================================
    # 설문 수정 / 삭제 (복원)
    # =========================================================
    st.subheader("✏️ 설문 수정 / 삭제")

    if shops_df.empty:
        st.info("수정/삭제할 설문 점포가 없습니다.")
        return

    edit_df = shops_df.copy().reset_index(drop=True)
    edit_df["__id_str__"] = edit_df["id"].astype(str)

    sort_cols = [c for c in ["updated_at"] if c in edit_df.columns]
    if sort_cols:
        try:
            edit_df = edit_df.sort_values(sort_cols, ascending=False).reset_index(drop=True)
        except Exception:
            pass

    option_ids = edit_df["__id_str__"].tolist()
    selected_shop_id = str(st.session_state.get("selected_shop_id") or "")

    if selected_shop_id not in option_ids:
        selected_shop_id = option_ids[0]
        st.session_state["selected_shop_id"] = selected_shop_id

    def _shop_label(shop_id_str: str) -> str:
        try:
            row = edit_df[edit_df["__id_str__"] == shop_id_str].iloc[0].to_dict()
            return f"{safe_str(row.get('station'))} · {safe_str(row.get('shop_name'))} · {safe_str(row.get('address'))}"
        except Exception:
            return shop_id_str

    selected_shop_id = st.selectbox(
        "수정할 점포 선택",
        options=option_ids,
        index=option_ids.index(selected_shop_id),
        format_func=_shop_label,
        key="edit_shop_selectbox",
    )
    st.session_state["selected_shop_id"] = str(selected_shop_id)

    selected_rows = edit_df[edit_df["__id_str__"] == str(selected_shop_id)]
    if selected_rows.empty:
        st.warning("선택한 점포 정보를 찾을 수 없습니다.")
        return

    shop_row = selected_rows.iloc[0].to_dict()

    info1, info2, info3 = st.columns(3)
    with info1:
        st.caption("관서")
        st.write(safe_str(shop_row.get("station"), "-"))
    with info2:
        st.caption("그리드ID")
        st.write(safe_str(shop_row.get("grid_id"), "-"))
    with info3:
        st.caption("최종 수정일")
        st.write(safe_str(shop_row.get("updated_at"), "-"))

    with st.form(key=f"edit_shop_form_{selected_shop_id}"):
        c1, c2 = st.columns(2)

        with c1:
            edit_shop_name = st.text_input("점포명", value=safe_str(shop_row.get("shop_name"), ""))
            edit_address = st.text_input("주소", value=safe_str(shop_row.get("address"), ""))
            edit_phone = st.text_input(
                "점포 연락처",
                value=safe_str(shop_row.get("phone"), safe_str(shop_row.get("tel"), "")),
            )
            edit_owner_phone = st.text_input(
                "점주 연락처",
                value=safe_str(shop_row.get("owner_phone"), "")
            )
            edit_officer_rank = st.text_input("담당자 계급", value=safe_str(shop_row.get("officer_rank"), ""))
            edit_officer_name = st.text_input("담당자 성명", value=safe_str(shop_row.get("officer_name"), ""))

        with c2:
            edit_current_score = st.number_input(
                "체감안전도/주관점수",
                min_value=0,
                max_value=100,
                value=int(pick_current_score(shop_row, 50)),
                step=1,
            )
            edit_uses_security_company = st.checkbox(
                "보안업체 이용",
                value=safe_bool(shop_row.get("uses_security_company"), False)
            )
            edit_has_emergency_bell = st.checkbox(
                "점포 비상벨 보유",
                value=safe_bool(shop_row.get("has_emergency_bell"), False)
            )
            edit_has_cctv = st.checkbox(
                "점포 CCTV 보유",
                value=safe_bool(shop_row.get("has_cctv"), False)
            )
            edit_other_security = st.text_area(
                "기타 보안시설",
                value=safe_str(shop_row.get("other_security"), ""),
                height=100
            )
            edit_cpo_comment = st.text_area(
                "CPO 의견",
                value=safe_str(shop_row.get("cpo_comment"), ""),
                height=100
            )

        save_col, delete_col = st.columns(2)
        save_clicked = save_col.form_submit_button("💾 수정 저장", use_container_width=True)
        delete_clicked = delete_col.form_submit_button("🗑️ 삭제 요청", use_container_width=True)

    if save_clicked:
        payload = {}

        if "shop_name" in edit_df.columns:
            payload["shop_name"] = edit_shop_name.strip()
        if "address" in edit_df.columns:
            payload["address"] = edit_address.strip()

        if "phone" in edit_df.columns:
            payload["phone"] = edit_phone.strip()
        if "tel" in edit_df.columns and "phone" not in edit_df.columns:
            payload["tel"] = edit_phone.strip()

        if "owner_phone" in edit_df.columns:
            payload["owner_phone"] = edit_owner_phone.strip()

        if "officer_rank" in edit_df.columns:
            payload["officer_rank"] = edit_officer_rank.strip()
        if "officer_name" in edit_df.columns:
            payload["officer_name"] = edit_officer_name.strip()

        if "perceived_safety" in edit_df.columns:
            payload["perceived_safety"] = int(edit_current_score)
        elif "subjective_score" in edit_df.columns:
            payload["subjective_score"] = int(edit_current_score)
        elif "safety_score" in edit_df.columns:
            payload["safety_score"] = int(edit_current_score)

        if "uses_security_company" in edit_df.columns:
            payload["uses_security_company"] = bool(edit_uses_security_company)
        if "has_emergency_bell" in edit_df.columns:
            payload["has_emergency_bell"] = bool(edit_has_emergency_bell)
        if "has_cctv" in edit_df.columns:
            payload["has_cctv"] = bool(edit_has_cctv)
        if "other_security" in edit_df.columns:
            payload["other_security"] = edit_other_security.strip()
        if "cpo_comment" in edit_df.columns:
            payload["cpo_comment"] = edit_cpo_comment.strip()
        if "updated_at" in edit_df.columns:
            payload["updated_at"] = datetime.now().isoformat()

        try:
            supabase.table("shops").update(payload).eq("id", shop_row["id"]).execute()
            st.success("점포 설문이 수정되었습니다.")
            st.session_state["MV_FAST_MODE"] = True
            time.sleep(0.3)
            st.rerun()
        except Exception as e:
            st.error(f"수정 실패: {e}")

    if delete_clicked:
        st.session_state["delete_target_shop_id"] = str(selected_shop_id)

    if st.session_state.get("delete_target_shop_id") == str(selected_shop_id):
        st.warning("정말 삭제하시려면 아래 '최종 삭제'를 누르세요. 삭제 후 복구가 어렵습니다.")
        d1, d2 = st.columns(2)

        if d1.button("🚨 최종 삭제", key=f"delete_final_{selected_shop_id}", use_container_width=True):
            try:
                supabase.table("shops").delete().eq("id", shop_row["id"]).execute()
                st.success("점포 설문이 삭제되었습니다.")
                st.session_state.pop("delete_target_shop_id", None)
                st.session_state.pop("selected_shop_id", None)
                st.session_state["MV_FAST_MODE"] = True
                time.sleep(0.3)
                st.rerun()
            except Exception as e:
                st.error(f"삭제 실패: {e}")

        if d2.button("취소", key=f"delete_cancel_{selected_shop_id}", use_container_width=True):
            st.session_state.pop("delete_target_shop_id", None)
            st.rerun()