#!/usr/bin/env python3
"""
해외 종속회사 목록 → data/subsidiaries.csv  (메인 스크린 지구본용)
    python scripts/build_subsidiaries.py            (UBDA_COMPANY 또는 --company 로 기업 지정)
입력  data/raw/overview_<연도>.txt  — collect_business_text.py가 저장한 '상세표-1 연결대상 종속회사 현황(상세)'
출력  data/subsidiaries.csv — 상호·설립일·주소·주요사업·자산총액(원문 단위 그대로)·국가·좌표·출처

· 국가는 원문 '주소' 칸의 글자로만 정한다(아래 COUNTRIES 표). 못 정하면 '미확인'으로 두고 지도에서 뺀다.
· 주소 칸이 각주 번호뿐이면(국내 신탁·펀드 등) '주소 미기재'로 두고 나라를 추정하지 않는다. 원문 '-' 한 줄 = 종속회사 없음.
· 좌표는 국가 대표 위치(지도 표시용)이며 법인 실제 주소의 좌표가 아니다.
· 값을 새로 만들지 않는다. 표를 못 찾으면 빈 파일(헤더만)을 쓴다.
"""
from __future__ import annotations

import json
import re
import sys

from ubda_common import DATA, RAW, now_kst, write_csv

COLS = ["name", "established", "address", "business", "assets", "assets_unit", "major", "country", "country_en", "lat", "lng",
        "report", "source_url", "source_location"]

