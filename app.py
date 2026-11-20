"""티링크 AI 현장사진 홍보콘텐츠 자동생성기
현장 사진 + 제품 정보(facts.csv) + 업체 리뷰 가이드라인(guideline.json)
→ 사진 분석 → 기술 차별점 매칭 → 가이드라인 맞춤 블로그·인스타 콘텐츠 → 코드 자동 검수
실행: streamlit run app.py
"""
import csv
import io
import json
import os
import re
from pathlib import Path

import streamlit as st

BASE = Path(__file__).parent
HEAD_LIMIT, SUB_LIMIT = 20, 45
MAX_PHOTOS = 5
SAMPLE_LABELS = {  # 파일명은 영문(윈도우 압축 해제 시 한글 깨짐 방지), 화면에는 한글로 표시
    "01_dashboard": "경영 대시보드",
    "02_consult": "상담 관리 화면",
    "03_call_stt": "통화 상세·STT",
    "04_ai_analysis": "AI 분석",
    "05_kpi_sales": "핵심 지표·영업기회",
}


# ---------------------------------------------------------------- 데이터
def read_facts(text):
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{"id": f"F{i}", **r} for i, r in enumerate(rows, 1)]


def default_facts():
    return read_facts((BASE / "facts.csv").read_text(encoding="utf-8-sig"))


def default_guideline():
    return json.loads((BASE / "guideline.json").read_text(encoding="utf-8"))


def facts_block(facts):
    return "\n".join(f"[{f['id']}] ({f['제품']}) {f['사실']}  — 출처: {f['출처']}" for f in facts)


# ---------------------------------------------------------------- 프롬프트
MODES = {
    "brand": "브랜드 블로그 · 도입 사례 소개",
    "review": "체험단 리뷰어용 초안",
}
DISCLOSURE = "※ 이 포스팅은 ㈜티링크앤주인닷컴으로부터 [제공받은 내용: 제품 체험 / 원고료 등]을 제공받아 작성되었습니다."


def mode_rule(mode):
    if mode == "review":
        return """작성 방식: 체험단 리뷰어가 직접 사용한 뒤 완성할 '리뷰 초안'이다.
- 1인칭 후기 문장은 쓰되, 리뷰어가 실제로 겪은 일(회사 규모, 기간, 통화 결과, 소감, "실제로 해 보니" 같은 사용 경험)은 한 문장도 지어내지 말고 "[직접 사용 후 작성: 무엇을 쓸지 안내]" 자리로 남겨.
- 제품 기능 설명 부분만 완성된 문장으로 써."""
    return """작성 방식: 티링크 공식 블로그에 올리는 '도입 사례·기능 소개' 글이다.
- 가상의 사용자나 회사를 1인칭으로 지어내지 마. "이런 회사라면", "외근 영업팀은" 처럼 3인칭으로 써.
- 현장 메모에 적힌 상황만 사례로 쓸 수 있다."""


