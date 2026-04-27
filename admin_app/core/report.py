"""
소상공인 안전물품 지원 관리시스템 - A4 리포트 생성 모듈

위원회 검토용 점포별 1장 보고서를 Word(.docx) 형태로 생성합니다.
"""

from __future__ import annotations
from io import BytesIO
from typing import Any, Dict, List, Optional
import zipfile
from datetime import datetime

from docx import Document
from docx.shared import Pt, Cm, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from core.scoring import score_breakdown, FIELD_SCORING


# ─────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────

def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _or(v: Any, fallback: str = "-") -> str:
    s = _s(v)
    return s if s and s not in ("None", "nan") else fallback


def _set_cell_bg(cell, hex_color: str):
    """표 셀 배경색 설정"""
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_cell_border(cell, sides=("top", "bottom", "left", "right"), color="AAAAAA", size="4"):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    tcBorders = OxmlElement("w:tcBorders")
    for side in sides:
        border = OxmlElement(f"w:{side}")
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), size)
        border.set(qn("w:color"), color)
        tcBorders.append(border)
    tcPr.append(tcBorders)


def _bold_run(para, text: str, size_pt: int = 10, color_hex: Optional[str] = None):
    run = para.add_run(text)
    run.bold = True
    run.font.size = Pt(size_pt)
    if color_hex:
        run.font.color.rgb = RGBColor.from_string(color_hex)
    return run


def _normal_run(para, text: str, size_pt: int = 10, color_hex: Optional[str] = None):
    run = para.add_run(text)
    run.bold = False
    run.font.size = Pt(size_pt)
    if color_hex:
        run.font.color.rgb = RGBColor.from_string(color_hex)
    return run


def _add_section_heading(doc: Document, title: str):
    """섹션 헤딩 (구분선 포함)"""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(2)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:color"), "1E3A5F")
    pBdr.append(bottom)
    pPr.append(pBdr)
    run = p.add_run(f"■ {title}")
    run.bold = True
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)
    return p


def _add_kv_table(doc: Document, rows: List[tuple], col_widths=(4.0, 12.0)):
    """키-값 2열 테이블 추가"""
    table = doc.add_table(rows=len(rows), cols=2)
    table.style = "Table Grid"
    w_key = Cm(col_widths[0])
    w_val = Cm(col_widths[1])
    for i, (key, val) in enumerate(rows):
        row = table.rows[i]
        # 키 셀
        kc = row.cells[0]
        kc.width = w_key
        _set_cell_bg(kc, "EEF2FA")
        kp = kc.paragraphs[0]
        kp.paragraph_format.space_before = Pt(2)
        kp.paragraph_format.space_after = Pt(2)
        _bold_run(kp, key, size_pt=9.5)
        # 값 셀
        vc = row.cells[1]
        vc.width = w_val
        vp = vc.paragraphs[0]
        vp.paragraph_format.space_before = Pt(2)
        vp.paragraph_format.space_after = Pt(2)
        _normal_run(vp, _or(val), size_pt=9.5)
    return table


def _score_bar_text(score: float, max_score: float) -> str:
    if max_score <= 0:
        return ""
    ratio = min(1.0, score / max_score)
    filled = int(ratio * 10)
    return "█" * filled + "░" * (10 - filled)


# ─────────────────────────────────────────────────
# 리포트 생성 메인
# ─────────────────────────────────────────────────

