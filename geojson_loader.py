# geojson_loader.py
import json
from pathlib import Path

import requests
import streamlit as st


@st.cache_data(show_spinner=False)
def load_geojson_from_secrets_or_local(secret_key: str, local_paths: list[str]):
    """
    1) local_paths 중 존재하는 파일이 있으면 그걸 로드
    2) 없으면 Streamlit Secrets에 있는 URL(secret_key)에서 다운로드
    """
    # 1) 로컬 우선
    for p in local_paths:
        path = Path(p)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))

    # 2) Secrets URL
    url = st.secrets.get(secret_key)
    if not url:
        return None

    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()