# 국가(한글) : (지도 데이터 이름, 위도, 경도, 주소에서 찾을 글자들)
COUNTRIES = {
    "대한민국": ("South Korea", 36.5, 127.9, ["대한민국", "한국", "KOREA", "서울", "경기", "김해", "청주", "영등포", "창원", "천안", "평택", "수원", "용인", "화성시", "성남", "판교", "아산", "구미", "포항", "거제", "울산광역", "부산", "인천", "대구", "광주광역", "대전", "울산", "세종", "강원", "충청", "충북", "충남", "전라", "전북", "전남", "경상", "경북", "경남", "제주"]),
    "미국": ("United States of America", 39.8, -98.6, ["미국", "U.S.A", "USA", "UNITED STATES", "U.S.", "DELAWARE", "IRVINE", "WILMINGTON", "CORPORATION TRUST CENTER", "CALIFORNIA", "NEW YORK", "NEW JERSEY", "TEXAS", "GEORGIA", "ALABAMA", "MICHIGAN", "ILLINOIS", "OHIO", "WASHINGTON", "NEVADA", "VIRGINIA", "FLORIDA", "MASSACHUSETTS", "INDIANA", "TENNESSEE", "KENTUCKY", "ARIZONA", "COLORADO", "NORTH CAROLINA", "SOUTH CAROLINA", "OREGON", "MINNESOTA", "PENNSYLVANIA", "WISCONSIN", "MISSOURI", "UTAH", "NEBRASKA", "CONNECTICUT", "MARYLAND", "LOS ANGELES", "SAN FRANCISCO", "SAN JOSE", "SEATTLE", "CHICAGO", "ATLANTA", "DETROIT", "HOUSTON", "DALLAS", "BOSTON", "HAWAII", "GUAM", "괌", "델라웨어", "캘리포니아", "뉴욕", "뉴저지", "텍사스", "조지아주", "앨라배마", "알라바마", "미시간", "일리노이", "하와이", "로스앤젤레스", "엘에이", "시카고", "애틀랜타", "디트로이트", "휴스턴", "달라스", "보스턴", "시애틀"]),
    "중국": ("China", 35.9, 104.2, ["중국", "CHINA", "P.R.C", "PRC", "上海", "北京", "SHANGHAI", "BEIJING", "SHENZHEN", "GUANGZHOU", "TIANJIN", "JIANGSU", "ZHEJIANG", "SHANDONG", "QINGDAO", "SUZHOU", "WUXI", "NANJING", "DALIAN", "SHENYANG", "CHONGQING", "CHENGDU", "WUHAN", "XIAN", "XI'AN", "YANTAI", "WEIHAI", "HANGZHOU", "상해", "상하이", "북경", "베이징", "심천", "선전", "광저우", "광주시(중국)", "천진", "톈진", "강소", "장쑤", "절강", "저장", "산동", "산둥", "청도", "칭다오", "소주", "쑤저우", "무석", "우시", "남경", "난징", "대련", "다롄", "심양", "선양", "중경", "충칭", "성도", "청두", "무한", "우한", "서안", "시안", "연태", "옌타이", "위해", "웨이하이", "항주", "항저우", "염성", "옌청", "길림", "지린", "흑룡강", "요녕", "랴오닝", "광동", "광둥", "복건", "푸젠", "하북", "허베이", "하남", "허난", "호북", "후베이", "안휘", "안후이"]),
    "홍콩": ("China", 22.3, 114.2, ["홍콩", "HONG KONG", "HONGKONG", "KOWLOON", "INTERNATIONAL COMMERCE CENTRE", "QUEEN'S ROAD", "WANCHAI", "WAN CHAI", "TSIM SHA TSUI", "TSIMSHATSUI"]),
    "마카오": ("China", 22.2, 113.5, ["마카오", "MACAU", "MACAO"]),
    "대만": ("Taiwan", 23.7, 121.0, ["대만", "TAIWAN", "TAIPEI", "台北", "台灣", "臺灣", "타이베이", "타이페이"]),
    "일본": ("Japan", 36.2, 138.3, ["일본", "JAPAN", "TOKYO", "MINATO", "CHIYODA", "SHINJUKU", "SHIBUYA", "CHUO-KU", "OSAKA", "YOKOHAMA", "NAGOYA", "FUKUOKA", "동경", "도쿄", "오사카", "요코하마", "나고야", "후쿠오카"]),
    "베트남": ("Vietnam", 14.1, 108.3, ["베트남", "VIETNAM", "VIET NAM", "HANOI", "HO CHI MINH", "하노이", "호치민", "하이퐁", "BAC NINH", "박닌", "HAI PHONG", "DONG NAI", "BINH DUONG", "THAI NGUYEN"]),
    "인도네시아": ("Indonesia", -2.5, 118.0, ["인도네시아", "INDONESIA", "JAKARTA", "자카르타", "BEKASI", "TANGERANG", "SURABAYA"]),
    "인도": ("India", 22.0, 79.0, ["인도", "INDIA", "MUMBAI", "CHENNAI", "NEW DELHI", "DELHI", "BANGALORE", "BENGALURU", "PUNE", "GURGAON", "GURUGRAM", "NOIDA", "HYDERABAD", "뭄바이", "첸나이", "뉴델리", "델리", "벵갈루루", "푸네", "구루그람", "노이다", "TAMIL NADU", "타밀나두", "HARYANA", "MAHARASHTRA", "ANDHRA PRADESH"]),
    "태국": ("Thailand", 15.9, 100.9, ["태국", "THAILAND", "BANGKOK", "PHAHOLYOTHIN", "PHAYA THAI", "방콕", "RAYONG", "CHONBURI"]),
    "말레이시아": ("Malaysia", 4.2, 102.0, ["말레이시아", "MALAYSIA", "KUALA LUMPUR", "쿠알라룸푸르", "PENANG", "SELANGOR", "JOHOR"]),
    "싱가포르": ("Singapore", 1.35, 103.8, ["싱가포르", "싱가폴", "SINGAPORE"]),
    "필리핀": ("Philippines", 12.9, 121.8, ["필리핀", "PHILIPPINES", "MANILA", "CALAMBA", "LAGUNA", "마닐라", "CEBU", "MAKATI", "TAGUIG"]),
    "미얀마": ("Myanmar", 21.9, 95.9, ["미얀마", "MYANMAR", "YANGON", "양곤"]),
    "캄보디아": ("Cambodia", 12.6, 104.9, ["캄보디아", "CAMBODIA", "PHNOM PENH", "프놈펜"]),
    "라오스": ("Laos", 19.9, 102.5, ["라오스", "LAOS", "VIENTIANE"]),
    "방글라데시": ("Bangladesh", 23.7, 90.4, ["방글라데시", "BANGLADESH", "DHAKA"]),
    "파키스탄": ("Pakistan", 30.4, 69.3, ["파키스탄", "PAKISTAN", "KARACHI", "LAHORE"]),
    "스리랑카": ("Sri Lanka", 7.9, 80.8, ["스리랑카", "SRI LANKA", "COLOMBO"]),
    "몽골": ("Mongolia", 46.9, 103.8, ["몽골", "MONGOLIA", "ULAANBAATAR", "울란바토르"]),
    "카자흐스탄": ("Kazakhstan", 48.0, 66.9, ["카자흐스탄", "KAZAKHSTAN", "ALMATY", "ASTANA", "알마티"]),
    "우즈베키스탄": ("Uzbekistan", 41.4, 64.6, ["우즈베키스탄", "UZBEKISTAN", "TASHKENT", "타슈켄트"]),
    "아랍에미리트": ("United Arab Emirates", 23.4, 53.8, ["아랍에미리트", "UAE", "U.A.E", "UNITED ARAB EMIRATES", "DUBAI", "ABU DHABI", "두바이", "아부다비"]),
    "사우디아라비아": ("Saudi Arabia", 23.9, 45.1, ["사우디", "SAUDI", "RIYADH", "리야드", "JEDDAH", "DAMMAM", "KSA", "AL KHOBAR", "KHOBAR"]),
    "카타르": ("Qatar", 25.3, 51.2, ["카타르", "QATAR", "DOHA"]),
    "쿠웨이트": ("Kuwait", 29.3, 47.5, ["쿠웨이트", "KUWAIT"]),
    "오만": ("Oman", 21.5, 55.9, ["오만", "OMAN", "MUSCAT"]),
    "이스라엘": ("Israel", 31.0, 34.9, ["이스라엘", "ISRAEL", "TEL AVIV"]),
    "튀르키예": ("Turkey", 39.0, 35.2, ["튀르키예", "터키", "TURKEY", "TURKIYE", "TÜRKIYE", "ISTANBUL", "이스탄불", "IZMIT"]),
    "이집트": ("Egypt", 26.8, 30.8, ["이집트", "EGYPT", "CAIRO"]),
    "남아프리카공화국": ("South Africa", -30.6, 22.9, ["남아프리카", "남아공", "SOUTH AFRICA", "JOHANNESBURG"]),
    "앙골라": ("Angola", -11.2, 17.9, ["앙골라", "ANGOLA", "LUANDA"]),
    "나이지리아": ("Nigeria", 9.1, 8.7, ["나이지리아", "NIGERIA", "LAGOS"]),
    "케냐": ("Kenya", -0.0, 37.9, ["케냐", "KENYA", "NAIROBI"]),
    "모로코": ("Morocco", 31.8, -7.1, ["모로코", "MOROCCO"]),
    "알제리": ("Algeria", 28.0, 1.7, ["알제리", "ALGERIA"]),
    "영국": ("United Kingdom", 54.0, -2.0, ["영국", "UNITED KINGDOM", "U.K.", "UK", "LEATHERHEAD", "BRIGHTON", "MANCHESTER", "BIRMINGHAM", "READING", "SURREY", "ENGLAND", "LONDON", "런던", "SCOTLAND", "WALES"]),
    "독일": ("Germany", 51.2, 10.4, ["독일", "GERMANY", "DEUTSCHLAND", "STRASSE", "STRAßE", "FRANKFURT", "프랑크푸르트", "MUNICH", "MÜNCHEN", "뮌헨", "BERLIN", "베를린", "HAMBURG", "함부르크", "DÜSSELDORF", "DUSSELDORF", "뒤셀도르프", "ESCHBORN", "에쉬본", "OFFENBACH", "오펜바흐", "STUTTGART"]),
    "프랑스": ("France", 46.2, 2.2, ["프랑스", "FRANCE", "PARIS", "파리"]),
    "이탈리아": ("Italy", 41.9, 12.6, ["이탈리아", "ITALY", "MILAN", "MILANO", "밀라노", "ROMA", "ROME"]),
    "스페인": ("Spain", 40.5, -3.7, ["스페인", "SPAIN", "MADRID", "마드리드", "BARCELONA"]),
    "포르투갈": ("Portugal", 39.4, -8.2, ["포르투갈", "PORTUGAL", "LISBON"]),
    "네덜란드": ("Netherlands", 52.1, 5.3, ["네덜란드", "NETHERLANDS", "HOLLAND", "AMSTELVEEN", "HOOFDDORP", "암스텔베인", "SCHIPHOL", "EINDHOVEN", "UTRECHT", "THE HAGUE", "AMSTERDAM", "암스테르담", "ROTTERDAM", "로테르담", "BREDA"]),
    "벨기에": ("Belgium", 50.5, 4.5, ["벨기에", "BELGIUM", "BRUSSELS", "브뤼셀", "ANTWERP"]),
    "룩셈부르크": ("Luxembourg", 49.8, 6.1, ["룩셈부르크", "LUXEMBOURG"]),
    "스위스": ("Switzerland", 46.8, 8.2, ["스위스", "SWITZERLAND", "ZURICH", "취리히", "GENEVA", "제네바"]),
    "오스트리아": ("Austria", 47.5, 14.6, ["오스트리아", "AUSTRIA", "VIENNA", "WIEN", "비엔나"]),
    "아일랜드": ("Ireland", 53.4, -8.2, ["아일랜드", "IRELAND", "DUBLIN", "더블린"]),
    "스웨덴": ("Sweden", 60.1, 18.6, ["스웨덴", "SWEDEN", "STOCKHOLM", "GATAN", "ÅMÅL", "AMAL"]),
    "노르웨이": ("Norway", 60.5, 8.5, ["노르웨이", "NORWAY", "OSLO", "HOKKSUND", "FREDRIKSTAD", "SELLEBAKK"]),
    "덴마크": ("Denmark", 56.3, 9.5, ["덴마크", "DENMARK", "COPENHAGEN"]),
    "핀란드": ("Finland", 61.9, 25.7, ["핀란드", "FINLAND", "HELSINKI"]),
    "폴란드": ("Poland", 51.9, 19.1, ["폴란드", "POLAND", "WARSAW", "WARSZAWA", "POLSKA", "바르샤바", "WROCLAW", "브로츠와프", "브로츠와프"]),
    "체코": ("Czechia", 49.8, 15.5, ["체코", "CZECH", "PRAGUE", "프라하", "NOSOVICE", "OSTRAVA"]),
    "슬로바키아": ("Slovakia", 48.7, 19.7, ["슬로바키아", "SLOVAKIA", "ZILINA", "질리나", "BRATISLAVA"]),
    "헝가리": ("Hungary", 47.2, 19.5, ["헝가리", "HUNGARY", "BUDAPEST", "부다페스트", "GÖD", "괴드"]),
    "루마니아": ("Romania", 45.9, 24.9, ["루마니아", "ROMANIA", "BUCHAREST"]),
    "불가리아": ("Bulgaria", 42.7, 25.5, ["불가리아", "BULGARIA"]),
    "세르비아": ("Serbia", 44.0, 21.0, ["세르비아", "SERBIA", "BELGRADE"]),
    "슬로베니아": ("Slovenia", 46.2, 14.9, ["슬로베니아", "SLOVENIA"]),
    "크로아티아": ("Croatia", 45.1, 15.2, ["크로아티아", "CROATIA"]),
    "그리스": ("Greece", 39.1, 21.8, ["그리스", "GREECE", "ATHENS"]),
    "우크라이나": ("Ukraine", 48.4, 31.2, ["우크라이나", "UKRAINE", "KIEV", "KYIV"]),
    "러시아": ("Russia", 61.5, 105.3, ["러시아", "RUSSIA", "MOSCOW", "모스크바", "ST. PETERSBURG", "상트페테르부르크", "VLADIVOSTOK", "블라디보스토크", "KALUGA"]),
    "캐나다": ("Canada", 56.1, -106.3, ["캐나다", "CANADA", "TORONTO", "토론토", "VANCOUVER", "밴쿠버", "ONTARIO", "온타리오", "QUEBEC", "MONTREAL", "ALBERTA", "BRITISH COLUMBIA"]),
    "멕시코": ("Mexico", 23.6, -102.6, ["멕시코", "MEXICO", "MONTERREY", "몬테레이", "NUEVO LEON", "누에보레온", "TIJUANA", "티후아나", "QUERETARO", "COAHUILA", "SAN LUIS POTOSI", "GUANAJUATO"]),
    "브라질": ("Brazil", -14.2, -51.9, ["브라질", "BRAZIL", "BRASIL", "SAO PAULO", "SÃO PAULO", "상파울루", "MANAUS", "마나우스", "PIRACICABA", "CAMPINAS"]),
    "아르헨티나": ("Argentina", -38.4, -63.6, ["아르헨티나", "ARGENTINA", "BUENOS AIRES"]),
    "칠레": ("Chile", -35.7, -71.5, ["칠레", "CHILE", "SANTIAGO"]),
    "페루": ("Peru", -9.2, -75.0, ["페루", "PERU", "LIMA"]),
    "콜롬비아": ("Colombia", 4.6, -74.3, ["콜롬비아", "COLOMBIA", "BOGOTA"]),
    "파나마": ("Panama", 8.5, -80.8, ["파나마", "PANAMA"]),
    "호주": ("Australia", -25.3, 133.8, ["호주", "오스트레일리아", "AUSTRALIA", "SYDNEY", "시드니", "MELBOURNE", "멜버른", "PERTH", "BRISBANE"]),
    "뉴질랜드": ("New Zealand", -40.9, 174.9, ["뉴질랜드", "NEW ZEALAND", "AUCKLAND"]),
    "키르기스스탄": ("Kyrgyzstan", 41.2, 74.8, ["키르기스", "KYRGYZ", "BISHKEK", "비슈케크"]),
    "라트비아": ("Latvia", 56.9, 24.6, ["라트비아", "LATVIA", "RIGA"]),
    "에스토니아": ("Estonia", 58.6, 25.0, ["에스토니아", "ESTONIA", "TALLINN"]),
    "리투아니아": ("Lithuania", 55.2, 23.9, ["리투아니아", "LITHUANIA", "VILNIUS"]),
    "아제르바이잔": ("Azerbaijan", 40.1, 47.6, ["아제르바이잔", "AZERBAIJAN", "BAKU"]),
    "요르단": ("Jordan", 30.6, 36.2, ["요르단", "JORDAN", "AMMAN", "ABDALI"]),
    "레바논": ("Lebanon", 33.9, 35.9, ["레바논", "LEBANON", "BEIRUT"]),
    "이란": ("Iran", 32.4, 53.7, ["이란", "IRAN", "TEHRAN"]),
    "이라크": ("Iraq", 33.2, 43.7, ["이라크", "IRAQ", "BAGHDAD", "ERBIL"]),
    "베네수엘라": ("Venezuela", 6.4, -66.6, ["베네수엘라", "VENEZUELA", "CARACAS"]),
    "에콰도르": ("Ecuador", -1.8, -78.2, ["에콰도르", "ECUADOR", "QUITO", "GUAYAQUIL"]),
    "과테말라": ("Guatemala", 15.8, -90.2, ["과테말라", "GUATEMALA"]),
    "코스타리카": ("Costa Rica", 9.7, -83.8, ["코스타리카", "COSTA RICA"]),
    "푸에르토리코": ("Puerto Rico", 18.2, -66.6, ["푸에르토리코", "PUERTO RICO"]),
    "튀니지": ("Tunisia", 33.9, 9.5, ["튀니지", "TUNISIA", "TUNIS"]),
    "가나": ("Ghana", 7.9, -1.0, ["가나", "GHANA", "ACCRA"]),
    "탄자니아": ("Tanzania", -6.4, 34.9, ["탄자니아", "TANZANIA"]),
    "에티오피아": ("Ethiopia", 9.1, 40.5, ["에티오피아", "ETHIOPIA", "ADDIS ABABA"]),
    "벨라루스": ("Belarus", 53.7, 27.9, ["벨라루스", "BELARUS", "MINSK"]),
    "조지아": ("Georgia", 42.3, 43.4, ["TBILISI", "트빌리시"]),
    "브루나이": ("Brunei", 4.5, 114.7, ["브루나이", "BRUNEI"]),
    "네팔": ("Nepal", 28.4, 84.1, ["네팔", "NEPAL", "KATHMANDU"]),
    "우루과이": ("Uruguay", -32.5, -55.8, ["우루과이", "URUGUAY", "MONTEVIDEO"]),
    "온두라스": ("Honduras", 15.2, -86.2, ["온두라스", "HONDURAS", "TEGUCIGALPA"]),
    "나미비아": ("Namibia", -22.9, 18.5, ["나미비아", "NAMIBIA", "WINDHOEK"]),
    "모잠비크": ("Mozambique", -18.7, 35.5, ["모잠비크", "MOZAMBIQUE", "MAPUTO"]),
    "모리셔스": (None, -20.3, 57.6, ["모리셔스", "MAURITIUS"]),
    "케이맨제도": (None, 19.3, -81.3, ["케이맨", "CAYMAN"]),
    "버진아일랜드": (None, 18.4, -64.6, ["버진아일랜드", "버진 아일랜드", "VIRGIN ISLANDS", "B.V.I", "BVI", "TORTOLA"]),
    "버뮤다": (None, 32.3, -64.8, ["버뮤다", "BERMUDA"]),
    "마셜제도": (None, 7.1, 171.2, ["마셜", "마샬", "MARSHALL ISLANDS", "MAJURO"]),
    "채널제도": (None, 49.3, -2.3, ["GUERNSEY", "JERSEY", "건지", "저지섬"]),
    "라이베리아": ("Liberia", 6.4, -9.4, ["라이베리아", "LIBERIA", "MONROVIA"]),
    "몰타": (None, 35.9, 14.4, ["몰타", "MALTA"]),
    "키프로스": ("Cyprus", 35.1, 33.4, ["키프로스", "CYPRUS"]),
}
# 짧은 영어 약어(USA, UK 등)는 단어 경계로, 나머지는 그대로 찾는다. 긴 단어부터 맞춰 'GEORGIA' 같은 겹침을 줄임
_PATTERNS = sorted(((p, k) for k, (_, _, _, ps) in COUNTRIES.items() for p in ps), key=lambda x: -len(x[0]))