def generate_report(row: Dict, precas_scores: Dict, rank: Optional[int] = None, total_count: Optional[int] = None) -> bytes:
    """
    점포 1건의 A4 보고서를 Word bytes로 반환.

    Args:
        row:           v_admin_applications 뷰 데이터
        precas_scores: compute_precas_scores_batch() 결과
        rank:          전체 순위 (선택)
        total_count:   전체 점포 수 (선택)
    """
    bd = score_breakdown(row, precas_scores)
    doc = Document()

    # ── 페이지 설정 (A4) ─────────────────────────
    section = doc.sections[0]
    section.page_width  = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin    = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin   = Cm(2.0)
    section.right_margin  = Cm(2.0)

    # 기본 폰트
    doc.styles["Normal"].font.name = "맑은 고딕"
    doc.styles["Normal"].font.size = Pt(10)

    # ── 헤더 ─────────────────────────────────────
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_p.paragraph_format.space_after = Pt(4)
    tr = title_p.add_run("소상공인 방범물품 지원 검토 보고서")
    tr.bold = True
    tr.font.size = Pt(15)
    tr.font.color.rgb = RGBColor(0x1E, 0x3A, 0x5F)

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(6)
    sub_p.add_run("전라남도경찰청 CPO 관리시스템").font.size = Pt(9)

    # ── 총점 배너 ────────────────────────────────
    score_table = doc.add_table(rows=1, cols=3)
    score_table.style = "Table Grid"
    sc0 = score_table.rows[0].cells[0]
    sc1 = score_table.rows[0].cells[1]
    sc2 = score_table.rows[0].cells[2]
    _set_cell_bg(sc0, "1E3A5F")
    _set_cell_bg(sc1, "2563EB")
    _set_cell_bg(sc2, "3B82F6")

    def _banner_cell(cell, label: str, value: str):
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        r1 = p.add_run(f"{label}\n")
        r1.font.color.rgb = RGBColor(0xBF, 0xDB, 0xFE)
        r1.font.size = Pt(8)
        r2 = p.add_run(value)
        r2.bold = True
        r2.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        r2.font.size = Pt(14)

    total = bd["total"]
    rank_text = f"상위 {round((1 - rank/total_count)*100)}%" if rank and total_count else "-"
    _banner_cell(sc0, "총점 (100점 만점)", f"{total}점")
    _banner_cell(sc1, "순위", f"{rank}위 / {total_count}건" if rank else "-")
    _banner_cell(sc2, "백분위", rank_text)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)

    # ── 1. 점포 기본 정보 ────────────────────────
    _add_section_heading(doc, "점포 기본 정보")

    def full_addr():
        road = _s(row.get("address_road"))
        detail = _s(row.get("address_detail"))
        full = _s(row.get("full_address"))
        if full:
            return full
        return f"{road} {detail}".strip() or _or(row.get("address_jibun"))

    status_map = {
        "submitted": "접수완료", "under_review": "검토중",
        "docs_requested": "추가서류요청", "reviewed": "검토완료",
        "selection_consideration": "선정고려", "selected": "선정", "excluded": "제외",
    }
    status_label = status_map.get(_s(row.get("current_status")), _s(row.get("current_status")))

    _add_kv_table(doc, [
        ("점포명",     row.get("business_name")),
        ("대표자",     row.get("applicant_name")),
        ("연락처",     row.get("phone")),
        ("업종",       row.get("business_type")),
        ("연매출 구간", row.get("sales_band")),
        ("주소",       full_addr()),
        ("관할 경찰서", row.get("station_label")),
        ("신청일",     _s(row.get("submitted_at"))[:10]),
        ("현재 상태",  status_label),
    ])

    # ── 2. 프리카스 격자 데이터 ──────────────────
    _add_section_heading(doc, f"프리카스 격자 데이터 (배점 40점 / 획득 {bd['precas_total']}점)")

    if bd["has_precas"]:
        p112_text   = f"{bd['pct_112']}%" if bd['pct_112'] is not None else "-"
        prisk_text  = f"{bd['pct_risk']}%" if bd['pct_risk'] is not None else "-"
        ppatrol_text = f"{bd['pct_patrol']}%" if bd['pct_patrol'] is not None else "-"

        _add_kv_table(doc, [
            ("112신고 건수",
             f"{_or(row.get('precas_112_count'))}건  →  {_score_bar_text(bd['precas_112'], 16)}  {bd['precas_112']}점/16점  (상위 {p112_text})"),
            ("위험도 등급",
             f"{_or(row.get('precas_risk_grade'))}등급  →  {_score_bar_text(bd['precas_risk'], 14)}  {bd['precas_risk']}점/14점  (상위 {prisk_text})"),
            ("탄력순찰 수",
             f"{_or(row.get('precas_patrol_count'))}회  →  {_score_bar_text(bd['precas_patrol'], 10)}  {bd['precas_patrol']}점/10점  (상위 {ppatrol_text})"),
        ])
    else:
        p = doc.add_paragraph()
        _normal_run(p, "※ 프리카스 데이터 미입력 (0점 처리)", size_pt=9, color_hex="999999")

    # ── 3. CPO 현장 환경조사 ─────────────────────
    _add_section_heading(doc, f"CPO 현장 환경조사 (배점 20점 / 획득 {bd['field_total']}점)")

    field_rows = []
    for item in bd["field_detail"]:
        bar = _score_bar_text(item["score"], item["max"])
        field_rows.append((
            item["label"],
            f"{item['value']}  {bar}  {item['score']}점/{item['max']}점"
        ))
    _add_kv_table(doc, field_rows)

    # ── 4. 신청인 설문 요약 ──────────────────────
    _add_section_heading(doc, f"신청인 설문 (배점 30점 / 획득 {bd['survey_total']}점)")

    survey_val = {
        "survey_crime_anxiety":  ("범죄피해 경험",    row.get("survey_crime_anxiety")),
        "survey_late_night":     ("야간 영업 여부",   row.get("survey_late_night")),
        "survey_dark_area":      ("주변 환경",        row.get("survey_dark_area")),
        "survey_single_worker":  ("단독 근무",        row.get("survey_single_worker")),
    }

    cctv_val    = "있음" if bool(row.get("has_cctv")) else "없음"
    sec_val     = "이용 중" if bool(row.get("uses_security_company")) else "이용하지 않음"
    bell_val    = "있음" if bool(row.get("has_emergency_bell")) else "없음"

    env_rows = [(label, _or(val)) for _, (label, val) in survey_val.items()]
    env_rows += [
        ("점포내 CCTV",    cctv_val),
        ("사설경비 이용",  sec_val),
        ("비상벨 설치",    bell_val),
        ("체감안전도 점수", f"{bd['felt_safety']}점/10점"),
    ]
    env_rows.insert(0, ("환경설문 소계", f"{bd['survey_env']}점/20점"))
    _add_kv_table(doc, env_rows)

    # ── 5. CPO 재량점수 ──────────────────────────
    _add_section_heading(doc, f"CPO 재량점수 (배점 10점 / 획득 {bd['discretionary']}점)")
    disc_reason = _or(bd["discretionary_reason"])
    _add_kv_table(doc, [
        ("재량점수", f"{bd['discretionary']}점 / 10점"),
        ("입력 사유", disc_reason),
    ])

    # ── 6. CPO 최종 검토 의견 ────────────────────
    _add_section_heading(doc, "CPO 최종 검토 의견")
    comment = _or(row.get("review_comment"))
    opinion_p = doc.add_paragraph()
    opinion_p.paragraph_format.space_before = Pt(2)
    opinion_p.paragraph_format.space_after = Pt(2)
    opinion_p.paragraph_format.left_indent = Cm(0.5)
    _normal_run(opinion_p, comment, size_pt=10)

    # 검토자 정보
    reviewed_at = _s(row.get("reviewed_at") or "")[:10] or "-"
    footer_p = doc.add_paragraph()
    footer_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer_p.paragraph_format.space_before = Pt(6)
    _normal_run(
        footer_p,
        f"검토 상태: {status_label}  |  검토일: {reviewed_at}  |  관할: {_or(row.get('station_label'))}",
        size_pt=8,
        color_hex="666666",
    )

    # ── 저장 ─────────────────────────────────────
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def generate_report_zip(rows: List[Dict], precas_scores: Dict) -> bytes:
    """
    선택된 점포 전체의 보고서를 ZIP으로 묶어 bytes 반환.
    점수 기준 내림차순 정렬 후 순위 부여.
    """
    from core.scoring import compute_total_score

    sorted_rows = sorted(rows, key=lambda r: compute_total_score(r, precas_scores), reverse=True)
    total_count = len(sorted_rows)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rank, row in enumerate(sorted_rows, start=1):
            docx_bytes = generate_report(row, precas_scores, rank=rank, total_count=total_count)
            biz_name   = _s(row.get("business_name")) or f"store_{rank}"
            # 파일명 안전 처리
            safe_name  = "".join(c for c in biz_name if c.isalnum() or c in "가-힣ㄱ-ㅎㅏ-ㅣ _-")
            filename   = f"{rank:03d}_{safe_name}.docx"
            zf.writestr(filename, docx_bytes)
    return buf.getvalue()
