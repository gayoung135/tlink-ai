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
def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return os.getenv(name, "")


def main():
    st.set_page_config(page_title="티링크 AI 현장사진 홍보콘텐츠 자동생성기", page_icon="📸", layout="wide")
    st.title("📸 티링크 AI 현장사진 홍보콘텐츠 자동생성기")
    st.caption("현장 사진 + 제품 정보 + 업체 리뷰 가이드라인 → 가이드라인을 지킨 블로그·인스타 초안과 자동 검수 결과")

    # ---- 설정 / 데이터
    with st.sidebar:
        st.header("⚙️ 설정")
        secret_key = get_secret("GEMINI_API_KEY")
        api_key = secret_key or st.text_input("Gemini API 키", type="password")
        if secret_key:
            st.success("API 키 연결됨")
        model = st.text_input("모델", value=get_secret("GEMINI_MODEL") or "gemini-2.5-flash")
        st.divider()
        st.subheader("📂 다른 업체·제품에 쓰기")
        up_g = st.file_uploader("가이드라인 (guideline.json)", type=["json"])
        up_f = st.file_uploader("제품 정보 (facts.csv)", type=["csv"])

    g = json.loads(up_g.getvalue().decode("utf-8")) if up_g else default_guideline()
    facts = read_facts(up_f.getvalue().decode("utf-8-sig")) if up_f else default_facts()

    with st.expander(f"📑 근거 데이터 보기 — 제품 정보 {len(facts)}건 · 가이드라인 '{g['제품명']}'"):
        st.dataframe([{k: f[k] for k in ("id", "제품", "사실", "출처")} for f in facts], hide_index=True)
        st.write("**필수 키워드**", ", ".join(g["필수키워드"]))
        st.write("**제목·첫 문단 키워드**", ", ".join(g["제목_첫문단_키워드"]))
        for c in g.get("확인필요_충돌", []):
            st.warning(f"확인 필요: {c['내용']} — {c['이유']}")

    # ---- 입력
    c1, c2 = st.columns([3, 2])
    with c1:
        use_sample = st.toggle("샘플 사진으로 시연하기", value=False)
        if use_sample:
            files = sorted((BASE / "samples").glob("*.jpg"))
            images = [(p.read_bytes(), "image/jpeg") for p in files]
            names = [SAMPLE_LABELS.get(p.stem, p.stem) for p in files]
        else:
            ups = st.file_uploader(f"① 현장 사진 (최대 {MAX_PHOTOS}장)", type=["jpg", "jpeg", "png"],
                                   accept_multiple_files=True)
            ups = (ups or [])[:MAX_PHOTOS]
            images = [(u.getvalue(), u.type) for u in ups]
            names = [Path(u.name).stem for u in ups]
        if images:
            cols = st.columns(len(images))
            for col, (b, _), nm in zip(cols, images, names):
                col.image(b, caption=nm)
    with c2:
        memo = st.text_area("② 현장 메모 (선택)", height=120,
                            placeholder="예) 외근 영업 10명 회사, 휴대폰·인터넷전화 통화를 따로 관리하던 곳")
        st.caption("⚠️ 실제 고객 정보가 담긴 사진은 올리지 마세요. 무료 API는 입력이 서비스 개선에 쓰일 수 있습니다.")
        run = st.button("🚀 콘텐츠 생성", type="primary", use_container_width=True,
                        disabled=not (images and api_key))
        if not api_key:
            st.info("왼쪽 설정에 Gemini API 키를 넣으세요.")

    if run:
        with st.spinner("사진 분석 → 차별점 매칭 → 블로그·인스타 작성 → 자동 검수 중..."):
            try:
                result = call_gemini(api_key, model, images, build_prompt(g, facts, memo, len(images)))
                st.session_state["out"] = {"result": result, "names": names, "images": images}
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    st.error("무료 사용량을 잠시 초과했어요. 1분 뒤 다시 눌러 주세요.")
                else:
                    st.error(f"생성 실패: {msg}")
                return

    out = st.session_state.get("out")
    if not out:
        return
    result, names, images = out["result"], out["names"], out["images"]
    checks = audit(result, g, facts)
    fmap = {f["id"]: f for f in facts}

    st.divider()
    passed = sum(c["ok"] for c in checks)
    st.subheader(f"✅ 자동 검수 {passed}/{len(checks)} 통과")
    for c in checks:
        st.write(("✅ " if c["ok"] else "⚠️ ") + c["label"] + (f" — {c['detail']}" if c["detail"] else ""))
    for r in result.get("privacy_risks", []):
        st.write(f"🔒 개인정보 확인: {r}")

    t1, t2, t3, t4 = st.tabs(["🔍 사진 분석·차별점", "📝 블로그 미리보기", "📱 인스타그램", "⬇️ 내보내기"])
    with t1:
        for p in result.get("photos", []):
            st.write(f"**사진 {p.get('index')}** {p.get('what','')} → *{p.get('section','')}*")
        st.markdown("#### 기술 차별점")
        for p in result.get("points", []):
            with st.container(border=True):
                st.markdown(f"**{p.get('point','')}**")
                st.write(p.get("why", ""))
                for fid in p.get("fact_ids", []):
                    f = fmap.get(fid)
                    st.caption(f"✅ {fid} {f['사실']} — {f['출처']}" if f else f"⚠️ {fid}: 제품 정보에 없는 근거")
    with t2:
        b = result.get("blog", {})
        caps = {p.get("index"): p.get("caption", "") for p in result.get("photos", [])}
        st.markdown(f"## {b.get('title','')}")
        st.write(b.get("first_paragraph", ""))
        for s in b.get("sections", []):
            st.markdown(f"### {s.get('heading','')}")
            idx = s.get("photo_index")
            if isinstance(idx, int) and 1 <= idx <= len(images):
                st.image(images[idx - 1][0], caption=caps.get(idx, ""))
            st.write(s.get("body", ""))
            if s.get("fact_ids"):
                st.caption("근거: " + ", ".join(s["fact_ids"]))
        st.write(b.get("conclusion", ""))
        st.divider()
        st.text(g["하단정보"])
        st.caption(" ".join(g["태그"]))
    with t3:
        slides = result.get("instagram", [])
        st.dataframe([{"장": i, "헤드카피": s.get("headline", ""), "글자": len(s.get("headline", "")),
                       "서브카피": s.get("sub", ""), "글자수": len(s.get("sub", ""))}
                      for i, s in enumerate(slides, 1)], hide_index=True)
        st.write(result.get("instagram_caption", ""))
        st.write(" ".join(result.get("instagram_hashtags", [])))
    with t4:
        md = final_blog_markdown(result, g, names)
        st.download_button("블로그 원고 (.md)", md, file_name="tlink_blog.md")
        st.download_button("전체 결과 (.json)", json.dumps(result, ensure_ascii=False, indent=2),
                           file_name="tlink_result.json")
        st.code(md, language="markdown")


if __name__ == "__main__":
    main()
