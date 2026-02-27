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
        # data가 0이면 그대로 fallback 하지 않고, 빈 df 반환(다운로드 기준을 biz_stores로 보는 게 자연스러움)
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

    # ✅ 핵심: df.index를 가진 out으로 시작해야 스칼라 컬럼이 NaN 안 됨
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
    for _ in range(10):
        if (cur / "data").exists():
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
        # supabase-py는 count="exact" 지원하는 경우가 많음
        res = (
            supabase.table("biz_stores")
            .select("grid_id", count="exact")
            .eq("grid_id", gid)
            .limit(1)
            .execute()
        )
        cnt = getattr(res, "count", None)
        if cnt is None:
            # 환경별 fallback (count가 안 오면 최소 데이터로 대략)
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

    # shops 로드 (0건이어도 지도는 표시해야 함)
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

    # ✅ 지도용 DF: shops(좌표) + ranked merge
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

    # ✅ 지도는 항상 표시
    st.subheader("🗺️ 지도")
    if shops_df.empty:
        st.info("등록된 점포(설문)가 없어도 지도/시군경계/핫스팟 격자는 표시됩니다.")
    call_map_page(station=station, shops_df=map_df)

    st.divider()

    # =========================================================
    # ✅ 🟧 격자 우선순위 TOP (상위 10개만 표시)
    # - 점포수는 '다운로드 기준(DB count)'으로 표시하여 오차 제거
    # =========================================================
    st.subheader("🟧 격자 우선순위 TOP (need_score)")

    TOPN = 10
    station_key = _extract_station_key(station)
    sel_grid = st.session_state.get("selected_grid_id")

    # hotspot 파일 로드
    hot_path = _find_output_file("hotspot_grids.geojson")
    hot = None
    feats = []
    if hot_path:
        try:
            with open(hot_path, "r", encoding="utf-8") as f:
                hot = json.load(f)
            feats = hot.get("features", []) or []
        except Exception:
            feats = []

    # 관서 필터(시군)
    if feats and station_key:
        target = _station_key_to_sigungu(station_key)
        feats = [ft for ft in feats if (ft.get("properties", {}) or {}).get("sigungu") == target]

    # =========================
    # 1) 지도에서 선택한 격자 패널(정보 + 다운로드)
    # =========================
    if sel_grid:
        st.markdown("### 📌 선택 격자(지도 클릭)")
        p = _find_feat_props_by_gid(feats, sel_grid) if feats else None

        # 선택 격자 다운로드 데이터 1번만 준비
        raw_df, sel_src = _fetch_grid_store_list(supabase, str(sel_grid))
        dl_cnt = len(raw_df) if raw_df is not None else 0

        sel_out_df = _normalize_store_df(raw_df, str(sel_grid), station, sel_src)
        sel_xlsx = df_to_xlsx_bytes_safe(sel_out_df)
        sel_csv = sel_out_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")

        # 격자 정보 표시(상위목록 스타일)
        need = safe_float(p.get("need_score"), None) if p else None
        info = None
        if p:
            info = (
                f"점포 {dl_cnt} | "  # ✅ 다운로드 기준
                f"112 {safe_int(p.get('cnt_112'),0)} | "
                f"5대 {safe_int(p.get('cnt_5crime'),0)} | "
                f"CCTV {safe_int(p.get('cnt_cctv'),0)} | "
                f"순찰 {safe_int(p.get('cnt_patrol'),0)}"
            )

        cA, cB, cC = st.columns([3, 5, 2])
        with cA:
            st.markdown(_cell(str(sel_grid), selected=True, bold=True), unsafe_allow_html=True)
        with cB:
            st.markdown(
                _cell((f"need_score {need:.2f} / {info}" if (need is not None and info) else f"점포 {dl_cnt} (다운로드 기준)"),
                      selected=True),
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

    # =========================
    # 2) TOP10 목록 + 체크 합본 다운로드
    # =========================
    if not hot_path or not feats:
        st.caption("hotspot_grids.geojson 파일이 없습니다. (tools/make_hotspot_geojson.py 실행 필요)")
    else:
        rows = []
        for ft in feats:
            p = ft.get("properties", {}) or {}
            rows.append({
                "grid_id": p.get("grid_id"),
                "need_score": p.get("need_score"),
                "cnt_store": p.get("cnt_store"),  # (참고용) 화면에는 안 씀
                "cnt_112": p.get("cnt_112"),
                "cnt_5crime": p.get("cnt_5crime"),
                "cnt_cctv": p.get("cnt_cctv"),
                "cnt_patrol": p.get("cnt_patrol"),
            })

        gdf = pd.DataFrame(rows)
        if gdf.empty:
            st.info("표시할 격자 우선순위 데이터가 없습니다.")
        else:
            gdf["need_score"] = pd.to_numeric(gdf["need_score"], errors="coerce")
            gdf = gdf.sort_values(["need_score"], ascending=False).reset_index(drop=True)

            gdf_top = gdf.head(TOPN).copy()
            gdf_top["grid_id"] = gdf_top["grid_id"].apply(_gid_str)
            gdf_top = gdf_top[gdf_top["grid_id"] != ""].reset_index(drop=True)

            top_gids = gdf_top["grid_id"].tolist()

            # ✅ TOP10에 대한 다운로드 기준 점포수 미리 계산
            store_cnt_map = {gid: _get_store_count_download_basis(supabase, gid) for gid in top_gids}

            # 지도 클릭된 sel_grid는 자동 체크 ON(단, TOP10 안에 있을 때만)
            if sel_grid and str(sel_grid).strip() in top_gids:
                k = f"chk_{_gid_key(str(sel_grid).strip())}"
                if k not in st.session_state:
                    st.session_state[k] = True

            # 전체선택(보이는 10개만)
            def _toggle_all():
                v = st.session_state.get("chk_all_top10", False)
                for gid in top_gids:
                    st.session_state[f"chk_{_gid_key(gid)}"] = v

            # 초기 전체선택 상태
            if "chk_all_top10" not in st.session_state:
                st.session_state["chk_all_top10"] = all(
                    st.session_state.get(f"chk_{_gid_key(gid)}", False) for gid in top_gids
                )

            # 체크된 격자(Top10만)
            checked_gids = [gid for gid in top_gids if st.session_state.get(f"chk_{_gid_key(gid)}", False)]

            # 합본 생성
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

            # 헤더(UI): 점포리스트 다운 + 전체선택
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

            st.caption(f"현재 관서 기준 상위 {len(top_gids)}개 격자 — (체크 {len(checked_gids)}개)")

            # 본문 행들 (개별 다운로드 버튼 없음)
            for i, r in gdf_top.iterrows():
                grid_id_str = _gid_str(r.get("grid_id"))
                is_sel = (str(sel_grid or "").strip() == grid_id_str)

                need = r.get("need_score")
                need_txt = f"{float(need):.2f}" if need == need else str(need)

                dl_cnt = int(store_cnt_map.get(grid_id_str, 0))

                info = (
                    f"점포 {dl_cnt} | "  # ✅ 다운로드 기준
                    f"112 {safe_int(r.get('cnt_112'),0)} | "
                    f"5대 {safe_int(r.get('cnt_5crime'),0)} | "
                    f"CCTV {safe_int(r.get('cnt_cctv'),0)} | "
                    f"순찰 {safe_int(r.get('cnt_patrol'),0)}"
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
                        st.rerun()

                with c6:
                    st.checkbox("", key=f"chk_{_gid_key(grid_id_str)}", label_visibility="collapsed")

    # ✅ 점포가 없으면, 이후(점포 기반 UI)는 보여줄 수 없으니 여기서 끝.
    if shops_df.empty:
        st.caption("※ 점포(설문)가 등록되면 TOP5/현황표/설문수정/점수정보/진단 기능이 활성화됩니다.")
        return

    # =========================================================
    # (기존) TOP5
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
            c1, c2, c3, c4, c5 = st.columns([1, 2, 5, 2, 2])
            with c1:
                st.write(f"#{safe_int(r.get('priority_rank'), 0)}")
            with c2:
                st.write(safe_str(r.get("station"), ""))
            with c3:
                st.write(safe_str(r.get("shop_name"), ""))
            with c4:
                st.write(f"{safe_float(r.get('priority_score'), 0):.1f}")
            with c5:
                if st.button("📍 이동", key=f"top_move_{shop_id}_{i}"):
                    st.session_state["selected_shop_id"] = str(shop_id)
                    st.rerun()
    else:
        st.info("TOP5를 표시할 데이터가 없습니다. (v_shops_priority_ranked 확인)")

    st.divider()

    # =========================================================
    # (기존) 전체 현황표
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
            except Exception:
                pass

        except TypeError:
            st.dataframe(display_df, use_container_width=True, height=420, hide_index=True)
            st.caption("※ 표 클릭으로 지도 이동 기능은 Streamlit 최신 버전에서만 동작합니다.")