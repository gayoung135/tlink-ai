"""티링크 AI 현장사진 홍보콘텐츠 자동생성기 (MVP)
현장 사진 + 제품 정보 시트(products.csv) → 사진 분석 → 차별점 매칭 → 블로그·인스타 초안 + 검수 체크리스트
실행: streamlit run app.py
"""
import csv
import json
import os
import re
from pathlib import Path

import streamlit as st

PLACEHOLDER = "[확인 필요]"
HEAD_LIMIT, SUB_LIMIT, TITLE_LIMIT = 20, 45, 30
SHEET_PATH = Path(__file__).with_name("products.csv")


# ---------- 제품 정보 시트 ----------
def load_products(path=SHEET_PATH):
    with open(path, encoding="utf-8-sig") as f:
        return [row for row in csv.DictReader(f)]


def sheet_text(rows):
    """AI에 넘길 근거 원문. 한 줄 = 한 사실."""
    lines = []
    for r in rows:
        for key in ("특허", "차별점", "설치환경", "추가정보"):
            val = (r.get(key) or "").strip()
            if val:
                lines.append(f"[{r['제품명']}] {key}: {val}")
    return "\n".join(lines)


# ---------- 코드 레벨 검증 (AI 결과를 그대로 믿지 않음) ----------
def normalize(s):
    return re.sub(r"\s+", "", s or "")


def check_evidence(points, source):
    """AI가 댄 근거 문장이 시트 원문에 실제로 있는지 확인."""
    src = normalize(source)
    for p in points:
        ev = normalize(p.get("evidence", ""))
        p["verified"] = bool(ev) and ev in src
    return points


def check_lengths(slides, title):
    issues = []
    for i, s in enumerate(slides, 1):
        h, sub = s.get("headline", ""), s.get("sub", "")
        if len(h) > HEAD_LIMIT:
            issues.append(f"{i}장 헤드카피 {len(h)}자 (≤{HEAD_LIMIT})")
        if len(sub) > SUB_LIMIT:
            issues.append(f"{i}장 서브카피 {len(sub)}자 (≤{SUB_LIMIT})")
    if len(title) > TITLE_LIMIT:
        issues.append(f"블로그 제목 {len(title)}자 (≤{TITLE_LIMIT})")
    return issues


def build_prompt(products, source, memo):
    return f"""너는 정보통신 업체 '티링크'의 팩트 기반 B2B 마케터야.
첨부한 현장 사진과 아래 [제품 정보 시트]만 근거로 홍보 콘텐츠 초안을 만들어.

[설치 제품] {", ".join(products)}
[현장 메모] {memo or "없음"}

[제품 정보 시트]
{source}

규칙:
1. 시트에 없는 성능·수치·인증·고객사명·가격은 절대 만들지 말고 "{PLACEHOLDER}"로 표기.
2. 차별점(points)의 evidence에는 시트 문장을 한 글자도 바꾸지 말고 그대로 복사.
3. 사진에서 사람 얼굴, 상호·간판, 전화번호, 문서 글씨가 보이면 privacy_risks에 적어.
4. 최고·최초·유일·1위 같은 근거 없는 최상급 표현 금지.
5. 인스타 카드: 정확히 5장, headline {HEAD_LIMIT}자 이내, sub {SUB_LIMIT}자 이내 (공백 포함).
6. 블로그 제목 {TITLE_LIMIT}자 이내, 본문은 ### 소제목 3개 이상, 600~1000자.

아래 JSON 형식으로만 답해:
{{
  "scene": {{"environment": "설치 환경 한 줄", "visible_items": ["사진에 보이는 장비"], "pain_point": "이 현장의 고충 추정 한 줄"}},
  "points": [{{"product": "제품명", "point": "차별점 요약", "evidence": "시트 원문 그대로", "why": "이 현장에 맞는 이유"}}],
  "instagram": [{{"headline": "", "sub": ""}}],
  "instagram_caption": "피드 본문",
  "hashtags": ["#..."],
  "blog": {{"title": "", "body": "마크다운 본문"}},
  "privacy_risks": ["..."]
}}"""


def call_gemini(api_key, model, image_bytes, mime, prompt):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.4),
    )
    return json.loads(resp.text)


def to_markdown(r):
    md = [f"# 현장 홍보 콘텐츠 초안\n", f"**현장 분석**: {r['scene'].get('environment','')}\n"]
    md.append("## 인스타그램 카드뉴스")
    for i, s in enumerate(r.get("instagram", []), 1):
        md.append(f"{i}. **{s.get('headline','')}** — {s.get('sub','')}")
    md.append(f"\n{r.get('instagram_caption','')}\n\n{' '.join(r.get('hashtags', []))}\n")
    md.append(f"## 블로그\n### {r['blog'].get('title','')}\n\n{r['blog'].get('body','')}")
    return "\n".join(md)


