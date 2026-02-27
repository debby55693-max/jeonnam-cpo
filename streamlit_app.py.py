import streamlit as st
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _run(app_folder: str):
    app_dir = ROOT / app_folder

    # 각 앱 폴더를 sys.path에 올려서
    # admin_app/app.py 안에서 "from core..." 같은 import가 그대로 되게 함
    p = str(app_dir)
    if p not in sys.path:
        sys.path.insert(0, p)

    # 해당 앱의 app.py를 "그대로 실행"
    runpy.run_path(str(app_dir / "app.py"), run_name="__main__")


# ✅ 여기서는 set_page_config 호출하지 않음 (각 앱에서 이미 하고 있을 가능성이 큼)
with st.sidebar:
    st.markdown("## 🧭 모드 선택")
    mode = st.radio("", ["관리자/분석", "설문 입력"], index=0, label_visibility="collapsed")
    st.caption("※ 아래 화면은 기존 UI 그대로 실행됩니다.")

if mode == "관리자/분석":
    _run("admin_app")
else:
    _run("survey_app")