/* =====================================================
   소상공인 방범물품 지원 신청 — app.js
   ===================================================== */

"use strict";

/* ── Supabase / VWorld 설정 ──────────────────────── */
const SUPABASE_URL   = window.APP_CONFIG.SUPABASE_URL;
const SUPABASE_KEY   = window.APP_CONFIG.SUPABASE_ANON_KEY;
const VWORLD_KEY     = window.APP_CONFIG.VWORLD_API_KEY;
const JUSO_KEY       = window.APP_CONFIG.JUSO_CONFM_KEY;
const JUSO_COORD_KEY = window.APP_CONFIG.JUSO_COORD_CONFM_KEY;

/* ── 전역 상태 ──────────────────────────────────── */
let map       = null;
let marker    = null;
let userLat   = null;
let userLng   = null;

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   지원 물품 선택
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
const ITEM_IDS = ["bell", "self", "kit"];
const ITEM_LABELS = {
  bell: "비상벨 + 경광등",
  self: "호신용품 세트",
  kit:  "방범 강화키트",
};

function selectItem(key) {
  ITEM_IDS.forEach(id => {
    document.getElementById("itemCard_" + id).classList.remove("selected");
  });
  document.getElementById("itemCard_" + key).classList.add("selected");
  document.getElementById("selectedItem").value = ITEM_LABELS[key] || key;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   헬퍼
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function getRadioValue(name) {
  const checked = document.querySelector(`input[name="${name}"]:checked`);
  return checked ? checked.value : null;
}

function getSelectValue(id) {
  const el = document.getElementById(id);
  return el ? el.value : "";
}

function getInputValue(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

function isChecked(id) {
  const el = document.getElementById(id);
  return el ? el.checked : false;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   지도 초기화 (VWorld)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function initMap(lat, lng) {
  const center = new vw.CoordZ(lng, lat, 10.0);
  const mapOptions = {
    mapMode   : vw.MapMode.TWO_D,
    coordinate: vw.CoordType.EPSG_4326,
    transitionEffect: vw.TransitionEffect.NONE,
    initPosition: center,
    zoom: 16,
  };

  map = new vw.Map("map", mapOptions);
  map.on("leftClick", onMapClick);
  setMarker(lat, lng);
}

function setMarker(lat, lng) {
  if (marker) map.removeLayer(marker);
  const pos = new vw.CoordZ(lng, lat, 10.0);
  marker = new vw.Marker(pos, { color: "#E24B4A", size: 32 });
  map.addLayer(marker);
  userLat = lat;
  userLng = lng;
  updateLocationInfo(lat, lng);
}

function onMapClick(e) {
  const lat = e.position.y;
  const lng = e.position.x;
  setMarker(lat, lng);
}

function updateLocationInfo(lat, lng) {
  const el = document.getElementById("locationInfo");
  if (el) {
    el.textContent = `선택된 좌표: 위도 ${lat.toFixed(6)}, 경도 ${lng.toFixed(6)}`;
  }
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   주소 검색
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
async function searchAddress() {
  const query = getInputValue("address");
  if (!query) { alert("주소를 입력해주세요."); return; }

  try {
    const url = `https://www.juso.go.kr/addrlink/addrLinkApi.do?confmKey=${JUSO_KEY}&currentPage=1&countPerPage=5&keyword=${encodeURIComponent(query)}&resultType=json`;
    const res  = await fetch(url);
    const data = await res.json();
    const items = data?.results?.juso;

    if (!items || items.length === 0) {
      alert("검색 결과가 없습니다. 주소를 다시 확인해주세요."); return;
    }

    const selected = items[0];
    const roadAddr = selected.roadAddr;
    document.getElementById("selectedAddress").value = roadAddr;

    /* 좌표 변환 */
    const coordUrl = `https://www.juso.go.kr/addrlink/addrCoordApi.do?confmKey=${JUSO_COORD_KEY}&admCd=${selected.admCd}&rnMgtSn=${selected.rnMgtSn}&udrtYn=${selected.udrtYn}&buldMnnm=${selected.buldMnnm}&buldSlno=${selected.buldSlno}&resultType=json`;
    const cRes  = await fetch(coordUrl);
    const cData = await cRes.json();
    const juso  = cData?.results?.juso?.[0];

    if (juso && juso.entX && juso.entY) {
      const lat = parseFloat(juso.entY);
      const lng = parseFloat(juso.entX);
      if (map) { setMarker(lat, lng); map.moveTo(new vw.CoordZ(lng, lat, 10.0), 16); }
      else { initMap(lat, lng); }
    }
  } catch (err) {
    console.error("주소 검색 오류:", err);
    alert("주소 검색 중 오류가 발생했습니다.");
  }
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   체감안전도 점수 (5점 만점, 문항당 0~1점)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function safeFeelScore(answer, reverse) {
  if (reverse) {
    if (answer === "매우 그렇다")       return 0.0;
    if (answer === "그렇다")            return 0.25;
    if (answer === "보통이다")          return 0.5;
    if (answer === "그렇지 않다")       return 0.75;
    if (answer === "매우 그렇지 않다") return 1.0;
    return 0;
  }
  if (answer === "매우 그렇지 않다") return 0.0;
  if (answer === "그렇지 않다")      return 0.25;
  if (answer === "보통이다")         return 0.5;
  if (answer === "그렇다")           return 0.75;
  if (answer === "매우 그렇다")      return 1.0;
  return 0;
}

function calcFeltSafetyScore() {
  return (
    safeFeelScore(getRadioValue("safeFeel1"), true)  +
    safeFeelScore(getRadioValue("safeFeel2"), true)  +
    safeFeelScore(getRadioValue("safeFeel3"), false) +
    safeFeelScore(getRadioValue("safeFeel4"), true)  +
    safeFeelScore(getRadioValue("safeFeel5"), false)
  );
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   유효성 검사
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
function validate() {
  const errors = [];

  if (!getInputValue("ownerName"))  errors.push("성명을 입력해주세요.");
  if (!getInputValue("phone"))      errors.push("연락처를 입력해주세요.");
  if (!getInputValue("shopName"))   errors.push("점포명을 입력해주세요.");
  if (!getSelectValue("businessType")) errors.push("업종을 선택해주세요.");
  if (!getInputValue("selectedAddress")) errors.push("점포 주소를 검색해주세요.");
  if (!getRadioValue("salesRange")) errors.push("연매출 구간을 선택해주세요.");
  if (!getRadioValue("crimeFear"))  errors.push("점포 환경 설문 1번을 선택해주세요.");
  if (!getRadioValue("nightBusiness")) errors.push("점포 환경 설문 2번을 선택해주세요.");
  if (!getRadioValue("darkArea"))   errors.push("점포 환경 설문 3번을 선택해주세요.");
  if (!getRadioValue("soloWork"))   errors.push("점포 환경 설문 4번을 선택해주세요.");
  if (!getRadioValue("cctvStatus")) errors.push("점포 환경 설문 5번을 선택해주세요.");
  if (!getRadioValue("securityCompany")) errors.push("점포 환경 설문 6번을 선택해주세요.");
  if (!getRadioValue("hasBell"))    errors.push("점포 환경 설문 7번을 선택해주세요.");

  const feels = ["safeFeel1","safeFeel2","safeFeel3","safeFeel4","safeFeel5"];
  const missingFeel = feels.some(n => !getRadioValue(n));
  if (missingFeel) errors.push("체감안전도 설문 5문항을 모두 선택해주세요.");

  if (!getInputValue("selectedItem")) errors.push("지원 물품을 1개 선택해주세요.");

  if (!isChecked("agreePrivacy")) errors.push("개인정보 수집·이용 동의가 필요합니다.");
  if (!isChecked("agreeNotice"))  errors.push("유의사항 확인이 필요합니다.");

  return errors;
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Supabase 제출
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
async function submitToSupabase(payload) {
  const res = await fetch(`${SUPABASE_URL}/rest/v1/applications`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "apikey": SUPABASE_KEY,
      "Authorization": `Bearer ${SUPABASE_KEY}`,
      "Prefer": "return=representation",
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err?.message || `HTTP ${res.status}`);
  }
  return res.json();
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   제출 핸들러
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
async function handleSubmit() {
  const errors = validate();
  if (errors.length > 0) {
    alert("입력 오류:\n\n" + errors.join("\n"));
    return;
  }

  const cctvVal      = getRadioValue("cctvStatus");
  const hasCctv      = (cctvVal === "1~2대" || cctvVal === "3대 이상");
  const secVal       = getRadioValue("securityCompany");
  const usesSecurity = (secVal === "이용 중");
  const bellVal      = getRadioValue("hasBell");
  const hasBell      = (bellVal === "예");

  const salesRaw = getInputValue("annualSales").replace(/,/g, "");
  const salesNum = salesRaw ? parseInt(salesRaw, 10) : null;

  const feltSafety = Math.round(calcFeltSafetyScore() * 100) / 100;

  const bizType    = getSelectValue("businessType");
  const bizTypeEtc = getInputValue("businessTypeEtc");

  const payload = {
    applicant_name:       getInputValue("ownerName"),
    phone:                getInputValue("phone"),
    business_name:        getInputValue("shopName"),
    business_type:        bizType === "기타" ? "기타" : bizType,
    business_type_other:  bizType === "기타" ? bizTypeEtc : null,
    address_road:         getInputValue("selectedAddress"),
    address_detail:       getInputValue("detailAddress"),
    latitude:             userLat,
    longitude:            userLng,
    sales_band:           getRadioValue("salesRange"),
    annual_sales:         salesNum,

    /* 점포 환경 설문 */
    survey_crime_anxiety:  getRadioValue("crimeFear"),
    survey_late_night:     getRadioValue("nightBusiness"),
    survey_dark_area:      getRadioValue("darkArea"),
    survey_single_worker:  getRadioValue("soloWork"),
    has_cctv:              hasCctv,
    uses_security_company: usesSecurity,
    has_emergency_bell:    hasBell,

    /* 체감안전도 (5점 만점) */
    safe_feel_1:         getRadioValue("safeFeel1"),
    safe_feel_2:         getRadioValue("safeFeel2"),
    safe_feel_3:         getRadioValue("safeFeel3"),
    safe_feel_4:         getRadioValue("safeFeel4"),
    safe_feel_5:         getRadioValue("safeFeel5"),
    felt_safety_score:   feltSafety,

    /* 지원 물품 희망 */
    requested_item:      getInputValue("selectedItem"),

    status:              "submitted",
  };

  const btn = document.getElementById("submitBtn");
  btn.disabled = true;
  btn.textContent = "제출 중...";

  try {
    await submitToSupabase(payload);
    document.getElementById("resultBox").innerHTML = `
      <div style="color:#166534;font-weight:700;font-size:16px;margin-bottom:8px;">✓ 신청서가 접수되었습니다.</div>
      <div style="color:#374151;font-size:14px;">
        신청인: <b>${payload.applicant_name}</b> 님<br>
        점포명: <b>${payload.business_name}</b><br>
        희망 물품: <b>${payload.requested_item}</b><br><br>
        검토 결과는 <b>${payload.phone}</b> 으로 개별 연락드릴 예정입니다.
      </div>
    `;
    btn.textContent = "접수 완료";
  } catch (err) {
    console.error("제출 오류:", err);
    alert("제출 중 오류가 발생했습니다.\n" + err.message);
    btn.disabled = false;
    btn.textContent = "신청서 제출";
  }
}

/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   이벤트 바인딩
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */
document.addEventListener("DOMContentLoaded", () => {
  /* 주소 검색 버튼 */
  const searchBtn = document.getElementById("searchAddressBtn");
  if (searchBtn) searchBtn.addEventListener("click", searchAddress);

  /* 지도 초기화 (전남 중심 기본좌표) */
  if (typeof vw !== "undefined" && document.getElementById("map")) {
    initMap(34.8679, 126.9910);
  }

  /* 제출 버튼 */
  const submitBtn = document.getElementById("submitBtn");
  if (submitBtn) submitBtn.addEventListener("click", handleSubmit);
});