def build_prompt(g, facts, memo, n_photos, mode="brand"):
    conflicts = "\n".join(f"- {c['내용']}: {c['이유']}" for c in g.get("확인필요_충돌", [])) or "- 없음"
    missions = "\n".join(f"{i}. {m}" for i, m in enumerate(g["미션"], 1))
    return f"""너는 '{g['업체명']}'에 입사한 10년 차 B2B 콘텐츠 마케터야.
첨부한 현장 사진 {n_photos}장과 아래 [제품 정보], [리뷰 가이드라인]만 근거로 네이버 블로그 리뷰와 인스타그램 카드뉴스를 만들어.

[현장 메모] {memo or '없음'}

{mode_rule(mode)}

[제품 정보] (각 줄 앞의 [F번호]가 근거 ID)
{facts_block(facts)}

[리뷰 가이드라인]
- 홍보 제품: {g['제품명']}
- 리뷰 컨셉: {g['리뷰컨셉']}
- 필수 키워드(제목에 1회, 본문 소제목 글에도 각각 1회 이상 반드시 포함): {', '.join(g['필수키워드'])}
- 제목과 첫 문단에 넣을 키워드: {', '.join(g['제목_첫문단_키워드'])}
- 서브 키워드(자연스럽게): {', '.join(g['서브키워드'])}
- 허용 태그: {' '.join(g['태그'])}
- 추천 본문 구성(이 순서로 소제목): {' → '.join(g['추천구성'])}
- 리뷰 미션:
{missions}

[사용 금지]
- 단어: {', '.join(g['사용금지'])}
- 업체 확인 전 사용 금지 정보:
{conflicts}

규칙:
0. 자료에 없는 효과를 부풀리지 마. "입증", "보장", "차단", "철저" 같은 단정 표현 대신 자료 문장 그대로의 기능 설명을 써.
1. 제품 정보에 없는 기능·수치·가격·고객사·인증은 절대 만들지 마. 필요한 자리에는 "[확인 필요]"라고 써.
2. 제품 기능을 말하는 문장마다 근거 ID를 fact_ids에 적어. 근거가 없으면 그 문장을 쓰지 마.
3. 숫자는 제품 정보와 현장 메모에 있는 숫자만 써. 사진(제품 화면) 속 건수·퍼센트·시간은 예시 데이터이므로 실제 성과처럼 쓰지 마. 가격을 쓰면 조건(상담원 1인 기준, 설정비, VAT 별도, 상담 후 확정)을 빠짐없이 함께 써.
4. 사진마다 무슨 화면/현장인지 판단하고, 블로그 소제목 중 어디에 넣을지 정해. 사진에 없는 내용을 사진 설명으로 지어내지 마.
5. 사진에 사람 얼굴, 실제 고객명·전화번호, 상호가 보이면 privacy_risks에 적어.
6. 인스타 카드뉴스는 정확히 5장, headline {HEAD_LIMIT}자 이내, sub {SUB_LIMIT}자 이내(공백 포함).
7. 블로그 본문은 소제목 본문을 합쳐 {g.get('블로그_최소글자', 1500)}자 이상. 한 문단은 3~4문장 이내로 짧게 나눠.
8. 근거 ID(F1 같은 표시)는 본문에 쓰지 말고 fact_ids에만 적어.
9. 제목은 55자 이내 자연스러운 한 문장으로 쓰고, 필수 키워드 3개와 '{g['제품명']}'을 넣어. 나머지 지정 키워드는 첫 문단에 자연스럽게 넣어.
11. instagram_hashtags는 아래 [허용 태그] 목록에서만 5~10개 골라.
10. 하단 홈페이지·문의 정보와 광고 표기 문구는 앱이 자동으로 붙이니 쓰지 마.

아래 JSON 형식으로만 답해:
{{
  "photos": [{{"index": 1, "what": "사진 속 화면/현장", "section": "넣을 소제목", "caption": "사진 아래 설명 한 줄"}}],
  "points": [{{"point": "기술 차별점 한 줄", "fact_ids": ["F1"], "why": "이 현장·타겟에 중요한 이유"}}],
  "blog": {{
    "title": "블로그 제목",
    "first_paragraph": "첫 문단",
    "sections": [{{"heading": "소제목", "body": "본문", "photo_index": 1, "fact_ids": ["F1"]}}],
    "conclusion": "결론 문단"
  }},
  "mission_coverage": [{{"mission": 1, "section": "반영한 소제목"}}],
  "instagram": [{{"headline": "", "sub": ""}}],
  "instagram_caption": "피드 본문",
  "instagram_hashtags": ["#..."],
  "privacy_risks": []
}}"""


def build_revision_prompt(g, facts, result, failed, mode):
    issues = "\n".join(f"- {c['label']}: {c['detail']}" for c in failed)
    return f"""아래 [기존 결과]는 자동 점검에서 다음 문제가 발견됐어.
[발견된 문제]
{issues}

[제품 정보]
{facts_block(facts)}

{mode_rule(mode)}

할 일:
1. 위 문제만 고치고, 나머지 내용·구성·사진 배치(photos, photo_index)는 최대한 그대로 둬.
2. 사용 금지 단어: {', '.join(g['사용금지'])} — 모든 필드에서 빼고 자연스러운 표현으로 바꿔.
3. 필수 키워드 {', '.join(g['필수키워드'])}는 제목과 본문에 모두 들어가야 해.
4. 숫자는 제품 정보와 현장 메모에 있는 것만. 근거 ID는 본문에 쓰지 말고 fact_ids에만.
5. 해시태그는 다음 목록에서만: {' '.join(g['태그'])}
6. [기존 결과]와 똑같은 JSON 형식으로만 답해.

[기존 결과]
{json.dumps(result, ensure_ascii=False)}"""


