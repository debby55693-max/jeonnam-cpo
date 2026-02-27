import streamlit as st

# ✅ 사이드바 기본 펼침 고정
st.set_page_config(page_title="소상공인 시스템", layout="wide", initial_sidebar_state="expanded")

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _purge_modules(prefixes: list[str]):
    """admin_app ↔ survey_app 전환 시, 같은 이름(pages/core) 모듈 캐시 충돌 방지"""
    for k in list(sys.modules.keys()):
        for p in prefixes:
            if k == p or k.startswith(p + "."):
                sys.modules.pop(k, None)


def _set_sys_path(app_folder: str):
    """선택된 앱 폴더만 sys.path 최상단으로 올리기"""
    for folder in ["admin_app", "survey_app"]:
        p = str(ROOT / folder)
        if p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(ROOT / app_folder))


def _run(app_folder: str):
    _purge_modules(["pages", "core"])
    _set_sys_path(app_folder)
    runpy.run_path(str(ROOT / app_folder / "app.py"), run_name="__main__")


with st.sidebar:
    st.markdown("## 🧭 모드 선택")
    mode = st.radio("", ["관리자/분석", "설문 입력"], index=0, label_visibility="collapsed")
    st.caption("※ 아래 화면은 기존 UI 그대로 실행됩니다.")

if mode == "관리자/분석":
    _run("admin_app")
else:
    _run("survey_app")