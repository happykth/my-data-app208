# ============================================================
# 날짜별 박스오피스 - 스트림릿 앱 (KOBIS 일별 박스오피스 API 사용)
# ============================================================
# 이 앱은 영화진흥위원회(KOBIS)의 일별 박스오피스 API를 호출해서
# 달력에서 고른 날짜의 박스오피스 순위를 보여줍니다.
# 고를 수 있는 가장 늦은 날짜는 '어제(한국 시간 기준)'까지입니다. 오늘 것은 아직 집계 전이거든요.
#
# [배포 전 준비사항]
# 1. Streamlit Cloud 접속 -> 앱 설정(Settings) -> Secrets 메뉴로 이동
# 2. 아래처럼 인증키를 등록하세요. (따옴표 포함해서 그대로)
#
#    KOBIS_KEY = "여기에_발급받은_인증키"
#
# 절대로 인증키를 이 코드 파일 안에 직접 적지 마세요!
# ============================================================

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # 파이썬 기본 내장 모듈(설치 불필요) - 시간대 계산용

# ------------------------------------------------------------
# 0. 기본 화면 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="날짜별 박스오피스",
    page_icon="🎬",
    layout="wide",
)

# 앱 전체에 쓸 따뜻한 색 팔레트 (그래프, 카드 등에서 재사용)
WARM_COLORS = ["#E07A5F", "#F2CC8F", "#81B29A", "#F4A261", "#BC6C25"]

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"


# ------------------------------------------------------------
# 1. '어제 날짜(한국 시간 기준)' 계산하기
# ------------------------------------------------------------
# 배포 서버의 시계는 한국 시간이 아닐 수 있으므로,
# 반드시 Asia/Seoul 시간대를 기준으로 '지금'을 구한 다음 하루를 빼야 합니다.
def get_yesterday_kst():
    """한국 시간(KST) 기준으로 '어제' 날짜(date 객체)를 반환합니다.
    달력에서 고를 수 있는 가장 늦은 날짜로도 사용합니다. (오늘 것은 아직 집계 전)"""
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.date()


# ------------------------------------------------------------
# 2. KOBIS API 호출 함수 (결과를 1시간 동안 기억함 = 캐시)
# ------------------------------------------------------------
# st.cache_data(ttl=3600)을 붙이면, 같은 target_dt로 다시 요청이 와도
# 1시간(3600초) 안에는 실제 API를 다시 부르지 않고 저장해둔 결과를 재사용합니다.
@st.cache_data(ttl=3600)
def fetch_box_office(target_dt: str, api_key: str):
    """
    KOBIS 일별 박스오피스 API를 호출합니다.
    성공하면 (영화 목록 리스트, None)을 반환하고,
    실패하면 (None, "사용자에게 보여줄 한국어 안내 문구")를 반환합니다.
    """
    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 2-1. 네트워크 요청 자체가 실패하는 경우 (타임아웃, 연결 끊김 등)
    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return None, (
            "박스오피스 서버에 연결하지 못했습니다. "
            "인터넷 연결 상태를 확인하시거나 잠시 후 다시 시도해 주세요."
        )

    # 2-2. 응답이 200이 아닌 경우 (서버 오류 등)
    if response.status_code != 200:
        return None, (
            f"박스오피스 서버가 오류를 반환했습니다. (상태 코드: {response.status_code}) "
            "잠시 후 다시 시도해 주세요."
        )

    # 2-3. 응답 본문이 JSON 형식이 아닌 경우
    try:
        data = response.json()
    except ValueError:
        return None, "서버 응답을 해석할 수 없습니다. 잠시 후 다시 시도해 주세요."

    # 2-4. 인증키가 틀렸을 때 등, KOBIS가 faultInfo 상자를 보내는 경우
    # (문서에 따르면 이 경우에도 상태 코드는 200이라서 별도로 확인해야 함)
    if "faultInfo" in data:
        fault = data["faultInfo"]
        message = fault.get("message", "알 수 없는 오류")
        return None, (
            f"KOBIS API 오류: {message}\n\n"
            "→ Streamlit Cloud의 Secrets에 등록한 KOBIS_KEY 값이 정확한지 확인해 주세요."
        )

    # 2-5. 정상 구조인지 확인 (boxOfficeResult가 없는 경우 방어)
    box_office_result = data.get("boxOfficeResult")
    if not box_office_result:
        return None, "서버 응답에서 박스오피스 결과를 찾을 수 없습니다. 잠시 후 다시 시도해 주세요."

    movie_list = box_office_result.get("dailyBoxOfficeList", [])

    # 2-6. 영화 목록이 비어 있는 경우 (예: 너무 이른 날짜, 아직 집계 전인 날짜 등)
    # 이건 진짜 '오류'는 아니라서 에러 메시지 없이 빈 목록만 돌려주고,
    # 화면을 그리는 쪽(main 함수)에서 "그날은 아직 집계 전입니다"라고 안내합니다.
    return movie_list, None


# ------------------------------------------------------------
# 3. 문자열 숫자를 진짜 숫자(int)로 바꾸는 전처리 함수
# ------------------------------------------------------------
# KOBIS API는 관객수, 스크린수 등 모든 숫자를 문자열("12345")로 내려줍니다.
# 정렬이나 그래프에 쓰려면 반드시 진짜 숫자(int)로 바꿔줘야 합니다.
def to_dataframe(movie_list):
    df = pd.DataFrame(movie_list)

    # rankInten(순위 증감)은 음수도 올 수 있어서 함께 숫자로 변환합니다.
    numeric_columns = ["rank", "rankInten", "audiCnt", "audiAcc", "scrnCnt", "showCnt"]
    for col in numeric_columns:
        if col in df.columns:
            # errors="coerce": 혹시 이상한 값이 섞여 있어도 앱이 죽지 않고 NaN 처리 후 0으로 채움
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