def shrink(data, mime, max_side=1280):
    """전송 전 사진을 줄여 생성 속도를 높임."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if max(im.size) <= max_side:
            return data, mime
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def call_gemini(api_key, model, images, prompt):
    from google import genai
    from google.genai import types

    images = [shrink(b, m) for b, m in images]
    client = genai.Client(api_key=api_key)
    parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in images] + [prompt]
    resp = client.models.generate_content(
        model=model,
        contents=parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4),
    )
    text = re.sub(r"^```(?:json)?|```$", "", resp.text.strip()).strip()
    return json.loads(text)


# ---------------------------------------------------------------- 자동 검수 (AI 결과를 그대로 믿지 않음)
def plain(md):
    """마크다운 기호를 뺀 실제 글자."""
    md = re.sub(r"[#*_>`|\-]+", " ", md or "")
    return re.sub(r"\s+", " ", md).strip()


def blog_text(blog):
    secs = "\n".join(f"{s.get('heading','')}\n{s.get('body','')}" for s in blog.get("sections", []))
    return "\n".join([blog.get("first_paragraph", ""), secs, blog.get("conclusion", "")])


def numbers_in(text):
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", text)  # 목록 번호 제외
    text = re.sub(r"\[F\d+\]|F\d+", " ", text)  # 근거 ID 제외
    return set(re.findall(r"\d[\d,.]*\d|\d", text))


def audit(result, g, facts, memo=""):
    blog = result.get("blog", {})
    title, first = blog.get("title", ""), blog.get("first_paragraph", "")
    body = blog_text(blog)
    fact_ids = {f["id"] for f in facts}
    source_text = facts_block(facts) + json.dumps(g, ensure_ascii=False) + "\n" + (memo or "")
    checks = []

    def add(ok, label, detail=""):
        checks.append({"ok": ok, "label": label, "detail": detail})

    # 1. 근거 ID
    used = [fid for p in result.get("points", []) for fid in p.get("fact_ids", [])]
    used += [fid for s in blog.get("sections", []) for fid in s.get("fact_ids", [])]
    bad = sorted(set(used) - fact_ids)
    add(bool(used) and not bad, f"근거 ID {len(set(used)) - len(bad)}개 확인", f"없는 ID: {', '.join(bad)}" if bad else "")

    # 2. 출처 없는 숫자
    src_nums = numbers_in(source_text)
    orphan = sorted(n for n in numbers_in(title + "\n" + body) if n not in src_nums)
    add(not orphan, "모든 숫자가 제품 정보에 있음", f"출처 없는 숫자: {', '.join(orphan)}" if orphan else "")

    # 3. 필수 키워드
    miss_t = [k for k in g["필수키워드"] if k not in title]
    miss_b = [k for k in g["필수키워드"] if k not in body]
    add(not miss_b, "필수 키워드 본문 포함", f"본문 누락: {', '.join(miss_b)}" if miss_b else "")
    add(not miss_t, "필수 키워드 제목 포함", f"제목 누락: {', '.join(miss_t)}" if miss_t else "")

    # 4. 제목·첫 문단 키워드
    miss_f = [k for k in g["제목_첫문단_키워드"] if k not in title + first]
    add(not miss_f, "제목·첫 문단 지정 키워드 포함", f"누락: {', '.join(miss_f)}" if miss_f else "")

    add(len(title) <= 55, f"블로그 제목 {len(title)}자 (55자 이내)")
    leaked = re.findall(r"\[?F\d+(?:,\s*F\d+)*\]?", body)
    add(not leaked, "본문에 근거 ID 표기 없음", "내보내기 원고에서는 자동 삭제됨" if leaked else "")

    # 5. 분량
    n = len(plain(body))
    need = g.get("블로그_최소글자", 1500)
    add(n >= need, f"블로그 본문 {n:,}자 (기준 {need:,}자 이상, 기호 제외)")

    # 6. 금지어·확인 필요 정보
    all_text = json.dumps(result, ensure_ascii=False)
    banned = [w for w in g["사용금지"] if w in all_text]
    add(not banned, "사용 금지 단어 없음", f"발견: {', '.join(banned)}" if banned else "")
    for c in g.get("확인필요_충돌", []):
        hit = c["패턴"] in all_text
        add(not hit, f"'{c['내용']}' 미사용", c["이유"] if hit else "")

    # 7. 추천 구성 / 미션
    heads = " ".join(s.get("heading", "") for s in blog.get("sections", []))
    miss_sec = [s for s in g["추천구성"] if s.replace("·", " ").split()[0] not in heads]  # 첫 단어로 대조
    add(not miss_sec, f"추천 본문 구성 {len(g['추천구성']) - len(miss_sec)}/{len(g['추천구성'])}", ", ".join(miss_sec))
    covered = {m.get("mission") for m in result.get("mission_coverage", [])}
    add(len(covered) >= len(g["미션"]), f"리뷰 미션 반영 {len(covered)}/{len(g['미션'])} (AI 자가 보고)")

    # 8. 인스타
    slides = result.get("instagram", [])
    over = [f"{i}장" for i, s in enumerate(slides, 1)
            if len(s.get("headline", "")) > HEAD_LIMIT or len(s.get("sub", "")) > SUB_LIMIT]
    add(len(slides) == 5 and not over, f"카드뉴스 {len(slides)}장 · 글자 수 제한", f"초과: {', '.join(over)}" if over else "")
    bad_tags = [t for t in result.get("instagram_hashtags", []) if t not in g["태그"]]
    add(not bad_tags, "해시태그가 가이드라인 태그 안에서 선택됨", f"목록 밖: {', '.join(bad_tags)}" if bad_tags else "")

    # 9. 확인 필요
    ph = all_text.count("[확인 필요]")
    add(ph == 0, f"[확인 필요] {ph}곳", "게시 전 업체 확인 후 채우기" if ph else "")
    return checks


def clean(t):
    """본문에 섞인 근거 ID 표기 제거."""
    t = re.sub(r"\s*\[F\d+(?:\s*,\s*F\d+)*\]", "", t or "")
    return re.sub(r"\s*\(F\d+(?:\s*,\s*F\d+)*\)", "", t)


def final_blog_markdown(result, g, photo_names, mode="brand"):
    b = result["blog"]
    out = [f"# {clean(b.get('title',''))}", ""]
    if mode == "review":
        out += [g.get("광고표기", DISCLOSURE), ""]
    out += [clean(b.get("first_paragraph", "")), ""]
    caps = {p.get("index"): p.get("caption", "") for p in result.get("photos", [])}
    for s in b.get("sections", []):
        out += [f"## {clean(s.get('heading',''))}", ""]
        idx = s.get("photo_index")
        if isinstance(idx, int) and 1 <= idx <= len(photo_names):
            out += [f"[사진 {idx}: {photo_names[idx-1]}] {caps.get(idx,'')}", ""]
        out += [clean(s.get("body", "")), ""]
    out += [clean(b.get("conclusion", "")), "", "---", g["하단정보"], "", " ".join(g["태그"])]
    return "\n".join(out)


# ---------------------------------------------------------------- 화면
ACCENT = "#1F3FE5"   # 강조색은 이 하나만: 주요 버튼 · 단계 번호
INK, SUB, LINE, BG = "#111827", "#6B7280", "#E5E7EB", "#F9FAFB"
COPYRIGHT = "© 2026 T·LINK 현장사진 홍보콘텐츠 생성기. All rights reserved."

CSS = f"""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
html, body, [class*="css"], .stMarkdown, button, input, textarea {{
  font-family: 'Pretendard', -apple-system, 'Malgun Gothic', sans-serif !important;
}}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stHeader"], footer {{ display:none !important; }}
.block-container {{ max-width: 860px; padding-top: 3rem !important; padding-bottom: 2rem; }}
.stMarkdown p, .stMarkdown li {{ font-size: 16px; line-height: 1.75; color: {INK}; }}