# ---------- 화면 ----------
def main():
    st.set_page_config(page_title="티링크 AI 현장사진 홍보콘텐츠 자동생성기", layout="wide")
    st.title("📸 티링크 AI 현장사진 홍보콘텐츠 자동생성기")
    st.caption("현장 사진 한 장 + 제품 정보 시트 → 블로그·인스타 초안과 검수 체크리스트")

    with st.sidebar:
        st.header("설정")
        api_key = st.text_input("Gemini API 키", value=os.getenv("GEMINI_API_KEY", ""), type="password")
        model = st.text_input("모델명", value=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                              help="Google AI Studio에서 사용 가능한 모델명으로 바꾸세요.")
        st.divider()
        st.write("제품 정보 시트:", SHEET_PATH.name)

    rows = load_products()
    names = [r["제품명"] for r in rows]

    col1, col2 = st.columns([1, 1])
    with col1:
        photo = st.file_uploader("① 현장 사진 업로드", type=["jpg", "jpeg", "png"])
        if photo:
            st.image(photo, use_container_width=True)
    with col2:
        chosen = st.multiselect("② 설치 제품 선택", names, default=names[:1])
        memo = st.text_area("③ 현장 메모 (선택)", placeholder="예) 공장 사무동 단자함, 공간 협소")
        run = st.button("🚀 콘텐츠 생성", type="primary", disabled=not (photo and chosen and api_key))
        if not api_key:
            st.info("왼쪽에 Gemini API 키를 입력하세요.")

    if not run:
        return

    selected = [r for r in rows if r["제품명"] in chosen]
    source = sheet_text(selected)
    with st.spinner("사진 분석 → 차별점 매칭 → 콘텐츠 생성 중..."):
        try:
            result = call_gemini(api_key, model, photo.getvalue(), photo.type, build_prompt(chosen, source, memo))
        except Exception as e:  # 시연 중 오류도 화면에 보이게
            st.error(f"생성 실패: {e}")
            return

    points = check_evidence(result.get("points", []), source)
    slides = result.get("instagram", [])
    blog = result.get("blog", {"title": "", "body": ""})
    length_issues = check_lengths(slides, blog.get("title", ""))
    all_text = json.dumps(result, ensure_ascii=False)
    placeholder_count = all_text.count(PLACEHOLDER)

    st.divider()
    st.subheader("1. 현장 사진 분석")
    sc = result.get("scene", {})
    st.write(f"**설치 환경**: {sc.get('environment','')}")
    st.write(f"**보이는 장비**: {', '.join(sc.get('visible_items', []))}")
    st.write(f"**현장 고충(추정)**: {sc.get('pain_point','')}")

    st.subheader("2. 기술 차별점 매칭")
    for p in points:
        badge = "✅ 시트 근거 확인" if p["verified"] else "⚠️ 시트에 없는 근거 — 사용 금지"
        with st.container(border=True):
            st.markdown(f"**{p.get('product','')} · {p.get('point','')}**  \n{badge}")
            st.caption(f"근거: {p.get('evidence','')}")
            st.write(p.get("why", ""))

    tab1, tab2 = st.tabs(["📱 인스타그램", "📝 블로그"])
    with tab1:
        st.table([{"장": i, "헤드카피": s.get("headline", ""), "글자": len(s.get("headline", "")),
                   "서브카피": s.get("sub", ""), "글자 ": len(s.get("sub", ""))} for i, s in enumerate(slides, 1)])
        st.write(result.get("instagram_caption", ""))
        st.write(" ".join(result.get("hashtags", [])))
    with tab2:
        st.markdown(f"### {blog.get('title','')} ({len(blog.get('title',''))}자)")
        st.markdown(blog.get("body", ""))

    st.subheader("3. 검수 체크리스트")
    unverified = [p for p in points if not p["verified"]]
    checks = {
        f"차별점 근거 {len(points) - len(unverified)}/{len(points)}건 시트와 일치": not unverified,
        f"글자 수 제한 {'통과' if not length_issues else '초과: ' + ', '.join(length_issues)}": not length_issues,
        f"카드뉴스 {len(slides)}장 (5장 필요)": len(slides) == 5,
        f"미확인 정보 {placeholder_count}곳 [확인 필요] 표시 — 게시 전 채우기": placeholder_count == 0,
    }
    for label, ok in checks.items():
        st.write(("✅ " if ok else "⚠️ ") + label)
    for risk in result.get("privacy_risks", []):
        st.write(f"🔒 개인정보 확인: {risk}")

    st.download_button("⬇️ 초안 다운로드 (.md)", to_markdown(result), file_name="tlink_content.md")


if __name__ == "__main__":
    main()