# ------------------------------------------------------------
# 3-1. 순위 변동을 화살표 글자로 바꾸는 함수
# ------------------------------------------------------------
# rankInten이 양수면 순위가 오른 것(▲), 음수면 내린 것(▼), 0이면 그대로(-)입니다.
def rank_change_text(rank_inten: int) -> str:
    if rank_inten > 0:
        return f"▲ {rank_inten}"
    elif rank_inten < 0:
        return f"▼ {abs(rank_inten)}"
    else:
        return "-"


# ------------------------------------------------------------
# 3-2. 순위 변동 글자에 색을 입히는 함수 (오른 건 빨강, 내린 건 파랑)
# ------------------------------------------------------------
def rank_change_color(rank_change: str) -> str:
    if rank_change.startswith("▲"):
        return "color: #D64545; font-weight: bold;"
    elif rank_change.startswith("▼"):
        return "color: #3A6EA5; font-weight: bold;"
    else:
        return ""


# ------------------------------------------------------------
# 4. 화면 그리기
# ------------------------------------------------------------
def main():
    st.title("🎬 날짜별 박스오피스")

    # 4-0. 달력으로 날짜 고르기
    # 고를 수 있는 가장 늦은 날짜는 '어제(한국 시간 기준)'까지입니다. 오늘 것은 아직 집계 전이라서요.
    latest_selectable_date = get_yesterday_kst()
    selected_date = st.date_input(
        "조회할 날짜를 선택하세요",
        value=latest_selectable_date,
        max_value=latest_selectable_date,
    )
    target_dt = selected_date.strftime("%Y%m%d")
    display_date = f"{target_dt[:4]}년 {target_dt[4:6]}월 {target_dt[6:]}일"
    st.caption(f"기준일: {display_date}")

    # 4-1. Secrets에서 인증키 불러오기
    api_key = st.secrets.get("KOBIS_KEY")
    if not api_key:
        st.error(
            "KOBIS_KEY가 설정되어 있지 않습니다.\n\n"
            "→ Streamlit Cloud의 앱 설정(Settings) > Secrets 메뉴에서 "
            '`KOBIS_KEY = "발급받은_인증키"` 형태로 등록해 주세요.'
        )
        return

    # 4-2. 데이터 불러오기 (실패 시 안내 문구 출력)
    with st.spinner("박스오피스 정보를 불러오는 중입니다..."):
        movie_list, error_message = fetch_box_office(target_dt, api_key)

    if error_message:
        st.warning(error_message)
        return

    # 영화 목록이 비어 있으면(에러는 아니지만 데이터가 없으면) 집계 전이라고 안내합니다.
    if not movie_list:
        st.info(f"{display_date}는 아직 집계 전입니다. 다른 날짜를 선택해 주세요.")
        return

    df = to_dataframe(movie_list)

    # ------------------------------------------------------------
    # 4-3. 1위 영화 - 지표 카드 세 장
    # ------------------------------------------------------------
    top1 = df.iloc[0]
    st.subheader(f"👑 1위 : {top1['movieNm']}")

    col1, col2, col3 = st.columns(3)
    col1.metric("해당일 관객수", f"{top1['audiCnt']:,} 명")
    col2.metric("누적 관객수", f"{top1['audiAcc']:,} 명")
    col3.metric("스크린수", f"{top1['scrnCnt']:,} 개")

    st.divider()

    # ------------------------------------------------------------
    # 4-4. 관객수 상위 5편 - 막대그래프
    # ------------------------------------------------------------
    st.subheader("📊 관객수 상위 5편")

    top5 = df.sort_values("audiCnt", ascending=False).head(5)
    fig = px.bar(
        top5,
        x="movieNm",
        y="audiCnt",
        text="audiCnt",
        color="movieNm",
        color_discrete_sequence=WARM_COLORS,
        labels={"movieNm": "영화명", "audiCnt": "관객수(명)"},
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    fig.update_layout(showlegend=False, xaxis_title=None, yaxis_title="관객수(명)")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ------------------------------------------------------------
    # 4-5. 전체 순위표
    # ------------------------------------------------------------
    st.subheader("📋 전체 순위")
    st.caption("🔺 빨강 화살표 = 전날보다 순위 상승 · 🔻 파랑 화살표 = 전날보다 순위 하락 · 🏆 = 누적관객 100만 명 이상")

    table_df = df[["rank", "rankInten", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()

    # 순위 변동을 화살표 글자로 바꾸기 (예: ▲ 2, ▼ 1, -)
    table_df["순위변동"] = table_df["rankInten"].apply(rank_change_text)

    # 누적관객이 100만 명을 넘은 영화는 영화명 옆에 트로피 이모지를 붙이기
    table_df["영화명"] = table_df.apply(
        lambda row: f"{row['movieNm']} 🏆" if row["audiAcc"] >= 1_000_000 else row["movieNm"],
        axis=1,
    )

    table_df = table_df[["rank", "영화명", "순위변동", "openDt", "audiCnt", "audiAcc", "scrnCnt"]]
    table_df.columns = ["순위", "영화명", "순위변동", "개봉일", "관객수", "누적관객", "스크린수"]

    # 순위변동 글자에 색을 입히기 위해 Styler를 사용합니다.
    styled_table = table_df.style.map(rank_change_color, subset=["순위변동"]).format(
        {"관객수": "{:,}", "누적관객": "{:,}", "스크린수": "{:,}"}
    )

    st.dataframe(
        styled_table,
        use_container_width=True,
        hide_index=True,
    )


if __name__ == "__main__":
    main()