US_STATE = re.compile(r"(?:,|\s)\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\.?\s*,?\s*\d{5}(-\d{4})?\b")


CN_CITY = {"상해", "북경", "천진", "청도", "대련", "심양", "중경", "성도", "무한", "서안", "연태", "위해", "항주", "소주", "무석", "남경", "옌청", "염성"}
JP_POSTAL = re.compile(r"(?<![\d-])\d{3}-\d{4}(?![\d-])")
NO_ADDR = re.compile(r"^\s*(-|–|\(?\s*주\s*\d*\s*\)?|\(?\*\d*\)?)?\s*$")  # 주소 칸이 비었거나 각주 번호만 있음


def _rx(p: str, k: str):
    if k != "대한민국" and re.fullmatch(r"[가-힣]{2,3}", p):  # '가나'·'오만'·'인도' 같은 짧은 한글 국명은 단어로만 (예: '인도로' 제외)
        if p in CN_CITY:  # '상해시' 처럼 '시'가 붙는 중국 도시 (하남시·광주시 같은 국내 지명과 겹치는 이름은 제외)
            return re.compile(r"(?<![가-힣])" + p + r"(?=시|(?![가-힣]))")
        return re.compile(r"(?<![가-힣])" + p + r"(?![가-힣])")
    if re.fullmatch(r"[A-Z.]{2,5}", p):
        return re.compile(r"(?<![A-Z])" + re.escape(p) + r"(?![A-Z])")
    return re.compile(re.escape(p))


