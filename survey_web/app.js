document.addEventListener("DOMContentLoaded", function () {
  const resultBox = document.getElementById("resultBox");
  const locationInfo = document.getElementById("locationInfo");
  const submitBtn = document.getElementById("submitBtn");
  const searchAddressBtn = document.getElementById("searchAddressBtn");
  const addressInput = document.getElementById("address");
  const selectedAddressInput = document.getElementById("selectedAddress");
  const detailAddressInput = document.getElementById("detailAddress");
  const phoneInput = document.getElementById("phone");
  const annualSalesInput = document.getElementById("annualSales");
  const businessTypeSelect = document.getElementById("businessType");
  const businessTypeEtcInput = document.getElementById("businessTypeEtc");
  const agreePrivacyInput = document.getElementById("agreePrivacy");
  const agreeNoticeInput = document.getElementById("agreeNotice");

  const submitSectionDesc = submitBtn
    ?.closest(".section-card")
    ?.querySelector(".section-desc");

  let selectedLon = null;
  let selectedLat = null;
  let stationRows = [];
  let currentMap = null;
  let currentMarkerLayer = null;
  let isSubmitting = false;
  let hasJustSubmitted = false;

  function setResultMessage(message) {
    if (resultBox) {
      resultBox.innerHTML = message;
    }
  }

  function setLocationMessage(message) {
    if (locationInfo) {
      locationInfo.innerHTML = message;
    }
  }

  function setSubmitPending(isPending) {
    if (!submitBtn) return;
    submitBtn.disabled = isPending;
    submitBtn.textContent = isPending ? "제출 중..." : "신청서 제출";
    submitBtn.style.opacity = isPending ? "0.7" : "1";
    submitBtn.style.cursor = isPending ? "not-allowed" : "pointer";
  }

  function loadScript(src, id) {
    return new Promise((resolve, reject) => {
      const existing = document.getElementById(id);
      if (existing) {
        resolve();
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.id = id;
      script.onload = () => resolve();
      script.onerror = () => reject(new Error("스크립트 로드 실패: " + src));
      document.head.appendChild(script);
    });
  }

  function jsonpRequest(url, callbackName) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");

      const timer = setTimeout(() => {
        cleanup();
        reject(new Error("주소 검색 응답 시간이 초과되었습니다."));
      }, 10000);

      function cleanup() {
        clearTimeout(timer);
        if (script.parentNode) {
          script.parentNode.removeChild(script);
        }
        try {
          delete window[callbackName];
        } catch (e) {
          window[callbackName] = undefined;
        }
      }

      window[callbackName] = function (data) {
        cleanup();
        resolve(data);
      };

      script.src = `${url}&callback=${callbackName}`;
      script.onerror = function () {
        cleanup();
        reject(new Error("주소 검색 스크립트를 불러오지 못했습니다."));
      };

      document.body.appendChild(script);
    });
  }

  function getRadioValue(name) {
    const checked = document.querySelector(`input[name="${name}"]:checked`);
    return checked ? checked.value : "";
  }

  function onlyDigits(value) {
    return String(value || "").replace(/\D/g, "");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatPhoneNumber(value) {
    const digits = onlyDigits(value).slice(0, 11);

    if (!digits) return "";

    if (digits.startsWith("02")) {
      if (digits.length <= 2) return digits;
      if (digits.length <= 5) return `${digits.slice(0, 2)}-${digits.slice(2)}`;
      if (digits.length <= 9) return `${digits.slice(0, 2)}-${digits.slice(2, 5)}-${digits.slice(5)}`;
      return `${digits.slice(0, 2)}-${digits.slice(2, 6)}-${digits.slice(6)}`;
    }

    if (digits.length <= 3) return digits;
    if (digits.length <= 6) return `${digits.slice(0, 3)}-${digits.slice(3)}`;
    if (digits.length <= 10) return `${digits.slice(0, 3)}-${digits.slice(3, 6)}-${digits.slice(6)}`;
    return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`;
  }

  function formatNumberWithCommas(value) {
    const digits = onlyDigits(value);
    if (!digits) return "";
    return Number(digits).toLocaleString("ko-KR");
  }

  function parseNumberOrNull(value) {
    const digits = onlyDigits(value);
    if (!digits) return null;
    const parsed = Number(digits);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function focusAndScroll(target) {
    if (!target) return;

    if (typeof target.focus === "function") {
      target.focus();
    }

    target.scrollIntoView({
      behavior: "smooth",
      block: "center"
    });
  }

  function formatDateTime(date) {
    const yyyy = date.getFullYear();
    const mm = String(date.getMonth() + 1).padStart(2, "0");
    const dd = String(date.getDate()).padStart(2, "0");
    const hh = String(date.getHours()).padStart(2, "0");
    const mi = String(date.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${mi}`;
  }

  function normalizeText(value) {
    return String(value || "").replace(/\s/g, "");
  }

  function createInfoRow(label, value) {
    const safeLabel = escapeHtml(label);
    const safeValue = escapeHtml(value || "(미입력)");
    return `
      <div style="display:grid;grid-template-columns:130px 1fr;gap:10px;padding:10px 0;border-bottom:1px solid #e5e7eb;">
        <div style="font-weight:700;color:#374151;">${safeLabel}</div>
        <div style="color:#111827;line-height:1.7;">${safeValue}</div>
      </div>
    `;
  }

  function getSafeFeelAnswers() {
    return {
      safeFeel1: getRadioValue("safeFeel1"),
      safeFeel2: getRadioValue("safeFeel2"),
      safeFeel3: getRadioValue("safeFeel3"),
      safeFeel4: getRadioValue("safeFeel4"),
      safeFeel5: getRadioValue("safeFeel5")
    };
  }

  function buildApplyReason() {
    const crimeFear = getRadioValue("crimeFear") || "(미응답)";
    const nightBusiness = getRadioValue("nightBusiness") || "(미응답)";
    const darkArea = getRadioValue("darkArea") || "(미응답)";
    const soloWork = getRadioValue("soloWork") || "(미응답)";

    return [
      `범죄 불안 경험: ${crimeFear}`,
      `야간 영업 여부: ${nightBusiness}`,
      `주변 환경: ${darkArea}`,
      `혼자 근무 시간: ${soloWork}`
    ].join(" / ");
  }

  function buildEtcNote() {
    const cctvStatus = getRadioValue("cctvStatus") || "(미응답)";
    const securityCompany = getRadioValue("securityCompany") || "(미응답)";
    const hasBell = getRadioValue("hasBell") || "(미응답)";
    const safeFeels = getSafeFeelAnswers();

    return [
      "[체감안전도 설문]",
      `1. 전반적 안전감: ${safeFeels.safeFeel1 || "(미응답)"}`,
      `2. 야간 주변 안전감: ${safeFeels.safeFeel2 || "(미응답)"}`,
      `3. 단독근무 불안감: ${safeFeels.safeFeel3 || "(미응답)"}`,
      `4. 외부 침입 보호감: ${safeFeels.safeFeel4 || "(미응답)"}`,
      `5. 범죄피해 가능성 인식: ${safeFeels.safeFeel5 || "(미응답)"}`,
      "",
      "[방범시설 응답 원문]",
      `CCTV 설치 현황: ${cctvStatus}`,
      `사설경비업체 이용 여부: ${securityCompany}`,
      `비상벨 설치 여부: ${hasBell}`
    ].join("\n");
  }

  function inferStationByAddress(addressText) {
    const normalized = normalizeText(addressText);
    if (!normalized || !Array.isArray(stationRows) || stationRows.length === 0) {
      return null;
    }

    const candidates = [];

    stationRows.forEach((row) => {
      const areaName = String(row.area_name || "").trim();
      if (!areaName) return;

      let score = 0;

      if (normalized.includes(`${areaName}시`)) score = 4;
      else if (normalized.includes(`${areaName}군`)) score = 4;
      else if (normalized.includes(`${areaName}구`)) score = 4;
      else if (normalized.includes(areaName)) score = 3;
      else if (normalized.includes(String(row.station_name || "").trim())) score = 2;
      else if (normalized.includes(String(row.station_label || "").replace("경찰서", "").trim())) score = 1;

      if (score > 0) {
        candidates.push({ row, score });
      }
    });

    candidates.sort((a, b) => b.score - a.score);
    return candidates.length > 0 ? candidates[0].row : null;
  }

  function validateRequiredFields() {
    const ownerName = document.getElementById("ownerName")?.value.trim() || "";
    const phone = phoneInput?.value.trim() || "";
    const shopName = document.getElementById("shopName")?.value.trim() || "";
    const businessType = businessTypeSelect?.value || "";
    const businessTypeEtc = businessTypeEtcInput?.value.trim() || "";
    const address = addressInput?.value.trim() || "";
    const selectedAddress = selectedAddressInput?.value.trim() || "";
    const salesRange = getRadioValue("salesRange");
    const crimeFear = getRadioValue("crimeFear");
    const nightBusiness = getRadioValue("nightBusiness");
    const darkArea = getRadioValue("darkArea");
    const soloWork = getRadioValue("soloWork");
    const cctvStatus = getRadioValue("cctvStatus");
    const securityCompany = getRadioValue("securityCompany");
    const hasBell = getRadioValue("hasBell");
    const safeFeel1 = getRadioValue("safeFeel1");
    const safeFeel2 = getRadioValue("safeFeel2");
    const safeFeel3 = getRadioValue("safeFeel3");
    const safeFeel4 = getRadioValue("safeFeel4");
    const safeFeel5 = getRadioValue("safeFeel5");
    const agreePrivacy = agreePrivacyInput?.checked || false;
    const agreeNotice = agreeNoticeInput?.checked || false;

    const missing = [];

    if (!ownerName) {
      missing.push({ label: "성명", target: document.getElementById("ownerName") });
    }

    if (!phone) {
      missing.push({ label: "연락처", target: phoneInput });
    } else if (onlyDigits(phone).length < 10) {
      missing.push({ label: "연락처 형식 확인", target: phoneInput });
    }

    if (!shopName) {
      missing.push({ label: "점포명", target: document.getElementById("shopName") });
    }

    if (!businessType) {
      missing.push({ label: "업종 선택", target: businessTypeSelect });
    }

    if (businessType === "기타" && !businessTypeEtc) {
      missing.push({ label: "기타 업종 입력", target: businessTypeEtcInput });
    }

    if (!address) {
      missing.push({ label: "주소 입력", target: addressInput });
    }

    if (!selectedAddress) {
      missing.push({ label: "주소 검색", target: addressInput });
    }

    if (!salesRange) {
      missing.push({
        label: "연매출 구간",
        target: document.querySelector('input[name="salesRange"]')
      });
    }

    if (!crimeFear) {
      missing.push({
        label: "범죄피해 또는 위협 경험",
        target: document.querySelector('input[name="crimeFear"]')
      });
    }

    if (!nightBusiness) {
      missing.push({
        label: "야간 영업 여부",
        target: document.querySelector('input[name="nightBusiness"]')
      });
    }

    if (!darkArea) {
      missing.push({
        label: "점포 주변 환경",
        target: document.querySelector('input[name="darkArea"]')
      });
    }

    if (!soloWork) {
      missing.push({
        label: "혼자 근무 시간",
        target: document.querySelector('input[name="soloWork"]')
      });
    }

    if (!cctvStatus) {
      missing.push({
        label: "점포 내 CCTV 설치 여부",
        target: document.querySelector('input[name="cctvStatus"]')
      });
    }

    if (!securityCompany) {
      missing.push({
        label: "사설경비업체 이용 여부",
        target: document.querySelector('input[name="securityCompany"]')
      });
    }

    if (!hasBell) {
      missing.push({
        label: "비상벨 설치 여부",
        target: document.querySelector('input[name="hasBell"]')
      });
    }

    if (!safeFeel1) {
      missing.push({
        label: "체감안전도 설문 1번",
        target: document.querySelector('input[name="safeFeel1"]')
      });
    }

    if (!safeFeel2) {
      missing.push({
        label: "체감안전도 설문 2번",
        target: document.querySelector('input[name="safeFeel2"]')
      });
    }

    if (!safeFeel3) {
      missing.push({
        label: "체감안전도 설문 3번",
        target: document.querySelector('input[name="safeFeel3"]')
      });
    }

    if (!safeFeel4) {
      missing.push({
        label: "체감안전도 설문 4번",
        target: document.querySelector('input[name="safeFeel4"]')
      });
    }

    if (!safeFeel5) {
      missing.push({
        label: "체감안전도 설문 5번",
        target: document.querySelector('input[name="safeFeel5"]')
      });
    }

    if (selectedLat === null || selectedLon === null) {
      missing.push({
        label: "지도 위치 선택",
        target: document.getElementById("map")
      });
    }

    if (!agreePrivacy) {
      missing.push({ label: "개인정보 수집·이용 동의", target: agreePrivacyInput });
    }

    if (!agreeNotice) {
      missing.push({ label: "유의사항 확인", target: agreeNoticeInput });
    }

    return missing;
  }

  function resetRadioGroup(name) {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
      input.checked = false;
    });
  }

  function clearMarkerAndLocation() {
    selectedLon = null;
    selectedLat = null;

    if (currentMarkerLayer && typeof currentMarkerLayer.clearMarkers === "function") {
      currentMarkerLayer.clearMarkers();
    }

    setLocationMessage("주소 검색 후 지도를 클릭하면 최종 위치가 선택됩니다.");
  }

  function resetApplicationForm() {
    const form = document.querySelector("form");
    if (form) {
      form.reset();
    }

    if (phoneInput) phoneInput.value = "";
    if (annualSalesInput) annualSalesInput.value = "";
    if (businessTypeSelect) businessTypeSelect.value = "";
    if (businessTypeEtcInput) {
      businessTypeEtcInput.value = "";
      businessTypeEtcInput.disabled = true;
      businessTypeEtcInput.placeholder = "기타 업종일 경우 입력";
    }

    if (addressInput) addressInput.value = "";
    if (selectedAddressInput) selectedAddressInput.value = "";
    if (detailAddressInput) detailAddressInput.value = "";

    [
      "salesRange",
      "crimeFear",
      "nightBusiness",
      "darkArea",
      "soloWork",
      "cctvStatus",
      "securityCompany",
      "hasBell",
      "safeFeel1",
      "safeFeel2",
      "safeFeel3",
      "safeFeel4",
      "safeFeel5"
    ].forEach(resetRadioGroup);

    if (agreePrivacyInput) agreePrivacyInput.checked = false;
    if (agreeNoticeInput) agreeNoticeInput.checked = false;

    clearMarkerAndLocation();

    if (currentMap && currentMap.displayProjection && currentMap.projection) {
      const centerLon = 126.463;
      const centerLat = 34.816;
      const center = new OpenLayers.LonLat(centerLon, centerLat).transform(
        currentMap.displayProjection,
        currentMap.projection
      );
      currentMap.setCenter(center, 10);
    }
  }

  async function fetchStations() {
    const supabaseUrl = window.APP_CONFIG?.SUPABASE_URL;
    const anonKey = window.APP_CONFIG?.SUPABASE_ANON_KEY;

    if (!supabaseUrl || !anonKey) {
      console.warn("Supabase 설정값이 없어 stations를 불러오지 못했습니다.");
      return [];
    }

    const url =
      `${supabaseUrl}/rest/v1/stations` +
      `?select=id,station_name,station_label,area_name,is_active` +
      `&is_active=eq.true` +
      `&order=id.asc`;

    const response = await fetch(url, {
      method: "GET",
      headers: {
        apikey: anonKey,
        Authorization: `Bearer ${anonKey}`
      }
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error("경찰서 목록 조회 실패: " + errorText);
    }

    const data = await response.json();
    return Array.isArray(data) ? data : [];
  }

  async function insertApplication(payload) {
    const supabaseUrl = window.APP_CONFIG?.SUPABASE_URL;
    const anonKey = window.APP_CONFIG?.SUPABASE_ANON_KEY;

    if (!supabaseUrl || !anonKey) {
      throw new Error("Supabase 설정값이 없습니다. config.js를 확인해주세요.");
    }

    const response = await fetch(`${supabaseUrl}/rest/v1/applications`, {
      method: "POST",
      headers: {
        apikey: anonKey,
        Authorization: `Bearer ${anonKey}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal"
      },
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      let message = "신청 저장 중 오류가 발생했습니다.";
      try {
        const err = await response.json();
        message =
          err?.message ||
          err?.hint ||
          err?.details ||
          JSON.stringify(err);
      } catch (e) {
        message = await response.text();
      }
      throw new Error(message);
    }

    return { ok: true };
  }

  if (phoneInput) {
    phoneInput.addEventListener("input", function () {
      phoneInput.value = formatPhoneNumber(phoneInput.value);
    });

    phoneInput.addEventListener("blur", function () {
      phoneInput.value = formatPhoneNumber(phoneInput.value);
    });
  }

  if (annualSalesInput) {
    annualSalesInput.addEventListener("input", function () {
      annualSalesInput.value = formatNumberWithCommas(annualSalesInput.value);
    });

    annualSalesInput.addEventListener("blur", function () {
      annualSalesInput.value = formatNumberWithCommas(annualSalesInput.value);
    });
  }

  if (businessTypeSelect && businessTypeEtcInput) {
    function syncBusinessTypeEtcState() {
      if (businessTypeSelect.value === "기타") {
        businessTypeEtcInput.disabled = false;
        businessTypeEtcInput.placeholder = "기타 업종을 입력해주세요";
      } else {
        businessTypeEtcInput.value = "";
        businessTypeEtcInput.disabled = true;
        businessTypeEtcInput.placeholder = "기타 업종일 경우 입력";
      }
    }

    businessTypeSelect.addEventListener("change", syncBusinessTypeEtcState);
    syncBusinessTypeEtcState();
  }

  async function initVworldMap() {
    try {
      if (submitSectionDesc) {
        submitSectionDesc.textContent = "입력 내용을 확인한 뒤 신청서 제출 버튼을 누르면 실제로 접수됩니다.";
      }

      setResultMessage("신청서를 작성한 뒤 신청서 제출 버튼을 누르면 실제로 접수됩니다.");
      setLocationMessage("주소 검색 후 지도를 클릭하면 최종 위치가 선택됩니다.");

      try {
        stationRows = await fetchStations();
      } catch (stationError) {
        console.warn(stationError);
      }

      const apiKey = window.APP_CONFIG?.VWORLD_API_KEY;
      if (!apiKey) {
        setResultMessage("V월드 API 키가 비어 있습니다. config.js를 확인하세요.");
        return;
      }

      const domain = window.location.origin;

      await loadScript(
        "https://map.vworld.kr/js/map/OpenLayers-2.13/OpenLayers-2.13.js",
        "openlayers-script"
      );

      await loadScript(
        `https://map.vworld.kr/js/apis.do?type=Base&apiKey=${encodeURIComponent(apiKey)}&domain=${encodeURIComponent(domain)}`,
        "vworld-base-script"
      );

      if (typeof OpenLayers === "undefined") {
        setResultMessage("OpenLayers 객체가 없습니다. 스크립트 로드를 확인하세요.");
        return;
      }

      if (typeof vworld === "undefined") {
        setResultMessage("V월드 객체(vworld)가 없습니다. 등록한 서비스 URL과 현재 주소가 정확히 같은지 확인하세요.");
        return;
      }

      const map = new OpenLayers.Map("map", {
        projection: new OpenLayers.Projection("EPSG:900913"),
        displayProjection: new OpenLayers.Projection("EPSG:4326"),
        units: "m",
        numZoomLevels: 21,
        maxResolution: 156543.0339,
        maxExtent: new OpenLayers.Bounds(
          -20037508.34,
          -20037508.34,
          20037508.34,
          20037508.34
        )
      });

      currentMap = map;

      const vBase = new vworld.Layers.Base("VBASE");
      map.addLayer(vBase);

      const centerLon = 126.463;
      const centerLat = 34.816;

      const center = new OpenLayers.LonLat(centerLon, centerLat).transform(
        map.displayProjection,
        map.projection
      );
      map.setCenter(center, 10);

      const markerLayer = new OpenLayers.Layer.Markers("Markers");
      map.addLayer(markerLayer);
      current.addLayer(markerLayer);
      currentMarkerLayer = markerLayer;

      function updateSelectedPoint(lon, lat, sourceLabel = "지도 클릭") {
        selectedLon = lon;
        selectedLat = lat;

        markerLayer.clearMarkers();

        const markerLonLat = new OpenLayers.LonLat(lon, lat).transform(
          map.displayProjection,
          map.projection
        );

        const size = new OpenLayers.Size(21, 25);
        const offset = new OpenLayers.Pixel(-(size.w / 2), -size.h);
        const icon = new OpenLayers.Icon(
          "https://map.vworld.kr/images/ol3/marker_blue.png",
          size,
          offset
        );

        const marker = new OpenLayers.Marker(markerLonLat, icon);
        markerLayer.addMarker(marker);

        const moveCenter = new OpenLayers.LonLat(lon, lat).transform(
          map.displayProjection,
          map.projection
        );
        map.setCenter(moveCenter, 17);

        setLocationMessage(`
          <b>${sourceLabel}</b><br>
          선택 좌표(위도/경도): ${lat.toFixed(6)} / ${lon.toFixed(6)}
        `);
      }

      map.events.register("click", map, function (e) {
        const lonLat = map.getLonLatFromPixel(e.xy).transform(
          map.projection,
          map.displayProjection
        );

        updateSelectedPoint(lonLat.lon, lonLat.lat, "지도에서 최종 선택한 위치");
      });

      async function requestVworldCoord(query, type) {
        const callbackName =
          "vworldJsonpCallback_" +
          Date.now() +
          "_" +
          Math.floor(Math.random() * 10000);

        const baseUrl =
          "https://api.vworld.kr/req/address" +
          `?service=address` +
          `&request=getcoord` +
          `&version=2.0` +
          `&crs=epsg:4326` +
          `&address=${encodeURIComponent(query)}` +
          `&refine=true` +
          `&simple=false` +
          `&format=json` +
          `&errorformat=json` +
          `&type=${encodeURIComponent(type)}` +
          `&key=${encodeURIComponent(apiKey)}`;

        return await jsonpRequest(baseUrl, callbackName);
      }

      async function searchAddressToCoord() {
        const query = addressInput.value.trim();

        if (!query) {
          setResultMessage("주소를 먼저 입력해주세요.");
          return;
        }

        setResultMessage("주소를 찾는 중입니다...");

        try {
          let data = await requestVworldCoord(query, "road");

          if (
            !data ||
            !data.response ||
            data.response.status !== "OK" ||
            !data.response.result ||
            !data.response.result.point
          ) {
            data = await requestVworldCoord(query, "parcel");
          }

          if (
            !data ||
            !data.response ||
            data.response.status !== "OK" ||
            !data.response.result ||
            !data.response.result.point
          ) {
            setResultMessage("주소를 찾지 못했습니다. 시/군/구와 건물번호까지 더 자세히 입력해주세요.");
            return;
          }

          const lon = parseFloat(data.response.result.point.x);
          const lat = parseFloat(data.response.result.point.y);

          if (Number.isNaN(lon) || Number.isNaN(lat)) {
            setResultMessage("좌표 변환 결과가 올바르지 않습니다.");
            return;
          }

          selectedAddressInput.value = query;
          updateSelectedPoint(lon, lat, "주소 검색 결과 위치");
          setResultMessage("주소 검색이 완료되었습니다. 위치가 맞지 않으면 지도에서 다시 선택해주세요.");
        } catch (error) {
          console.error(error);
          setResultMessage("주소 검색 중 오류가 발생했습니다: " + error.message);
        }
      }

      if (searchAddressBtn) {
        searchAddressBtn.addEventListener("click", searchAddressToCoord);
      }

      if (addressInput) {
        addressInput.addEventListener("keydown", function (e) {
          if (e.key === "Enter") {
            e.preventDefault();
            searchAddressToCoord();
          }
        });
      }

      if (submitBtn) {
        submitBtn.addEventListener("click", async function () {
          if (isSubmitting) {
            alert("이미 제출 중입니다. 잠시만 기다려주세요.");
            return;
          }

          if (hasJustSubmitted) {
            alert("이미 정상 접수되었습니다. 새로 신청하려면 초기화된 폼에 다시 입력해주세요.");
            return;
          }

          const missingFields = validateRequiredFields();

          if (missingFields.length > 0) {
            setResultMessage(`
              <div style="padding:16px;border:1px solid #fecaca;border-radius:12px;background:#fff1f2;color:#991b1b;line-height:1.8;">
                <b>입력 확인이 필요합니다.</b><br>
                다음 항목을 확인해주세요.<br>
                - ${missingFields.map(item => escapeHtml(item.label)).join("<br>- ")}
              </div>
            `);

            focusAndScroll(missingFields[0].target);
            return;
          }

          isSubmitting = true;
          setSubmitPending(true);

          try {
            const ownerName = document.getElementById("ownerName")?.value.trim() || "";
            const phone = phoneInput?.value.trim() || "";
            const shopName = document.getElementById("shopName")?.value.trim() || "";
            const businessType = businessTypeSelect?.value || "";
            const businessTypeEtc = businessTypeEtcInput?.value.trim() || "";
            const typedAddress = addressInput?.value.trim() || "";
            const selectedAddress = selectedAddressInput?.value.trim() || "";
            const detailAddress = detailAddressInput?.value.trim() || "";
            const salesRange = getRadioValue("salesRange");
            const annualSalesValue = annualSalesInput?.value.trim() || "";
            const annualSalesNumber = parseNumberOrNull(annualSalesValue);

            const crimeFear = getRadioValue("crimeFear");
            const nightBusiness = getRadioValue("nightBusiness");
            const darkArea = getRadioValue("darkArea");
            const soloWork = getRadioValue("soloWork");
            const cctvStatus = getRadioValue("cctvStatus");
            const securityCompany = getRadioValue("securityCompany");
            const hasBell = getRadioValue("hasBell");

            const matchedStation = inferStationByAddress(selectedAddress || typedAddress);

            const payload = {
              applicant_name: ownerName,
              business_name: shopName,
              business_type: businessType || null,
              business_type_other: businessType === "기타" ? (businessTypeEtc || null) : null,
              phone: formatPhoneNumber(phone),
              email: null,
              address_road: selectedAddress,
              address_jibun: null,
              address_detail: detailAddress || null,
              latitude: Number(selectedLat.toFixed(7)),
              longitude: Number(selectedLon.toFixed(7)),
              annual_sales: annualSalesNumber,
              sales_band: salesRange || null,
              has_cctv: cctvStatus !== "없음",
              has_emergency_bell: hasBell === "예",
              uses_security_company: securityCompany === "이용 중",
              other_security: null,
              apply_reason: buildApplyReason(),
              requested_item: null,
              etc_note: buildEtcNote(),
              privacy_agreed: agreePrivacyInput?.checked || false,
              notice_agreed: agreeNoticeInput?.checked || false,
              survey_crime_anxiety: crimeFear || null,
              survey_late_night: nightBusiness || null,
              survey_dark_area: darkArea || null,
              survey_single_worker: soloWork || null,
              station_id: matchedStation ? matchedStation.id : null,
              status: "submitted"
            };

            await insertApplication(payload);
            hasJustSubmitted = true;

            const businessTypeText =
              businessType === "기타" && businessTypeEtc
                ? `${businessType} (${businessTypeEtc})`
                : businessType;

            const fullAddress = detailAddress
              ? `${selectedAddress}, ${detailAddress}`
              : selectedAddress;

            const infoRows =
              createInfoRow("접수상태", "정상 저장 완료") +
              createInfoRow("접수일시", formatDateTime(new Date())) +
              createInfoRow("성명", ownerName) +
              createInfoRow("연락처", formatPhoneNumber(phone)) +
              createInfoRow("점포명", shopName) +
              createInfoRow("업종", businessTypeText) +
              createInfoRow("주소", fullAddress) +
              createInfoRow("관할 경찰서", matchedStation?.station_label || "(자동 판별 안됨)") +
              createInfoRow("연매출 구간", salesRange) +
              createInfoRow("연매출 기재", annualSalesValue || "(미입력)") +
              createInfoRow("위도 / 경도", `${selectedLat.toFixed(6)} / ${selectedLon.toFixed(6)}`);

            setResultMessage(`
              <div style="padding:20px;border:1px solid #cfe0ff;border-radius:16px;background:#f8fbff;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                  <div style="width:36px;height:36px;border-radius:999px;background:#e8f0ff;display:flex;align-items:center;justify-content:center;font-size:18px;">✓</div>
                  <div style="font-size:20px;font-weight:800;color:#1d4ed8;">신청서가 정상 접수되었습니다.</div>
                </div>

                <div style="font-size:14px;line-height:1.8;color:#475569;margin-bottom:14px;">
                  입력하신 신청 내용이 시스템에 정상 저장되었습니다.<br>
                  신청 이후 관할 경찰서 CPO가 접수 내용을 검토할 예정입니다.
                </div>

                <div style="border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;padding:6px 14px;margin-bottom:16px;">
                  ${infoRows}
                </div>

                <div style="padding:14px 16px;border-radius:12px;background:#eef4ff;border:1px solid #d7e5ff;color:#1f3b63;line-height:1.8;font-size:14px;">
                  <b>안내사항</b><br>
                  1. 신청 이후 관할 경찰서 CPO가 접수 내용을 검토할 예정입니다.<br>
                  2. 필요 시 사업자등록증, 매출현황 증빙자료 등 추가 서류 제출을 요청할 수 있습니다.<br>
                  3. 필요 시 현장 확인 또는 연락이 진행될 수 있습니다.<br>
                  4. 최종 선정 결과는 개별 연락드릴 예정입니다.
                </div>
              </div>
            `);

            if (resultBox) {
              resultBox.scrollIntoView({
                behavior: "smooth",
                block: "center"
              });
            }

            alert("신청서가 정상 접수되었습니다.");

            resetApplicationForm();
            hasJustSubmitted = false;
            setResultMessage("신청서를 작성한 뒤 신청서 제출 버튼을 누르면 실제로 접수됩니다.");
          } catch (error) {
            console.error(error);
            hasJustSubmitted = false;
            setResultMessage(`
              <div style="padding:16px;border:1px solid #fecaca;border-radius:12px;background:#fff1f2;color:#991b1b;line-height:1.8;">
                <b>신청 저장 중 오류가 발생했습니다.</b><br>
                ${escapeHtml(error.message || "알 수 없는 오류")}
              </div>
            `);
          } finally {
            isSubmitting = false;
            setSubmitPending(false);
          }
        });
      }
    } catch (error) {
      console.error(error);
      setResultMessage("오류: " + error.message);
    }
  }

  initVworldMap();
});