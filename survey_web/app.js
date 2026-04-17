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
  let selectedOfficialAddress = "";
  let selectedSigungu = "";
  let stationRows = [];
  let currentMap = null;
  let currentMarkerLayer = null;
  let isSubmitting = false;
  let submitCooldownTimer = null;

  const addressSearchState = {
    keyword: "",
    page: 1,
    totalCount: 0,
    countPerPage: 10,
    results: [],
    selectedIndex: -1,
    isLoading: false,
  };

  const SUBMIT_LOCK_STORAGE_KEY = "jeonnam_security_support_submit_lock";
  const SUBMIT_PENDING_LOCK_MS = 60 * 1000;
  const SUBMIT_SUCCESS_COOLDOWN_MS = 7 * 1000;
  const FALLBACK_STATION_AREAS = [
    { area_name: "목포", station_label: "목포경찰서" },
    { area_name: "여수", station_label: "여수경찰서" },
    { area_name: "순천", station_label: "순천경찰서" },
    { area_name: "나주", station_label: "나주경찰서" },
    { area_name: "광양", station_label: "광양경찰서" },
    { area_name: "고흥", station_label: "고흥경찰서" },
    { area_name: "해남", station_label: "해남경찰서" },
    { area_name: "무안", station_label: "무안경찰서" },
    { area_name: "장흥", station_label: "장흥경찰서" },
    { area_name: "보성", station_label: "보성경찰서" },
    { area_name: "영광", station_label: "영광경찰서" },
    { area_name: "화순", station_label: "화순경찰서" },
    { area_name: "함평", station_label: "함평경찰서" },
    { area_name: "영암", station_label: "영암경찰서" },
    { area_name: "장성", station_label: "장성경찰서" },
    { area_name: "강진", station_label: "강진경찰서" },
    { area_name: "담양", station_label: "담양경찰서" },
    { area_name: "곡성", station_label: "곡성경찰서" },
    { area_name: "완도", station_label: "완도경찰서" },
    { area_name: "진도", station_label: "진도경찰서" },
    { area_name: "구례", station_label: "구례경찰서" },
    { area_name: "신안", station_label: "신안경찰서" }
  ];

  function setResultMessage(message) {
    if (resultBox) resultBox.innerHTML = message;
  }

  function setLocationMessage(message) {
    if (locationInfo) locationInfo.innerHTML = message;
  }

  function setSubmitState(state) {
    if (!submitBtn) return;

    if (state === "pending") {
      submitBtn.disabled = true;
      submitBtn.textContent = "제출 중입니다...";
      submitBtn.style.opacity = "0.7";
      submitBtn.style.cursor = "not-allowed";
      return;
    }

    if (state === "success-lock") {
      submitBtn.disabled = true;
      submitBtn.textContent = "접수 완료";
      submitBtn.style.opacity = "0.7";
      submitBtn.style.cursor = "not-allowed";
      return;
    }

    submitBtn.disabled = false;
    submitBtn.textContent = "신청서 제출";
    submitBtn.style.opacity = "1";
    submitBtn.style.cursor = "pointer";
  }

  function clearSubmitCooldownTimer() {
    if (submitCooldownTimer) {
      clearTimeout(submitCooldownTimer);
      submitCooldownTimer = null;
    }
  }

  function readSubmitLock() {
    try {
      const raw = sessionStorage.getItem(SUBMIT_LOCK_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch (e) {
      return null;
    }
  }

  function writeSubmitLock(state) {
    try {
      sessionStorage.setItem(
        SUBMIT_LOCK_STORAGE_KEY,
        JSON.stringify({
          state,
          ts: Date.now()
        })
      );
    } catch (e) {}
  }

  function clearSubmitLock() {
    try {
      sessionStorage.removeItem(SUBMIT_LOCK_STORAGE_KEY);
    } catch (e) {}
  }

  function getActiveSubmitLock() {
    const lock = readSubmitLock();
    if (!lock || !lock.state || !lock.ts) return null;

    const age = Date.now() - Number(lock.ts || 0);

    if (lock.state === "pending" && age < SUBMIT_PENDING_LOCK_MS) {
      return { state: "pending", remainingMs: SUBMIT_PENDING_LOCK_MS - age };
    }

    if (lock.state === "success" && age < SUBMIT_SUCCESS_COOLDOWN_MS) {
      return { state: "success", remainingMs: SUBMIT_SUCCESS_COOLDOWN_MS - age };
    }

    clearSubmitLock();
    return null;
  }

  function applySubmitLockState() {
    const lock = getActiveSubmitLock();

    clearSubmitCooldownTimer();

    if (!lock) {
      setSubmitState("idle");
      return;
    }

    if (lock.state === "pending") {
      setSubmitState("pending");
      return;
    }

    if (lock.state === "success") {
      setSubmitState("success-lock");
      submitCooldownTimer = setTimeout(() => {
        clearSubmitLock();
        setSubmitState("idle");
      }, Math.max(lock.remainingMs, 0));
    }
  }

  // 제출 완료/오류 팝업
  function ensureModalElement() {
    let modal = document.getElementById("submitCompleteModal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "submitCompleteModal";
    modal.style.position = "fixed";
    modal.style.inset = "0";
    modal.style.background = "rgba(15, 23, 42, 0.45)";
    modal.style.display = "none";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.style.padding = "20px";
    modal.style.zIndex = "99999";

    modal.innerHTML = `
      <div style="width:100%;max-width:520px;background:#ffffff;border-radius:18px;box-shadow:0 20px 45px rgba(15,23,42,0.22);overflow:hidden;border:1px solid #dbe4f0;">
        <div id="submitCompleteModalHeader" style="padding:18px 22px;background:#eef4ff;border-bottom:1px solid #d7e5ff;">
          <div id="submitCompleteModalTitle" style="font-size:22px;font-weight:800;color:#1d4ed8;">신청이 정상적으로 접수되었습니다.</div>
        </div>
        <div style="padding:22px;">
          <div id="submitCompleteModalBody" style="font-size:15px;line-height:1.9;color:#334155;"></div>
          <button id="submitCompleteModalConfirm" type="button" style="margin-top:20px;width:100%;height:48px;border:none;border-radius:12px;background:#1f5aa8;color:#ffffff;font-size:16px;font-weight:800;cursor:pointer;">확인</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    return modal;
  }

  // 주소 검색 결과 팝업
  function ensureAddressSearchModal() {
    let modal = document.getElementById("addressSearchModal");
    if (modal) return modal;

    modal = document.createElement("div");
    modal.id = "addressSearchModal";
    modal.style.position = "fixed";
    modal.style.inset = "0";
    modal.style.background = "rgba(15, 23, 42, 0.45)";
    modal.style.display = "none";
    modal.style.alignItems = "center";
    modal.style.justifyContent = "center";
    modal.style.padding = "10px";
    modal.style.zIndex = "99998";

    modal.innerHTML = `
      <div style="width:100%;max-width:430px;background:#ffffff;border-radius:16px;box-shadow:0 16px 32px rgba(15,23,42,0.18);overflow:hidden;border:1px solid #dbe4f0;">
        <div style="padding:14px 16px;background:#eef4ff;border-bottom:1px solid #d7e5ff;display:flex;justify-content:space-between;align-items:center;gap:10px;">
          <div>
            <div style="font-size:18px;font-weight:800;color:#1d4ed8;">주소 검색 결과</div>
            <div id="addressSearchModalSubTitle" style="margin-top:4px;font-size:12px;color:#475569;">검색 결과 목록에서 원하는 주소를 선택해주세요.</div>
          </div>
          <button id="addressSearchModalCloseTop" type="button" style="border:none;background:#dbeafe;color:#1d4ed8;border-radius:10px;padding:8px 12px;font-size:12px;font-weight:700;cursor:pointer;">닫기</button>
        </div>
        <div style="padding:16px;">
          <div id="addressSearchModalResultList" style="display:flex;flex-direction:column;gap:8px;min-height:120px;"></div>
          <div id="addressSearchModalEmpty" style="display:none;padding:20px 14px;border:1px dashed #cbd5e1;border-radius:12px;background:#f8fafc;color:#475569;text-align:center;line-height:1.7;font-size:13px;">검색 결과가 없습니다.</div>
          <div style="margin-top:14px;display:flex;justify-content:center;align-items:center;gap:6px;flex-wrap:wrap;">
            <button id="addressPrevPageBtn" type="button" style="height:36px;border:none;border-radius:10px;background:#e2e8f0;color:#334155;padding:0 12px;font-weight:700;cursor:pointer;font-size:13px;">이전</button>
            <div id="addressPageButtons" style="display:flex;gap:6px;flex-wrap:wrap;"></div>
            <button id="addressNextPageBtn" type="button" style="height:36px;border:none;border-radius:10px;background:#e2e8f0;color:#334155;padding:0 12px;font-weight:700;cursor:pointer;font-size:13px;">다음</button>
          </div>
          <button id="addressSearchModalCloseBottom" type="button" style="margin-top:14px;width:100%;height:42px;border:none;border-radius:12px;background:#1f5aa8;color:#ffffff;font-size:14px;font-weight:800;cursor:pointer;">닫기</button>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    return modal;
  }

  function showModal(options = {}) {
    const modal = ensureModalElement();
    const titleEl = document.getElementById("submitCompleteModalTitle");
    const bodyEl = document.getElementById("submitCompleteModalBody");
    const confirmBtn = document.getElementById("submitCompleteModalConfirm");
    const headerEl = document.getElementById("submitCompleteModalHeader");

    if (!titleEl || !bodyEl || !confirmBtn || !headerEl) {
      alert(options.title || "처리가 완료되었습니다.");
      return Promise.resolve();
    }

    titleEl.textContent = options.title || "처리가 완료되었습니다.";
    bodyEl.innerHTML = options.body || "";
    confirmBtn.textContent = options.buttonText || "확인";

    const tone = options.tone || "info";
    if (tone === "success") {
      headerEl.style.background = "#eefbf3";
      headerEl.style.borderBottom = "1px solid #ccead5";
      titleEl.style.color = "#166534";
    } else if (tone === "error") {
      headerEl.style.background = "#fff1f2";
      headerEl.style.borderBottom = "1px solid #fecdd3";
      titleEl.style.color = "#be123c";
    } else {
      headerEl.style.background = "#eef4ff";
      headerEl.style.borderBottom = "1px solid #d7e5ff";
      titleEl.style.color = "#1d4ed8";
    }

    modal.style.display = "flex";

    return new Promise((resolve) => {
      function closeModal() {
        modal.style.display = "none";
        confirmBtn.removeEventListener("click", onConfirm);
        modal.removeEventListener("click", onBackdrop);
        document.removeEventListener("keydown", onKeydown);
        resolve();
      }

      function onConfirm() {
        closeModal();
      }

      function onBackdrop(e) {
        if (e.target === modal) closeModal();
      }

      function onKeydown(e) {
        if (e.key === "Escape" || e.key === "Enter") closeModal();
      }

      confirmBtn.addEventListener("click", onConfirm);
      modal.addEventListener("click", onBackdrop);
      document.addEventListener("keydown", onKeydown);
      confirmBtn.focus();
    });
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
        if (script.parentNode) script.parentNode.removeChild(script);
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
    if (typeof target.focus === "function") target.focus();
    target.scrollIntoView({ behavior: "smooth", block: "center" });
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

  function buildOfficialAddressFromRefined(refined) {
    if (!refined) return "";
    if (refined.text && String(refined.text).trim()) {
      return String(refined.text).trim();
    }

    const s = refined.structure || {};
    const parts = [
      s.level1,
      s.level2,
      s.level3,
      s.level4A,
      s.level4L,
      s.level5,
      s.detail
    ]
      .map((v) => String(v || "").trim())
      .filter(Boolean);

    return parts.join(" ").replace(/\s+/g, " ").trim();
  }

  function extractSigunguFromRefined(refined) {
    const s = refined?.structure || {};
    const preferred = [s.level2, s.level3]
      .map((v) => String(v || "").trim())
      .find(Boolean);

    if (preferred) return preferred;

    const officialText = buildOfficialAddressFromRefined(refined);
    const matches = officialText.match(/[가-힣]+(?:시|군|구)/g);
    return matches && matches.length > 0 ? matches[0] : "";
  }

  function getStationCandidates() {
    if (Array.isArray(stationRows) && stationRows.length > 0) {
      return stationRows;
    }
    return FALLBACK_STATION_AREAS;
  }

  function normalizeAddressKeyword(value) {
    let text = String(value || "").trim();
    if (!text) return "";

    text = text.replace(/\s+/g, " ");
    text = text.replace(/([가-힣A-Za-z·\d]+로|[가-힣A-Za-z·\d]+길)(\d+)/g, "$1 $2");
    text = text.replace(/(읍|면|동)([가-힣A-Za-z·\d])/g, "$1 $2");

    return text.trim();
  }

  function inferStationByAddress(addressText, sigunguText = "") {
    const normalizedAddress = normalizeText(addressText);
    const normalizedSigungu = normalizeText(sigunguText);
    const rows = getStationCandidates();

    if ((!normalizedAddress && !normalizedSigungu) || rows.length === 0) {
      return null;
    }

    const candidates = [];

    rows.forEach((row) => {
      const areaName = String(row.area_name || "").trim();
      const stationName = String(row.station_name || "").trim();
      const stationLabel = String(row.station_label || "").trim();
      if (!areaName && !stationName && !stationLabel) return;

      const areaTokens = [
        areaName,
        `${areaName}시`,
        `${areaName}군`,
        `${areaName}구`,
        stationName.replace("경찰서", "").trim(),
        stationLabel.replace("경찰서", "").trim()
      ]
        .map((v) => normalizeText(v))
        .filter(Boolean);

      let score = 0;

      areaTokens.forEach((token) => {
        if (!token) return;
        if (normalizedSigungu === token) score = Math.max(score, 12);
        else if (normalizedSigungu.includes(token)) score = Math.max(score, 11);
        else if (normalizedAddress.includes(token)) score = Math.max(score, 9);
      });

      if (normalizedAddress.includes(normalizeText(stationName))) score = Math.max(score, 5);
      if (normalizedAddress.includes(normalizeText(stationLabel))) score = Math.max(score, 5);

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

    if (!ownerName) missing.push({ label: "성명", target: document.getElementById("ownerName") });

    if (!phone) {
      missing.push({ label: "연락처", target: phoneInput });
    } else if (onlyDigits(phone).length < 10) {
      missing.push({ label: "연락처 형식 확인", target: phoneInput });
    }

    if (!shopName) missing.push({ label: "점포명", target: document.getElementById("shopName") });
    if (!businessType) missing.push({ label: "업종 선택", target: businessTypeSelect });

    if (businessType === "기타" && !businessTypeEtc) {
      missing.push({ label: "기타 업종 입력", target: businessTypeEtcInput });
    }

    if (!address) missing.push({ label: "주소 입력", target: addressInput });
    if (!selectedAddress) missing.push({ label: "주소 검색", target: addressInput });

    if (!salesRange) {
      missing.push({ label: "연매출 구간", target: document.querySelector('input[name="salesRange"]') });
    }

    if (!crimeFear) {
      missing.push({ label: "범죄피해 또는 위협 경험", target: document.querySelector('input[name="crimeFear"]') });
    }

    if (!nightBusiness) {
      missing.push({ label: "야간 영업 여부", target: document.querySelector('input[name="nightBusiness"]') });
    }

    if (!darkArea) {
      missing.push({ label: "점포 주변 환경", target: document.querySelector('input[name="darkArea"]') });
    }

    if (!soloWork) {
      missing.push({ label: "혼자 근무 시간", target: document.querySelector('input[name="soloWork"]') });
    }

    if (!cctvStatus) {
      missing.push({ label: "점포 내 CCTV 설치 여부", target: document.querySelector('input[name="cctvStatus"]') });
    }

    if (!securityCompany) {
      missing.push({ label: "사설경비업체 이용 여부", target: document.querySelector('input[name="securityCompany"]') });
    }

    if (!hasBell) {
      missing.push({ label: "비상벨 설치 여부", target: document.querySelector('input[name="hasBell"]') });
    }

    if (!safeFeel1) missing.push({ label: "체감안전도 설문 1번", target: document.querySelector('input[name="safeFeel1"]') });
    if (!safeFeel2) missing.push({ label: "체감안전도 설문 2번", target: document.querySelector('input[name="safeFeel2"]') });
    if (!safeFeel3) missing.push({ label: "체감안전도 설문 3번", target: document.querySelector('input[name="safeFeel3"]') });
    if (!safeFeel4) missing.push({ label: "체감안전도 설문 4번", target: document.querySelector('input[name="safeFeel4"]') });
    if (!safeFeel5) missing.push({ label: "체감안전도 설문 5번", target: document.querySelector('input[name="safeFeel5"]') });

    if (selectedLat === null || selectedLon === null) {
      missing.push({ label: "지도 위치 선택", target: document.getElementById("map") });
    }

    if (!agreePrivacy) missing.push({ label: "개인정보 수집·이용 동의", target: agreePrivacyInput });
    if (!agreeNotice) missing.push({ label: "유의사항 확인", target: agreeNoticeInput });

    return missing;
  }

  function resetRadioGroup(name) {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
      input.checked = false;
    });
  }

  function resetAddressSearchState() {
    addressSearchState.keyword = "";
    addressSearchState.page = 1;
    addressSearchState.totalCount = 0;
    addressSearchState.countPerPage = 10;
    addressSearchState.results = [];
    addressSearchState.selectedIndex = -1;
    addressSearchState.isLoading = false;
  }

  function resetApplicationForm() {
    const form = document.querySelector("form");
    if (form) form.reset();

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

    selectedLon = null;
    selectedLat = null;
    selectedOfficialAddress = "";
    selectedSigungu = "";
    resetAddressSearchState();

    if (currentMarkerLayer && typeof currentMarkerLayer.clearMarkers === "function") {
      currentMarkerLayer.clearMarkers();
    }

    setLocationMessage("주소 검색 후 지도를 클릭하면 최종 위치가 선택됩니다.");

    if (currentMap && typeof currentMap.setCenter === "function" && currentMap.displayProjection && currentMap.projection) {
      const centerLon = 126.463;
      const centerLat = 34.816;
      const center = new OpenLayers.LonLat(centerLon, centerLat).transform(
        currentMap.displayProjection,
        currentMap.projection
      );
      currentMap.setCenter(center, 10);
    }

    applySubmitLockState();
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

  function createAddressCardHtml(item, index) {
    const roadAddr = escapeHtml(item.roadAddr || "");
    const jibunAddr = escapeHtml(item.jibunAddr || "");
    const zipNo = escapeHtml(item.zipNo || "");

    return `
      <button type="button" data-address-index="${index}" style="width:100%;text-align:left;border:1px solid #dbe4f0;border-radius:14px;background:#ffffff;padding:16px;cursor:pointer;transition:all .15s ease;">
        <div style="font-size:15px;font-weight:800;color:#0f172a;line-height:1.7;">${roadAddr}</div>
        <div style="margin-top:6px;font-size:13px;color:#64748b;line-height:1.7;">지번: ${jibunAddr || "-"}</div>
        <div style="margin-top:4px;font-size:12px;color:#94a3b8;">우편번호: ${zipNo || "-"}</div>
      </button>
    `;
  }

  function closeAddressSearchModal() {
    const modal = document.getElementById("addressSearchModal");
    if (!modal) return;
    modal.style.display = "none";
  }

  function bindAddressSearchModalEvents(apiKey, updateSelectedPoint) {
    const modal = ensureAddressSearchModal();
    const closeTop = document.getElementById("addressSearchModalCloseTop");
    const closeBottom = document.getElementById("addressSearchModalCloseBottom");
    const prevBtn = document.getElementById("addressPrevPageBtn");
    const nextBtn = document.getElementById("addressNextPageBtn");
    const listEl = document.getElementById("addressSearchModalResultList");

    if (closeTop) closeTop.onclick = closeAddressSearchModal;
    if (closeBottom) closeBottom.onclick = closeAddressSearchModal;
    if (modal) {
      modal.onclick = function (e) {
        if (e.target === modal) closeAddressSearchModal();
      };
    }

    if (prevBtn) {
      prevBtn.onclick = async function () {
        if (addressSearchState.page <= 1 || addressSearchState.isLoading) return;
        await searchAddressList(addressSearchState.keyword, addressSearchState.page - 1, apiKey, updateSelectedPoint);
      };
    }

    if (nextBtn) {
      nextBtn.onclick = async function () {
        const totalPages = Math.max(1, Math.ceil(addressSearchState.totalCount / addressSearchState.countPerPage));
        if (addressSearchState.page >= totalPages || addressSearchState.isLoading) return;
        await searchAddressList(addressSearchState.keyword, addressSearchState.page + 1, apiKey, updateSelectedPoint);
      };
    }

    if (listEl) {
      listEl.onclick = async function (e) {
        const button = e.target.closest("[data-address-index]");
        if (!button) return;
        const idx = Number(button.getAttribute("data-address-index"));
        if (!Number.isFinite(idx)) return;
        const selected = addressSearchState.results[idx];
        if (!selected) return;
        try {
          const coord = await requestVworldCoordByAddress(apiKey, selected.roadAddr || selected.jibunAddr || "");
          const lon = parseFloat(coord.response.result.point.x);
          const lat = parseFloat(coord.response.result.point.y);
          if (Number.isNaN(lon) || Number.isNaN(lat)) {
            throw new Error("좌표 변환 결과가 올바르지 않습니다.");
          }

          selectedOfficialAddress = String(selected.roadAddr || selected.jibunAddr || "").trim();
          selectedSigungu = extractSigunguFromAddressText(selectedOfficialAddress);
          if (selectedAddressInput) selectedAddressInput.value = selectedOfficialAddress;
          updateSelectedPoint(lon, lat, "주소 검색 결과 위치");
          closeAddressSearchModal();
          setResultMessage("주소 검색이 완료되었습니다. 선택한 주소가 반영되었습니다. 위치가 맞지 않으면 지도에서 다시 선택해주세요.");
        } catch (error) {
          console.error(error);
          setResultMessage("선택한 주소 좌표를 가져오는 중 오류가 발생했습니다: " + error.message);
        }
      };
    }
  }

  function extractSigunguFromAddressText(addressText) {
    const text = String(addressText || "").trim();
    const matches = text.match(/[가-힣]+(?:시|군|구)/g);
    return matches && matches.length > 0 ? matches[0] : "";
  }

  function renderAddressSearchModal() {
    const modal = ensureAddressSearchModal();
    const subTitle = document.getElementById("addressSearchModalSubTitle");
    const listEl = document.getElementById("addressSearchModalResultList");
    const emptyEl = document.getElementById("addressSearchModalEmpty");
    const pageButtonsEl = document.getElementById("addressPageButtons");
    const prevBtn = document.getElementById("addressPrevPageBtn");
    const nextBtn = document.getElementById("addressNextPageBtn");

    if (!modal || !subTitle || !listEl || !emptyEl || !pageButtonsEl || !prevBtn || !nextBtn) return;

    const totalPages = Math.max(1, Math.ceil(addressSearchState.totalCount / addressSearchState.countPerPage));
    subTitle.textContent = addressSearchState.isLoading
      ? "주소를 검색하고 있습니다..."
      : `검색 결과 ${addressSearchState.totalCount}건 중 ${addressSearchState.page}페이지`;

    if (addressSearchState.results.length > 0) {
      listEl.style.display = "flex";
      emptyEl.style.display = "none";
      listEl.innerHTML = addressSearchState.results
        .map((item, idx) => createAddressCardHtml(item, idx))
        .join("");
    } else {
      listEl.style.display = "none";
      emptyEl.style.display = "block";
      emptyEl.textContent = addressSearchState.isLoading
        ? "주소를 검색하고 있습니다..."
        : "검색 결과가 없습니다. 시/군/구와 건물번호까지 조금 더 자세히 입력해주세요.";
    }

    prevBtn.disabled = addressSearchState.page <= 1 || addressSearchState.isLoading;
    nextBtn.disabled = addressSearchState.page >= totalPages || addressSearchState.isLoading;
    prevBtn.style.opacity = prevBtn.disabled ? "0.5" : "1";
    nextBtn.style.opacity = nextBtn.disabled ? "0.5" : "1";
    prevBtn.style.cursor = prevBtn.disabled ? "not-allowed" : "pointer";
    nextBtn.style.cursor = nextBtn.disabled ? "not-allowed" : "pointer";

    pageButtonsEl.innerHTML = "";
    for (let i = 1; i <= totalPages; i++) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = String(i);
      btn.disabled = addressSearchState.isLoading;
      btn.style.height = "36px";
      btn.style.minWidth = "36px";
      btn.style.padding = "0 10px";
      btn.style.border = "none";
      btn.style.borderRadius = "10px";
      btn.style.fontWeight = "800";
      btn.style.fontSize = "13px";
      btn.style.cursor = addressSearchState.isLoading ? "not-allowed" : "pointer";
      if (i === addressSearchState.page) {
        btn.style.background = "#1f5aa8";
        btn.style.color = "#ffffff";
      } else {
        btn.style.background = "#e2e8f0";
        btn.style.color = "#334155";
      }
      btn.onclick = function () {
        if (i === addressSearchState.page || addressSearchState.isLoading) return;
        const apiKey = window.APP_CONFIG?.VWORLD_API_KEY;
        searchAddressList(addressSearchState.keyword, i, apiKey, window.__updateSelectedPointRef);
      };
      pageButtonsEl.appendChild(btn);
    }

    modal.style.display = "flex";
  }

  async function searchAddressList(keyword, page, apiKey, updateSelectedPoint) {
    const jusoKey = window.APP_CONFIG?.JUSO_CONFM_KEY;
    if (!jusoKey) {
      throw new Error("config.js에 JUSO_CONFM_KEY가 없습니다.");
    }

    addressSearchState.keyword = String(keyword || "").trim();
    addressSearchState.page = page;
    addressSearchState.isLoading = true;
    addressSearchState.results = [];
    renderAddressSearchModal();

    try {
      const url = "https://business.juso.go.kr/addrlink/addrLinkApiJsonp.do" +
        `?confmKey=${encodeURIComponent(jusoKey)}` +
        `&currentPage=${encodeURIComponent(page)}` +
        `&countPerPage=${encodeURIComponent(addressSearchState.countPerPage)}` +
        `&keyword=${encodeURIComponent(addressSearchState.keyword)}` +
        `&resultType=json`;

      const callbackName = "jusoListCallback_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
      const data = await jsonpRequest(url, callbackName);
      const results = data?.results || {};
      const common = results.common || {};
      const errorCode = String(common.errorCode || "0");
      const errorMessage = String(common.errorMessage || "");

      if (errorCode !== "0") {
        throw new Error(errorMessage || "주소 검색 중 오류가 발생했습니다.");
      }

      addressSearchState.totalCount = Number(common.totalCount || 0);
      addressSearchState.results = Array.isArray(results.juso) ? results.juso : [];
      addressSearchState.isLoading = false;
      window.__updateSelectedPointRef = updateSelectedPoint;
      renderAddressSearchModal();
    } catch (error) {
      addressSearchState.totalCount = 0;
      addressSearchState.results = [];
      addressSearchState.isLoading = false;
      renderAddressSearchModal();
      setResultMessage("주소 검색 중 오류가 발생했습니다: " + error.message);
      throw error;
    }
  }

  async function requestVworldCoordByAddress(apiKey, query) {
    const baseUrl = "https://api.vworld.kr/req/address";

    async function call(type) {
      const callbackName = "vworldJsonpCallback_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
      const url =
        `${baseUrl}?service=address` +
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
      return jsonpRequest(url, callbackName);
    }

    let data = await call("road");
    if (!data?.response || data.response.status !== "OK" || !data?.response?.result?.point) {
      data = await call("parcel");
    }

    if (!data?.response || data.response.status !== "OK" || !data?.response?.result?.point) {
      throw new Error("선택한 주소의 좌표를 찾지 못했습니다.");
    }
    return data;
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
        submitSectionDesc.textContent = "입력 내용을 확인한 뒤 신청서 제출 버튼을 누르면 실제로 접수됩니다. 접수 후에는 확인 팝업이 표시되고, 잠시 동안 중복 제출이 차단됩니다.";
      }

      setResultMessage("신청서를 작성한 뒤 신청서 제출 버튼을 누르면 실제로 접수됩니다.");
      applySubmitLockState();
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
          정식 주소: ${escapeHtml(selectedOfficialAddress || "(미확정)")}<br>
          선택 좌표(위도/경도): ${lat.toFixed(6)} / ${lon.toFixed(6)}
        `);
      }

      window.__updateSelectedPointRef = updateSelectedPoint;
      bindAddressSearchModalEvents(apiKey, updateSelectedPoint);

      async function searchAddressToCoord() {
        const rawQuery = addressInput.value.trim();
        const query = normalizeAddressKeyword(rawQuery);

        if (addressInput && query && addressInput.value !== query) {
          addressInput.value = query;
        }

        if (!query) {
          setResultMessage("주소를 먼저 입력해주세요.");
          return;
        }

        setResultMessage("주소 목록을 찾는 중입니다...");

        try {
          await searchAddressList(query, 1, apiKey, updateSelectedPoint);
          if (!addressSearchState.results.length) {
            setResultMessage("주소를 찾지 못했습니다. 시/군/구와 건물번호까지 더 자세히 입력해주세요.");
            return;
          }
          setResultMessage("주소 검색 결과가 표시되었습니다. 목록에서 원하는 주소를 선택해주세요.");
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

      map.events.register("click", map, function (e) {
        const lonLat = map.getLonLatFromPixel(e.xy).transform(
          map.projection,
          map.displayProjection
        );

        updateSelectedPoint(lonLat.lon, lonLat.lat, "지도에서 최종 선택한 위치");
      });

      if (submitBtn) {
        submitBtn.addEventListener("click", async function () {
          if (isSubmitting) {
            await showModal({
              title: "이미 제출 처리 중입니다.",
              body: `
                <div style="line-height:1.9;color:#334155;">
                  현재 신청 내용을 저장하고 있습니다.<br>
                  잠시만 기다려주세요. 버튼을 다시 누르실 필요는 없습니다.
                </div>
              `,
              buttonText: "확인"
            });
            return;
          }

          const activeLock = getActiveSubmitLock();
          if (activeLock?.state === "pending") {
            setResultMessage(`
              <div style="padding:16px;border:1px solid #dbeafe;border-radius:12px;background:#f8fbff;color:#1e3a8a;line-height:1.8;">
                <b>현재 신청 내용을 저장하고 있습니다.</b><br>
                중복 제출 방지를 위해 잠시 동안 추가 클릭이 제한됩니다.
              </div>
            `);
            await showModal({
              title: "제출 처리 중입니다.",
              body: `
                <div style="line-height:1.9;color:#334155;">
                  현재 신청 내용을 저장하고 있습니다.<br>
                  중복 제출 방지를 위해 잠시 후 다시 확인해주세요.
                </div>
              `,
              buttonText: "확인"
            });
            return;
          }

          if (activeLock?.state === "success") {
            setResultMessage(`
              <div style="padding:16px;border:1px solid #ccead5;border-radius:12px;background:#f0fdf4;color:#166534;line-height:1.8;">
                <b>방금 신청이 정상 접수되었습니다.</b><br>
                중복 제출 방지를 위해 잠시 동안 재제출이 제한됩니다.
              </div>
            `);
            await showModal({
              title: "방금 신청이 정상 접수되었습니다.",
              body: `
                <div style="line-height:1.9;color:#334155;">
                  같은 내용이 여러 번 저장되지 않도록 잠시 동안 재제출이 제한됩니다.<br>
                  새로운 신청이 필요하면 잠시 후 다시 진행해주세요.
                </div>
              `,
              buttonText: "확인",
              tone: "success"
            });
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
          writeSubmitLock("pending");
          setSubmitState("pending");

          try {
            const ownerName = document.getElementById("ownerName")?.value.trim() || "";
            const phone = phoneInput?.value.trim() || "";
            const shopName = document.getElementById("shopName")?.value.trim() || "";
            const businessType = businessTypeSelect?.value || "";
            const businessTypeEtc = businessTypeEtcInput?.value.trim() || "";
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

            const officialAddressForSave = (selectedOfficialAddress || selectedAddressInput.value || "").trim();
            const sigunguForStation = (selectedSigungu || extractSigunguFromRefined({ text: officialAddressForSave, structure: {} }) || "").trim();

            const matchedStation = inferStationByAddress(
              officialAddressForSave,
              sigunguForStation
            );

            const payload = {
              applicant_name: ownerName,
              business_name: shopName,
              business_type: businessType || null,
              business_type_other: businessType === "기타" ? (businessTypeEtc || null) : null,
              phone: formatPhoneNumber(phone),
              email: null,
              address_road: officialAddressForSave,
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

            const businessTypeText =
              businessType === "기타" && businessTypeEtc
                ? `${businessType} (${businessTypeEtc})`
                : businessType;

            const fullAddress = detailAddress
              ? `${officialAddressForSave}, ${detailAddress}`
              : officialAddressForSave;

            setResultMessage(`
              <div style="padding:20px;border:1px solid #ccead5;border-radius:16px;background:#f0fdf4;">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                  <div style="width:36px;height:36px;border-radius:999px;background:#dcfce7;display:flex;align-items:center;justify-content:center;font-size:18px;">✓</div>
                  <div style="font-size:20px;font-weight:800;color:#166534;">신청이 정상적으로 접수되었습니다.</div>
                </div>

                <div style="font-size:14px;line-height:1.8;color:#475569;margin-bottom:14px;">
                  입력하신 신청 내용이 시스템에 정상 저장되었습니다.<br>
                  관할 경찰서 CPO가 접수 내용을 확인한 뒤 검토를 진행할 예정입니다.
                </div>

                <div style="border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;padding:6px 14px;margin-bottom:16px;">
                  ${createInfoRow("접수상태", "정상 저장 완료")}
                  ${createInfoRow("접수일시", formatDateTime(new Date()))}
                  ${createInfoRow("성명", ownerName)}
                  ${createInfoRow("연락처", formatPhoneNumber(phone))}
                  ${createInfoRow("점포명", shopName)}
                  ${createInfoRow("업종", businessTypeText)}
                  ${createInfoRow("주소", fullAddress)}
                  ${createInfoRow("관할 경찰서", matchedStation?.station_label || "(자동 판별 안됨)")}
                  ${createInfoRow("연매출 구간", salesRange)}
                  ${createInfoRow("연매출 기재", annualSalesValue || "(미입력)")}
                </div>

                <div style="padding:14px 16px;border-radius:12px;background:#eef4ff;border:1px solid #d7e5ff;color:#1f3b63;line-height:1.8;font-size:14px;">
                  <b>안내사항</b><br>
                  1. 신청 내용은 관할 경찰서로 전달됩니다.<br>
                  2. 필요 시 사업자등록증, 매출현황 증빙자료 등 추가 서류 제출을 요청할 수 있습니다.<br>
                  3. 필요 시 현장 확인 또는 연락이 진행될 수 있습니다.<br>
                  4. 최종 선정 결과는 개별 연락드릴 예정입니다.
                </div>
              </div>
            `);

            writeSubmitLock("success");
            setSubmitState("success-lock");
            clearSubmitCooldownTimer();
            submitCooldownTimer = setTimeout(() => {
              clearSubmitLock();
              setSubmitState("idle");
            }, SUBMIT_SUCCESS_COOLDOWN_MS);

            await showModal({
              title: "신청이 정상적으로 접수되었습니다.",
              body: `
                <div style="line-height:1.9;color:#334155;">
                  입력하신 신청 내용은 시스템에 정상 저장되었습니다.<br>
                  신청 내용은 관할 경찰서로 전달되며, 필요 시 추가 서류 제출을 요청할 수 있습니다.<br>
                  확인을 누르면 입력 화면이 초기화됩니다.
                </div>
              `,
              buttonText: "확인",
              tone: "success"
            });

            resetApplicationForm();

            if (resultBox) {
              resultBox.scrollIntoView({ behavior: "smooth", block: "center" });
            }
          } catch (error) {
            console.error(error);
            clearSubmitLock();
            setSubmitState("idle");

            setResultMessage(`
              <div style="padding:16px;border:1px solid #fecaca;border-radius:12px;background:#fff1f2;color:#991b1b;line-height:1.8;">
                <b>신청 저장 중 오류가 발생했습니다.</b><br>
                ${escapeHtml(error.message || "알 수 없는 오류")}
              </div>
            `);

            await showModal({
              title: "신청 저장 중 오류가 발생했습니다.",
              body: `
                <div style="line-height:1.9;color:#334155;">
                  신청 내용을 저장하는 중 오류가 발생했습니다.<br>
                  같은 내용이 중복 저장되지 않도록 자동으로 확인한 뒤 다시 시도해주세요.<br><br>
                  <div style="padding:12px 14px;border:1px solid #fecaca;border-radius:12px;background:#fff1f2;color:#991b1b;">
                    ${escapeHtml(error.message || "알 수 없는 오류")}
                  </div>
                </div>
              `,
              buttonText: "확인",
              tone: "error"
            });
          } finally {
            isSubmitting = false;
            applySubmitLockState();
          }
        });
      }
    } catch (error) {
      console.error(error);
      setResultMessage("오류: " + error.message);
    }
  }

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) {
      applySubmitLockState();
    }
  });

  window.addEventListener("pageshow", function () {
    applySubmitLockState();
  });

  initVworldMap();
});