_RX = [(_rx(p, k), k) for p, k in _PATTERNS]


def country_of(addr: str) -> str:
    """주소에서 찾은 나라·도시 이름 중 가장 뒤에 나오는 것을 쓴다 (주소는 보통 나라 이름으로 끝남: 'Via Colombo …, Italy' → 이탈리아)."""
    a = addr.upper()
    best = None  # (끝 위치, 길이, 나라)
    def hit(m, k):
        nonlocal best
        cand = (m.end(), m.end() - m.start(), k)
        if best is None or cand[:2] > best[:2]:
            best = cand
    for rx, k in _RX:
        for m in rx.finditer(a):
            hit(m, k)
    for m in US_STATE.finditer(a):  # 미국식 '주 약어 + 우편번호'
        hit(m, "미국")
    if best is None and JP_POSTAL.search(a):  # 다른 단서가 없을 때만: 일본식 우편번호 123-4567 (한국 5자리·미국 5-4자리와 다름)
        return "일본"
    return best[2] if best else "미확인"


def parse(text: str) -> tuple[list[dict], str]:
    """'연결대상 종속회사 현황(상세)' 장의 표에서 상호·설립일·주소… 행을 뽑는다."""
    seg = ""
    m = re.search(r"##[^\n]*연결대상\s*종속회사\s*현황\s*\(\s*상세\s*\)[^\n]*\n", text)
    if m:
        seg = text[m.start():]
    if not seg:
        return [], ""
    unit = ""
    um = re.search(r"단위\s*[:：]\s*([^\)\n|]+)", seg[:3000])
    if um:
        unit = um.group(1).strip()
    rows, hdr = [], None
    # 표 행: 셀마다 한 줄(' |'로 끝남), 행 사이는 빈 줄 — 한 줄에 셀이 여러 개인 형식도 함께 처리
    blocks, curb = [], []
    for line in seg.splitlines():
        if line.strip().startswith("[표") or not line.strip():
            if curb:
                blocks.append(curb)
                curb = []
            continue
        if line.rstrip().endswith("|"):
            curb.extend(c.strip() for c in line.rstrip().rstrip("|").split(" | "))
        elif curb:
            blocks.append(curb)
            curb = []
    if curb:
        blocks.append(curb)
    for cells in blocks:
        joined = "".join(cells).replace(" ", "")
        if "상호" in joined and "주소" in joined:
            hdr = [c.replace(" ", "") for c in cells]
            continue
        if not hdr or len(cells) < 3:
            continue

        def col(*keys):
            for k in keys:
                for ix, h in enumerate(hdr):
                    if k in h and ix < len(cells):
                        return cells[ix]
            return ""
        name = col("상호", "회사명")
        if not name or name.replace(" ", "") in ("합계", "계", "소계", "-", "–", "해당없음", "해당사항없음") or name.startswith("※"):
            continue  # '-' 한 줄뿐인 표 = 종속회사 없음
        if re.match(r"제\s*\d+\s*기", name):  # 연결대상 회사 수 변동 표 같은 다른 표의 행
            continue
        rows.append({"name": name, "established": col("설립일"), "address": col("주소", "소재지"), "business": col("주요사업", "업종"),
                     "assets": col("자산총액", "자산"), "assets_unit": "원문 표기 그대로", "major": col("주요종속", "주요")})
    return rows, unit


