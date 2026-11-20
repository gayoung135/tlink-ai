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
def build_prompt(g, facts, memo, n_photos):
    conflicts = "\n".join(f"- {c['내용']}: {c['이유']}" for c in g.get("확인필요_충돌", [])) or "- 없음"
    missions = "\n".join(f"{i}. {m}" for i, m in enumerate(g["미션"], 1))
    return f"""너는 '{g['업체명']}'에 입사한 10년 차 B2B 콘텐츠 마케터야.
첨부한 현장 사진 {n_photos}장과 아래 [제품 정보], [리뷰 가이드라인]만 근거로 네이버 블로그 리뷰와 인스타그램 카드뉴스를 만들어.

[현장 메모] {memo or '없음'}

[제품 정보] (각 줄 앞의 [F번호]가 근거 ID)
{facts_block(facts)}

[리뷰 가이드라인]
- 홍보 제품: {g['제품명']}
- 리뷰 컨셉: {g['리뷰컨셉']}
- 필수 키워드(제목과 본문에 반드시 포함): {', '.join(g['필수키워드'])}
- 제목과 첫 문단에 넣을 키워드: {', '.join(g['제목_첫문단_키워드'])}
- 서브 키워드(자연스럽게): {', '.join(g['서브키워드'])}
- 추천 본문 구성(이 순서로 소제목): {' → '.join(g['추천구성'])}
- 리뷰 미션:
{missions}

[사용 금지]
- 단어: {', '.join(g['사용금지'])}
- 업체 확인 전 사용 금지 정보:
{conflicts}

규칙:
1. 제품 정보에 없는 기능·수치·가격·고객사·인증은 절대 만들지 마. 필요한 자리에는 "[확인 필요]"라고 써.
2. 제품 기능을 말하는 문장마다 근거 ID를 fact_ids에 적어. 근거가 없으면 그 문장을 쓰지 마.
3. 숫자는 제품 정보에 있는 숫자만 써. 가격을 쓰면 조건(상담원 1인 기준, 설정비, VAT 별도, 상담 후 확정)을 빠짐없이 함께 써.
4. 사진마다 무슨 화면/현장인지 판단하고, 블로그 소제목 중 어디에 넣을지 정해. 사진에 없는 내용을 사진 설명으로 지어내지 마.
5. 사진에 사람 얼굴, 실제 고객명·전화번호, 상호가 보이면 privacy_risks에 적어.
6. 인스타 카드뉴스는 정확히 5장, headline {HEAD_LIMIT}자 이내, sub {SUB_LIMIT}자 이내(공백 포함).
7. 블로그 본문은 사용 후기 형식으로, 소제목 본문을 합쳐 {g.get('블로그_최소글자', 1500)}자 이상.
8. 하단 홈페이지·문의 정보는 앱이 자동으로 붙이니 쓰지 마.

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


def call_gemini(api_key, model, images, prompt):
    from google import genai
    from google.genai import types

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


def audit(result, g, facts):
    blog = result.get("blog", {})
    title, first = blog.get("title", ""), blog.get("first_paragraph", "")
    body = blog_text(blog)
    fact_ids = {f["id"] for f in facts}
    source_text = facts_block(facts) + json.dumps(g, ensure_ascii=False)
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


def final_blog_markdown(result, g, photo_names):
    b = result["blog"]
    out = [f"# {b.get('title','')}", "", b.get("first_paragraph", ""), ""]
    caps = {p.get("index"): p.get("caption", "") for p in result.get("photos", [])}
    for s in b.get("sections", []):
        out += [f"## {s.get('heading','')}", ""]
        idx = s.get("photo_index")
        if isinstance(idx, int) and 1 <= idx <= len(photo_names):
            out += [f"[사진 {idx}: {photo_names[idx-1]}] {caps.get(idx,'')}", ""]
        out += [s.get("body", ""), ""]
    out += [b.get("conclusion", ""), "", "---", g["하단정보"], "", " ".join(g["태그"])]
    return "\n".join(out)


# ---------------------------------------------------------------- 화면
BRAND = "#1F3FE5"

CSS = f"""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
html, body, [class*="css"], .stMarkdown, button, input, textarea {{
  font-family: 'Pretendard', -apple-system, 'Malgun Gothic', sans-serif !important;
}}
[data-testid="stToolbar"], [data-testid="stDecoration"], footer {{ display: none !important; }}
.block-container {{ max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem; }}
.brandbar {{ display:flex; align-items:center; gap:10px; font-size:13px; color:#6B7280; letter-spacing:.02em; }}
.brandbar b {{ color:{BRAND}; font-size:15px; letter-spacing:.06em; }}
.hero h1 {{ font-size:30px; font-weight:800; margin:.4rem 0 .3rem; color:#0F172A; letter-spacing:-.02em; }}
.hero p {{ color:#4B5563; font-size:15.5px; margin:0 0 1.2rem; }}
.flow {{ display:flex; gap:8px; margin: 0 0 1.6rem; flex-wrap:wrap; }}
.flow span {{ font-size:13px; padding:6px 12px; border-radius:999px; background:#F1F4FB; color:#374151; }}
.flow span b {{ color:{BRAND}; margin-right:6px; }}
.step {{ font-size:12px; font-weight:700; color:{BRAND}; letter-spacing:.08em; margin:0; }}
.step-title {{ font-size:19px; font-weight:700; color:#111827; margin:.15rem 0 .2rem; }}
.step-desc {{ font-size:14px; color:#6B7280; margin:0 0 .8rem; }}
.badge {{ display:inline-block; font-size:12px; font-weight:700; padding:2px 9px; border-radius:6px; margin-right:8px; min-width:58px; text-align:center; }}
.ok {{ background:#E8F5EE; color:#167A47; }}
.ng {{ background:#FDF1E3; color:#B45309; }}
.chk {{ padding:9px 2px; border-bottom:1px solid #EEF0F4; font-size:14.5px; color:#1F2937; }}
.chk small {{ color:#6B7280; margin-left:6px; }}
.src {{ font-size:13px; color:#6B7280; padding:3px 0; }}
.src b {{ color:{BRAND}; font-weight:600; margin-right:4px; }}
.warn {{ font-size:13px; color:#B45309; padding:3px 0; }}
.note {{ font-size:13px; color:#6B7280; }}
div.stButton > button[kind="primary"] {{ height:52px; font-size:16px; font-weight:700; border-radius:10px; }}
</style>
"""


def esc(t):
    import html
    return html.escape(str(t or ""))


def step_header(no, title, desc):
    st.markdown(f'<p class="step">STEP {no}</p><p class="step-title">{esc(title)}</p>'
                f'<p class="step-desc">{esc(desc)}</p>', unsafe_allow_html=True)


def render_checks(checks):
    rows = []
    for c in checks:
        cls, word = ("ok", "통과") if c["ok"] else ("ng", "확인 필요")
        detail = f"<small>{esc(c['detail'])}</small>" if c["detail"] else ""
        rows.append(f'<div class="chk"><span class="badge {cls}">{word}</span>{esc(c["label"])}{detail}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return os.getenv(name, "")


def main():
    import time

    st.set_page_config(page_title="TLINK 현장사진 홍보콘텐츠 생성기", layout="centered",
                       initial_sidebar_state="collapsed")
    st.markdown(CSS, unsafe_allow_html=True)

    # ---- 헤더
    st.markdown(
        '<div class="brandbar"><b>T·LINK</b> 마케팅 콘텐츠 자동화</div>'
        '<div class="hero"><h1>현장사진 홍보콘텐츠 생성기</h1>'
        '<p>현장 사진을 올리면 티링크 제품 자료와 리뷰 가이드라인을 근거로 블로그 리뷰와 인스타그램 카드뉴스를 만들고, 게시 전 검수까지 끝냅니다.</p></div>'
        '<div class="flow"><span><b>1</b>사진 선택</span><span><b>2</b>현장 정보 입력</span>'
        '<span><b>3</b>생성</span><span><b>4</b>검수 결과 확인 후 복사</span></div>',
        unsafe_allow_html=True)

    # ---- 고급 설정 값 (맨 아래 펼침 메뉴에서 바꿈)
    api_key = get_secret("GEMINI_API_KEY") or st.session_state.get("api_key_input", "")
    model = st.session_state.get("model_input") or get_secret("GEMINI_MODEL") or "gemini-2.5-flash"
    g = st.session_state.get("guideline") or default_guideline()
    facts = st.session_state.get("facts") or default_facts()

    # ---- STEP 1
    with st.container(border=True):
        step_header(1, "현장 사진 선택", "시공·사용 현장이나 제품 화면 사진을 최대 5장까지 올립니다. 처음이라면 샘플 사진으로 바로 시험해 보세요.")
        mode = st.radio("사진 선택 방식", ["샘플 사진 사용 (티링크 제품 화면 5장)", "직접 사진 올리기"],
                        horizontal=True, label_visibility="collapsed")
        if mode.startswith("샘플"):
            files = sorted((BASE / "samples").glob("*.jpg"))
            images = [(p.read_bytes(), "image/jpeg") for p in files]
            names = [SAMPLE_LABELS.get(p.stem, p.stem) for p in files]
        else:
            ups = st.file_uploader("JPG, PNG 파일", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
            ups = (ups or [])[:MAX_PHOTOS]
            images = [(u.getvalue(), u.type) for u in ups]
            names = [Path(u.name).stem for u in ups]
            st.markdown('<p class="note">실제 고객 이름·전화번호·얼굴이 보이는 사진은 올리지 마세요.</p>',
                        unsafe_allow_html=True)
        if images:
            cols = st.columns(len(images))
            for col, (b, _), nm in zip(cols, images, names):
                col.image(b, caption=nm)

    # ---- STEP 2
    with st.container(border=True):
        step_header(2, "현장 정보 입력 (선택)", "어떤 고객의 어떤 문제를 해결한 현장인지 한두 줄로 적으면 내용이 더 구체적으로 나옵니다.")
        memo = st.text_area("현장 메모", height=90, label_visibility="collapsed",
                            placeholder="예) 외근 영업사원 10명 회사. 휴대폰과 사무실 인터넷전화 통화를 따로 관리해 고객 이력이 흩어져 있었음")

    # ---- STEP 3
    with st.container(border=True):
        step_header(3, "콘텐츠 생성", f"'{g['제품명']}' 리뷰 가이드라인과 제품 자료 {len(facts)}건만 근거로 작성합니다. 30초~1분 정도 걸립니다.")
        run = st.button("블로그·인스타그램 콘텐츠 생성하기", type="primary", use_container_width=True,
                        disabled=not (images and api_key))
        if not images:
            st.markdown('<p class="note">STEP 1에서 사진을 먼저 선택하세요.</p>', unsafe_allow_html=True)
        elif not api_key:
            st.markdown('<p class="warn">API 키가 설정되지 않았습니다. 페이지 아래 고급 설정에서 입력하세요.</p>',
                        unsafe_allow_html=True)

    if run:
        t0 = time.time()
        with st.spinner("사진 분석 → 제품 차별점 연결 → 원고 작성 → 검수 중입니다"):
            try:
                result = call_gemini(api_key, model, images, build_prompt(g, facts, memo, len(images)))
                st.session_state["out"] = {"result": result, "names": names, "images": images,
                                           "sec": round(time.time() - t0)}
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    st.error("무료 사용량을 잠시 초과했습니다. 1분 뒤 다시 시도해 주세요.")
                else:
                    st.error(f"생성에 실패했습니다: {msg}")

    out = st.session_state.get("out")
    if out:
        render_result(out, g, facts)

    # ---- 맨 아래: 근거 데이터 / 고급 설정
    st.write("")
    with st.expander("근거 데이터 보기 (제품 자료 · 리뷰 가이드라인)"):
        st.dataframe([{k: f[k] for k in ("id", "제품", "사실", "출처")} for f in facts], hide_index=True)
        st.markdown(f"**필수 키워드** {esc(', '.join(g['필수키워드']))}  \n"
                    f"**제목·첫 문단 키워드** {esc(', '.join(g['제목_첫문단_키워드']))}")
        for c in g.get("확인필요_충돌", []):
            st.markdown(f'<p class="warn">사용 보류: {esc(c["내용"])} — {esc(c["이유"])}</p>', unsafe_allow_html=True)
    with st.expander("고급 설정 · 다른 제품에 적용"):
        if not get_secret("GEMINI_API_KEY"):
            st.text_input("Gemini API 키", type="password", key="api_key_input")
        st.text_input("모델", value=model, key="model_input")
        up_g = st.file_uploader("리뷰 가이드라인 파일 (guideline.json)", type=["json"])
        up_f = st.file_uploader("제품 자료 파일 (facts.csv)", type=["csv"])
        if up_g:
            st.session_state["guideline"] = json.loads(up_g.getvalue().decode("utf-8"))
        if up_f:
            st.session_state["facts"] = read_facts(up_f.getvalue().decode("utf-8-sig"))
        st.markdown('<p class="note">같은 형식의 파일로 바꾸면 다른 제품·업체의 홍보 콘텐츠도 같은 방식으로 만들 수 있습니다.</p>',
                    unsafe_allow_html=True)


def render_result(out, g, facts):
    result, names, images = out["result"], out["names"], out["images"]
    checks = audit(result, g, facts)
    fmap = {f["id"]: f for f in facts}
    b = result.get("blog", {})
    passed = sum(c["ok"] for c in checks)
    ph = json.dumps(result, ensure_ascii=False).count("[확인 필요]")

    st.write("")
    st.markdown('<p class="step">RESULT</p><p class="step-title">생성 결과</p>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("자동 검수", f"{passed} / {len(checks)}")
    m2.metric("블로그 본문", f"{len(plain(blog_text(b))):,}자")
    m3.metric("확인 필요 항목", f"{ph}곳")
    m4.metric("소요 시간", f"{out.get('sec', '-')}초")

    t1, t2, t3, t4, t5 = st.tabs(["블로그 원고", "인스타그램", "사진 분석 · 근거", "검수 상세", "내보내기"])
    caps = {p.get("index"): p.get("caption", "") for p in result.get("photos", [])}
    with t1:
        st.markdown(f"### {esc(b.get('title',''))}")
        st.write(b.get("first_paragraph", ""))
        for s in b.get("sections", []):
            st.markdown(f"#### {esc(s.get('heading',''))}")
            idx = s.get("photo_index")
            if isinstance(idx, int) and 1 <= idx <= len(images):
                st.image(images[idx - 1][0], caption=caps.get(idx, ""))
            st.write(s.get("body", ""))
            if s.get("fact_ids"):
                st.markdown(f'<p class="src">근거 {esc(", ".join(s["fact_ids"]))}</p>', unsafe_allow_html=True)
        st.write(b.get("conclusion", ""))
        st.divider()
        st.text(g["하단정보"])
        st.caption(" ".join(g["태그"]))
    with t2:
        slides = result.get("instagram", [])
        st.dataframe([{"장": i, "헤드카피": s.get("headline", ""), "글자": len(s.get("headline", "")),
                       "서브카피": s.get("sub", ""), "글자 수": len(s.get("sub", ""))}
                      for i, s in enumerate(slides, 1)], hide_index=True, use_container_width=True)
        st.markdown("**피드 본문**")
        st.write(result.get("instagram_caption", ""))
        st.caption(" ".join(result.get("instagram_hashtags", [])))
    with t3:
        st.markdown("**사진별 분석**")
        for p in result.get("photos", []):
            nm = names[p["index"] - 1] if isinstance(p.get("index"), int) and 0 < p["index"] <= len(names) else ""
            st.markdown(f"- 사진 {p.get('index')} ({esc(nm)}): {esc(p.get('what',''))} → *{esc(p.get('section',''))}*")
        st.markdown("**기술 차별점과 근거**")
        for p in result.get("points", []):
            with st.container(border=True):
                st.markdown(f"**{esc(p.get('point',''))}**")
                st.write(p.get("why", ""))
                for fid in p.get("fact_ids", []):
                    f = fmap.get(fid)
                    if f:
                        st.markdown(f'<p class="src"><b>{fid}</b>{esc(f["사실"])} · {esc(f["출처"])}</p>',
                                    unsafe_allow_html=True)
                    else:
                        st.markdown(f'<p class="warn">{esc(fid)}: 제품 자료에 없는 근거</p>', unsafe_allow_html=True)
    with t4:
        render_checks(checks)
        for r in result.get("privacy_risks", []):
            st.markdown(f'<p class="warn">개인정보 확인: {esc(r)}</p>', unsafe_allow_html=True)
    with t5:
        md = final_blog_markdown(result, g, names)
        c1, c2 = st.columns(2)
        c1.download_button("블로그 원고 내려받기 (.md)", md, file_name="tlink_blog.md", use_container_width=True)
        c2.download_button("전체 결과 내려받기 (.json)", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name="tlink_result.json", use_container_width=True)
        st.caption("아래 원고를 복사해 블로그 편집기에 붙여넣고, [사진 n] 자리에 해당 사진을 넣으면 됩니다.")
        st.code(md, language="markdown")


if __name__ == "__main__":
    main()
