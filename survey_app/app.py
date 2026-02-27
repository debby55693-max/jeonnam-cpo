# survey_app/app.py
import streamlit as st

from core.supabase_client import get_supabase
from pages.field_public import field_public_page

# ✅ streamlit_app.py에서 set_page_config를 이미 호출했으면 여기서 에러가 날 수 있어 방지
try:
    st.set_page_config(page_title="소상공인 방범물품 지원 - 현장", layout="wide")
except Exception:
    pass

supabase = get_supabase()
field_public_page(supabase)