.brand {{ font-size:13px; color:{SUB}; line-height:1.6; }}
.brand b {{ color:{INK}; letter-spacing:.08em; margin-right:8px; }}
.title {{ font-size:28px; font-weight:800; color:{INK}; letter-spacing:-.02em; margin:.35rem 0 .4rem; }}
.lead {{ font-size:15.5px; color:{SUB}; line-height:1.7; margin:0 0 2rem; }}

.step {{ display:flex; gap:14px; align-items:flex-start; margin: 0 0 .9rem; }}
.num {{ flex:none; width:28px; height:28px; border-radius:50%; background:{ACCENT}; color:#fff;
        font-size:14px; font-weight:700; display:flex; align-items:center; justify-content:center; margin-top:2px; }}
.step h3 {{ font-size:18px; font-weight:700; color:{INK}; margin:0 0 2px; padding:0; }}
.step p {{ font-size:14.5px; color:{SUB}; margin:0; line-height:1.6; }}
.hint {{ font-size:13.5px; color:{SUB}; margin:.4rem 0 0; }}
.alert {{ font-size:14px; color:#B42318; margin:.4rem 0 0; }}

.sec {{ font-size:13px; font-weight:700; color:{SUB}; letter-spacing:.06em; margin:2.4rem 0 .6rem; }}
.kpis {{ display:grid; grid-template-columns:repeat(4,1fr); border:1px solid {LINE}; border-radius:12px; overflow:hidden; margin-bottom:1rem; }}
.kpi {{ padding:14px 16px; border-right:1px solid {LINE}; }}
.kpi:last-child {{ border-right:none; }}
.kpi span {{ display:block; font-size:12.5px; color:{SUB}; }}
.kpi b {{ font-size:22px; color:{INK}; font-weight:700; }}
.notice {{ border:1px solid {LINE}; background:{BG}; border-radius:10px; padding:12px 14px; font-size:14px; color:{INK}; margin-bottom:.8rem; }}

.chk {{ display:flex; gap:12px; padding:11px 0; border-bottom:1px solid {LINE}; font-size:14.5px; color:{INK}; }}
.tag {{ flex:none; font-size:12px; font-weight:600; padding:2px 8px; border-radius:4px; border:1px solid {LINE}; color:{SUB}; height:fit-content; }}
.tag.ng {{ border-color:#F3C9C4; color:#B42318; }}
.chk small {{ display:block; color:{SUB}; font-size:13px; margin-top:2px; }}
.src {{ font-size:13px; color:{SUB}; margin:.2rem 0 1rem; }}
.disc {{ font-size:13.5px; color:{SUB}; border-left:3px solid {LINE}; padding-left:10px; }}

div.stButton > button[kind="primary"] {{ height:52px; font-size:16px; font-weight:700; border-radius:10px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-color:{LINE} !important; border-radius:14px !important; }}
.copyright {{ text-align:center; font-size:12.5px; color:#9CA3AF; border-top:1px solid {LINE}; margin-top:3rem; padding-top:1.4rem; line-height:1.7; }}
@media (max-width: 640px) {{ .kpis {{ grid-template-columns:repeat(2,1fr); }} .kpi:nth-child(2) {{ border-right:none; }} }}
</style>
"""


def esc(t):
    import html as _h
    return _h.escape(str(t or ""))


def html(s):
    st.markdown(s, unsafe_allow_html=True)


def step_header(no, title, desc):
    html(f'<div class="step"><div class="num">{no}</div><div><h3>{esc(title)}</h3><p>{esc(desc)}</p></div></div>')


def render_checks(checks):
    rows = []
    for c in checks:
        tag = '<span class="tag">통과</span>' if c["ok"] else '<span class="tag ng">확인 필요</span>'
        detail = f"<small>{esc(c['detail'])}</small>" if c["detail"] else ""
        rows.append(f'<div class="chk">{tag}<div>{esc(c["label"])}{detail}</div></div>')
    html("".join(rows))


def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return os.getenv(name, "")


def main():
    import time

    st.set_page_config(page_title="T·LINK 현장사진 홍보콘텐츠 생성기", layout="centered",
                       initial_sidebar_state="collapsed")
    html(CSS)
    html('<div class="brand"><b>T·LINK</b>마케팅 콘텐츠 자동화</div>'
         '<div class="title">현장사진 홍보콘텐츠 생성기</div>'
         '<p class="lead">현장 사진을 올리면 티링크 제품 자료와 리뷰 가이드라인을 근거로 블로그 글과 인스타그램 카드뉴스 문구를 만들고, 게시 전 점검까지 해 드립니다.</p>')

    api_key = (get_secret("GEMINI_API_KEY") or st.session_state.get("api_key_input", "")).strip()
    model = (st.session_state.get("model_input") or get_secret("GEMINI_MODEL") or "gemini-3.8-flash").strip()
    g = st.session_state.get("guideline") or default_guideline()
    facts = st.session_state.get("facts") or default_facts()
    key_problem = ("API 키에 영문이 아닌 글자가 들어 있습니다. 관리 화면의 Secrets 값을 확인해 주세요."
                   if api_key and not api_key.isascii() else "")

    # ---- 1. 사진
    with st.container(border=True):
        step_header(1, "현장 사진 선택", "현장이나 제품 화면 사진을 최대 5장까지 올립니다. 처음이라면 샘플로 먼저 시험해 보세요.")
        src = st.radio("사진", ["샘플 사진 5장 사용", "내 사진 올리기"], horizontal=True, label_visibility="collapsed")
        if src.startswith("샘플"):
            files = sorted((BASE / "samples").glob("*.jpg"))
            images = [(p.read_bytes(), "image/jpeg") for p in files]
            names = [SAMPLE_LABELS.get(p.stem, p.stem) for p in files]
        else:
            ups = st.file_uploader("JPG 또는 PNG", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
            ups = (ups or [])[:MAX_PHOTOS]
            images = [(u.getvalue(), u.type) for u in ups]
            names = [Path(u.name).stem for u in ups]
            html('<p class="hint">고객 이름·전화번호·얼굴이 보이는 사진은 올리지 마세요.</p>')
        if images:
            cols = st.columns(len(images))
            for col, (b, _), nm in zip(cols, images, names):
                col.image(b, caption=nm)

    # ---- 2. 글 종류 + 메모
    with st.container(border=True):
        step_header(2, "글 종류와 현장 정보", "어디에 올릴 글인지 고르고, 어떤 고객의 어떤 문제를 해결했는지 한두 줄 적어 주세요.")
        mode_label = st.radio("글 종류", list(MODES.values()), horizontal=True, label_visibility="collapsed")
        mode = next(k for k, v in MODES.items() if v == mode_label)
        html('<p class="hint">' + ("체험단 리뷰어가 실제 사용 경험을 채워 넣을 자리를 남기고, 광고 표기 문구를 자동으로 붙입니다."
                                    if mode == "review" else
                                    "가상의 사용자 후기 없이, 3인칭 사례·기능 소개 글로 작성합니다.") + "</p>")
        memo = st.text_area("현장 메모", height=90, label_visibility="collapsed",
                            placeholder="예) 외근 영업사원 10명 회사. 휴대폰과 사무실 인터넷전화 통화를 따로 관리해 고객 이력이 흩어져 있었음")

    # ---- 3. 생성
    with st.container(border=True):
        step_header(3, "콘텐츠 만들기", f"'{g['제품명']}' 가이드라인과 제품 자료 {len(facts)}건만 근거로 씁니다. 약 2~3분 걸립니다.")
        run = st.button("콘텐츠 만들기", type="primary", use_container_width=True,
                        disabled=not (images and api_key) or bool(key_problem))
        if not images:
            html('<p class="hint">1단계에서 사진을 먼저 선택하세요.</p>')
        elif key_problem:
            html(f'<p class="alert">{esc(key_problem)}</p>')
        elif not api_key:
            html('<p class="alert">API 키가 설정되지 않았습니다. 페이지 아래 고급 설정에서 입력하세요.</p>')

    if run:
        t0 = time.time()
        with st.spinner("사진을 분석하고 원고를 쓰는 중입니다. 화면을 닫지 말고 기다려 주세요."):
            try:
                result = call_gemini(api_key, model, images, build_prompt(g, facts, memo, len(images), mode))
                st.session_state["out"] = {"result": result, "names": names, "images": images, "memo": memo,
                                           "mode": mode, "sec": round(time.time() - t0)}
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    st.error("사용량이 잠시 초과되었습니다. 1분 뒤 다시 시도해 주세요.")
                elif "404" in msg or "NOT_FOUND" in msg:
                    st.error("모델 이름을 찾을 수 없습니다. 고급 설정의 모델 이름을 확인해 주세요.")
                else:
                    st.error(f"만들기에 실패했습니다: {msg}")

    if st.session_state.get("out"):
        render_result(st.session_state["out"], g, facts, api_key, model)

    # ---- 하단
    html('<div class="sec">더 보기</div>')
    with st.expander("근거 자료 (제품 자료 · 리뷰 가이드라인)"):
        st.dataframe([{k: f[k] for k in ("id", "제품", "사실", "출처")} for f in facts],
                     hide_index=True, use_container_width=True)
        st.markdown(f"**필수 키워드** {esc(', '.join(g['필수키워드']))}  \n"
                    f"**제목·첫 문단 키워드** {esc(', '.join(g['제목_첫문단_키워드']))}")
        for c in g.get("확인필요_충돌", []):
            html(f'<p class="hint">사용 보류 · {esc(c["내용"])}: {esc(c["이유"])}</p>')
    with st.expander("고급 설정 · 다른 제품에 적용"):
        if not get_secret("GEMINI_API_KEY"):
            st.text_input("Gemini API 키", type="password", key="api_key_input")
        st.text_input("모델 이름", value=model, key="model_input")
        up_g = st.file_uploader("리뷰 가이드라인 파일 (guideline.json)", type=["json"])
        up_f = st.file_uploader("제품 자료 파일 (facts.csv)", type=["csv"])
        if up_g:
            st.session_state["guideline"] = json.loads(up_g.getvalue().decode("utf-8"))
        if up_f:
            st.session_state["facts"] = read_facts(up_f.getvalue().decode("utf-8-sig"))
        html('<p class="hint">같은 형식의 파일로 바꾸면 다른 제품의 홍보 콘텐츠도 같은 방식으로 만들 수 있습니다.</p>')
    html(f'<div class="copyright">{esc(COPYRIGHT)}<br>제품 정보 출처: ㈜티링크앤주인닷컴 제공 자료 · AI 생성 결과는 게시 전 담당자 검토가 필요합니다.</div>')


def revise(out, g, facts, failed, api_key, model):
    import time
    t0 = time.time()
    with st.spinner("점검에서 걸린 항목만 고쳐 다시 쓰는 중입니다. 약 1~2분 걸립니다."):
        try:
            new = call_gemini(api_key, model, [], build_revision_prompt(g, facts, out["result"], failed, out.get("mode", "brand")))
        except Exception as e:
            st.error(f"다시 쓰기에 실패했습니다: {e}")
            return
    before = sum(c["ok"] for c in audit(out["result"], g, facts, out.get("memo", "")))
    out["history"] = out.get("history", []) + [before]
    out["result"] = new
    out["sec"] = round(time.time() - t0)
    st.session_state["out"] = out
    st.rerun()


def render_result(out, g, facts, api_key="", model=""):
    result, names, images, mode = out["result"], out["names"], out["images"], out.get("mode", "brand")
    checks = audit(result, g, facts, out.get("memo", ""))
    fmap = {f["id"]: f for f in facts}
    b = result.get("blog", {})
    passed = sum(c["ok"] for c in checks)
    failed = [c for c in checks if not c["ok"]]
    raw = json.dumps(result, ensure_ascii=False)
    ph = raw.count("[확인 필요]") + raw.count("[직접 사용 후 작성")

    hist = out.get("history", [])
    html('<div class="sec">결과' + (f' · 다시 쓰기 {len(hist)}회 (점검 통과 {" → ".join(map(str, hist + [passed]))})' if hist else "") + '</div>')
    html('<div class="kpis">'
         f'<div class="kpi"><span>점검 통과</span><b>{passed} / {len(checks)}</b></div>'
         f'<div class="kpi"><span>블로그 본문</span><b>{len(plain(blog_text(b))):,}자</b></div>'
         f'<div class="kpi"><span>채워야 할 곳</span><b>{ph}곳</b></div>'
         f'<div class="kpi"><span>걸린 시간</span><b>{out.get("sec", "-")}초</b></div></div>')
    if failed:
        html(f'<div class="notice">게시 전에 확인할 항목이 {len(failed)}개 있습니다. '
             f'<b>점검 결과</b> 탭에서 내용을 확인하거나, 아래 버튼으로 해당 항목만 고쳐 다시 쓸 수 있습니다.</div>')
        if st.button(f"확인 필요 {len(failed)}개 항목 고쳐서 다시 쓰기", use_container_width=True,
                     disabled=not api_key):
            revise(out, g, facts, failed, api_key, model)

    t1, t2, t3, t4, t5 = st.tabs(["블로그 글", "인스타그램", "점검 결과", "사진 분석 · 근거", "복사 · 내려받기"])
    caps = {p.get("index"): p.get("caption", "") for p in result.get("photos", [])}
    with t1:
        st.markdown(f"### {esc(clean(b.get('title','')))}")
        if mode == "review":
            html(f'<p class="disc">{esc(g.get("광고표기", DISCLOSURE))}</p>')
        st.write(clean(b.get("first_paragraph", "")))
        for s in b.get("sections", []):
            st.markdown(f"#### {esc(clean(s.get('heading','')))}")
            idx = s.get("photo_index")
            if isinstance(idx, int) and 1 <= idx <= len(images):
                st.image(images[idx - 1][0], caption=caps.get(idx, ""), width=640)
            st.write(clean(s.get("body", "")))
            if s.get("fact_ids"):
                html(f'<p class="src">근거 자료 {esc(", ".join(s["fact_ids"]))}</p>')
        st.write(clean(b.get("conclusion", "")))
        st.divider()
        st.text(g["하단정보"])
        st.caption(" ".join(g["태그"]))
    with t2:
        for i, s in enumerate(result.get("instagram", []), 1):
            with st.container(border=True):
                st.markdown(f"**{i}장 · {esc(s.get('headline',''))}**  ({len(s.get('headline',''))}자)")
                st.write(f"{s.get('sub','')}  ({len(s.get('sub',''))}자)")
        st.markdown("**피드 본문**")
        st.write(result.get("instagram_caption", ""))
        st.caption(" ".join(result.get("instagram_hashtags", [])))
    with t3:
        html('<p class="hint">숫자·키워드·금지어·근거는 코드가 자동 점검합니다. 문장의 사실 여부와 어색한 표현은 게시 전에 담당자가 한 번 더 읽어 주세요.</p>')
        render_checks(checks)
        for r in result.get("privacy_risks", []):
            html(f'<div class="chk"><span class="tag ng">개인정보</span><div>{esc(r)}</div></div>')
    with t4:
        st.markdown("**사진별 분석**")
        for p in result.get("photos", []):
            i = p.get("index")
            nm = names[i - 1] if isinstance(i, int) and 0 < i <= len(names) else ""
            st.markdown(f"- 사진 {i} ({esc(nm)}): {esc(p.get('what',''))} → {esc(p.get('section',''))}")
        st.markdown("**기술 차별점과 근거**")
        for p in result.get("points", []):
            with st.container(border=True):
                st.markdown(f"**{esc(p.get('point',''))}**")
                st.write(p.get("why", ""))
                for fid in p.get("fact_ids", []):
                    f = fmap.get(fid)
                    html(f'<p class="src">{fid} · {esc(f["사실"])} ({esc(f["출처"])})</p>' if f
                         else f'<p class="alert">{esc(fid)}: 제품 자료에 없는 근거</p>')
    with t5:
        md = final_blog_markdown(result, g, names, mode)
        c1, c2 = st.columns(2)
        c1.download_button("블로그 원고 내려받기", md, file_name="tlink_blog.md", use_container_width=True)
        c2.download_button("전체 결과 내려받기 (JSON)", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name="tlink_result.json", use_container_width=True)
        html('<p class="hint">원고 오른쪽 위 복사 버튼을 눌러 블로그 편집기에 붙여넣고, [사진 n] 자리에 해당 사진을 넣으세요. 근거 ID 표기는 자동으로 지웠습니다.</p>')
        st.code(md, language="markdown")


if __name__ == "__main__":
    main()