def main() -> int:
    files = sorted(RAW.glob("overview_*.txt"))
    out = DATA / "subsidiaries.csv"
    if not files:
        write_csv(out, COLS, [])
        print("[안내] overview_*.txt 없음 — 종속회사 표 미수집")
        return 0
    f = files[-1]
    text = f.read_text(encoding="utf-8")
    meta = json.loads((RAW / "business_text.json").read_text(encoding="utf-8")) if (RAW / "business_text.json").exists() else {}
    year = f.stem.split("_")[-1]
    info = meta.get(year, {})
    rows, _ = parse(text)
    res = []
    for r in rows:
        if NO_ADDR.match(r["address"]):  # 주소 대신 각주만 있음(주로 국내 신탁·펀드·유동화회사) — 나라를 추정하지 않음
            k = country_of(r["name"])
            if k == "미확인":
                k = "주소 미기재"
        else:
            k = country_of(r["address"])
        if k == "미확인":  # 주소에 나라 이름이 없으면 상호(예: '… UK LIMITED', '… (Shanghai) Co.')로 한 번 더
            k = country_of(r["name"])
        en, lat, lng, _ = COUNTRIES.get(k, (None, None, None, None))
        res.append({**r, "country": k, "country_en": en or "", "lat": "" if lat is None else lat, "lng": "" if lng is None else lng,
                    "report": info.get("report_nm", f"{year} 사업보고서"), "source_url": info.get("viewer_url", ""),
                    "source_location": "XII. 상세표 > 1. 연결대상 종속회사 현황(상세)"})
    if not res and re.search(r"연결대상\s*종속회사\s*현황", text):  # 표는 있는데 '-'뿐 = 종속회사 없음 (미수집과 구분하려고 한 줄 남김)
        res.append({c: "" for c in COLS} | {"name": "(종속회사 없음)", "country": "종속회사 없음", "report": info.get("report_nm", f"{year} 사업보고서"),
                                             "source_url": info.get("viewer_url", ""), "source_location": "XII. 상세표 > 1. 연결대상 종속회사 현황(상세) — 원문 '-'"})
    write_csv(out, COLS, res)
    unk = [r for r in res if r["country"] == "미확인"]
    noad = [r for r in res if r["country"] == "주소 미기재"]
    fr = [r for r in res if r["country"] not in ("대한민국", "미확인", "주소 미기재", "종속회사 없음")]
    print(f"종속회사 {len(res)}곳 (해외 {len(fr)} · 국가 미확인 {len(unk)} · 주소 미기재 {len(noad)}) → {out.name}  [{now_kst()}]")
    for r in unk[:5]:
        print(f"  [미확인 주소] {r['name']} — {r['address'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
