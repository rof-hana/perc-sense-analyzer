(() => {
  "use strict";

  const state = {
    analysis: null,
    selectedKey: null,
    activeSkPill: "",
    filterText: "",
    senseKeysCatalog: [],
  };

  // Elements
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabPanels = document.querySelectorAll(".tab-panel");

  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const btnSelectFile = document.getElementById("btn-select-file");
  const btnLoadSample = document.getElementById("btn-load-sample");
  const uploadStatus = document.getElementById("upload-status");

  const extractedInfo = document.getElementById("extracted-info");
  const metaFilename = document.getElementById("meta-filename");
  const metaTotal = document.getElementById("meta-total");
  const metaUnique = document.getElementById("meta-unique");
  const extractedFiles = document.getElementById("extracted-files");

  const analyzerWorkspace = document.getElementById("analyzer-workspace");
  const detectedFilter = document.getElementById("detected-filter");
  const skFilterPills = document.getElementById("sk-filter-pills");
  const detectedList = document.getElementById("detected-list");
  const detectedDetail = document.getElementById("detected-detail");

  // Reference Tab Elements
  const refQuery = document.getElementById("ref-query");
  const refSkSelect = document.getElementById("ref-sk-select");
  const btnRefSearch = document.getElementById("btn-ref-search");
  const refCount = document.getElementById("ref-count");
  const refSkList = document.getElementById("ref-sk-list");
  const refAscList = document.getElementById("ref-asc-list");
  const refDetail = document.getElementById("ref-detail");

  function esc(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function showStatus(msg, isError = false) {
    uploadStatus.textContent = msg;
    uploadStatus.classList.remove("hidden", "error");
    if (isError) uploadStatus.classList.add("error");
  }

  function hideStatus() {
    uploadStatus.classList.add("hidden");
  }

  // Tab switching
  tabBtns.forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.tab;
      tabBtns.forEach((b) => b.classList.toggle("active", b === btn));
      tabPanels.forEach((p) => p.classList.toggle("active", p.id === `tab-${target}`));
    });
  });

  // Upload handlers
  btnSelectFile.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.click();
  });

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      fileInput.click();
    }
  });

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("dragover");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragover");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      uploadFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      uploadFile(fileInput.files[0]);
    }
  });

  btnLoadSample.addEventListener("click", async (e) => {
    e.stopPropagation();
    showStatus("サンプルTSRログを読み込み中...");
    try {
      const res = await fetch("/api/sample");
      const data = await res.json();
      if (!res.ok) {
        showStatus(data.error || "サンプル読み込みに失敗しました。", true);
        return;
      }
      hideStatus();
      renderAnalysis(data);
    } catch (err) {
      showStatus("通信エラーが発生しました: " + err.message, true);
    }
  });

  async function uploadFile(file) {
    showStatus(`"${file.name}" をアップロード・展開解析中...`);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (!res.ok) {
        showStatus(data.error || "解析エラーが発生しました。", true);
        return;
      }
      hideStatus();
      renderAnalysis(data);
    } catch (err) {
      showStatus("アップロード中にエラーが発生しました: " + err.message, true);
    }
  }

  function renderAnalysis(data) {
    state.analysis = data;
    state.selectedKey = null;
    state.activeSkPill = "";
    state.filterText = "";
    detectedFilter.value = "";

    extractedInfo.classList.remove("hidden");
    analyzerWorkspace.classList.remove("hidden");

    metaFilename.textContent = data.filename || "-";
    metaTotal.textContent = `${data.total_occurrences} 件`;
    metaUnique.textContent = `${data.unique_sense_codes} 種`;

    extractedFiles.innerHTML = (data.extracted_logs || [])
      .map(
        (f) =>
          `<span class="file-chip">${esc(f.path)} (${f.lines.toLocaleString()} lines)</span>`
      )
      .join("");

    renderSkPills(data.summary || []);
    renderDetectedList();

    if (data.summary && data.summary.length > 0) {
      selectDetectedItem(data.summary[0].key);
    } else {
      detectedDetail.innerHTML =
        '<div class="empty-detail">ストレージログ内に Sense Key の記述は検出されませんでした。</div>';
    }
  }

  function renderSkPills(summary) {
    const countsBySk = {};
    summary.forEach((item) => {
      countsBySk[item.sk] = (countsBySk[item.sk] || 0) + item.count;
    });
    const total = summary.reduce((acc, x) => acc + x.count, 0);

    let html = `<button class="pill ${state.activeSkPill === "" ? "active" : ""}" data-sk="">ALL (${total})</button>`;
    Object.keys(countsBySk)
      .sort((a, b) => parseInt(a, 16) - parseInt(b, 16))
      .forEach((sk) => {
        const sample = summary.find((s) => s.sk === sk);
        const label = sample ? `${sample.sk_code} ${sample.sk_name}` : `${sk}h`;
        html += `<button class="pill ${state.activeSkPill === sk ? "active" : ""}" data-sk="${esc(sk)}">${esc(label)} (${countsBySk[sk]})</button>`;
      });

    skFilterPills.innerHTML = html;
    skFilterPills.querySelectorAll(".pill").forEach((pill) => {
      pill.addEventListener("click", () => {
        state.activeSkPill = pill.dataset.sk;
        renderSkPills(state.analysis.summary || []);
        renderDetectedList();
      });
    });
  }

  detectedFilter.addEventListener("input", () => {
    state.filterText = detectedFilter.value.trim().toLowerCase();
    renderDetectedList();
  });

  function getFilteredSummary() {
    if (!state.analysis || !state.analysis.summary) return [];
    return state.analysis.summary.filter((item) => {
      if (state.activeSkPill && item.sk !== state.activeSkPill) return false;
      if (!state.filterText) return true;
      const hay = [
        item.key,
        item.sk_code,
        item.sk_name,
        item.sk_ja_name,
        item.asc_code,
        item.asc_description,
        ...(item.devices || []),
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(state.filterText);
    });
  }

  function renderDetectedList() {
    const items = getFilteredSummary();
    if (items.length === 0) {
      detectedList.innerHTML =
        '<div class="empty-detail">条件に一致する Sense Key はありません。</div>';
      return;
    }

    detectedList.innerHTML = items
      .map(
        (item) => `
      <div class="sense-item ${state.selectedKey === item.key ? "active" : ""}" data-key="${esc(item.key)}">
        <div class="sense-item-top">
          <span class="sense-code">SK: ${esc(item.sk_code)} / ASC: ${esc(item.asc_code)}</span>
          <span class="count-badge">${item.count} 件</span>
        </div>
        <div class="sense-item-title">${esc(item.sk_name)} — ${esc(item.sk_ja_name)}</div>
        <div class="sense-item-sub">${esc(item.asc_description)}</div>
      </div>`
      )
      .join("");

    detectedList.querySelectorAll(".sense-item").forEach((el) => {
      el.addEventListener("click", () => selectDetectedItem(el.dataset.key));
    });
  }

  function selectDetectedItem(key) {
    state.selectedKey = key;
    renderDetectedList();

    const item = (state.analysis.summary || []).find((s) => s.key === key);
    if (!item) return;

    const idSet = new Set(item.occurrence_ids || []);
    const occs = (state.analysis.occurrences || []).filter((o) => idSet.has(o.id));

    const devicesHtml =
      item.devices && item.devices.length
        ? item.devices.map((d) => `<span class="tag">${esc(d)}</span>`).join("")
        : '<span class="muted">デバイス識別子なし</span>';

    const devTypesHtml =
      item.asc_device_types && item.asc_device_types.length
        ? item.asc_device_types.map((dt) => `<span class="tag">${esc(dt)}</span>`).join("")
        : '<span class="muted">-</span>';

    const occsHtml = occs
      .map((o) => {
        const ctxHtml = (o.context || [])
          .map(
            (c) =>
              `<span class="log-line ${c.is_match ? "match" : ""}"><span class="log-lineno">${c.line_no}:</span>${esc(c.text)}</span>`
          )
          .join("");
        return `
        <div class="occurrence-card">
          <div class="occurrence-meta">
            <span>FILE: ${esc(o.file)}</span>
            <span>LINE: ${o.line_no}</span>
            ${o.timestamp ? `<span>TIME: ${esc(o.timestamp)}</span>` : ""}
            ${o.device ? `<span>DEV: ${esc(o.device)}</span>` : ""}
            ${o.cdb ? `<span>CDB: ${esc(o.cdb)}</span>` : ""}
          </div>
          <pre class="log-context">${ctxHtml}</pre>
        </div>`;
      })
      .join("");

    detectedDetail.innerHTML = `
      <div class="detail-header">
        <div class="detail-code-row">
          <span class="detail-badge">SK ${esc(item.sk_code)} (0x${esc(item.sk_hex)})</span>
          <span class="detail-badge">ASC/ASCQ ${esc(item.asc_code)}</span>
          <span class="mono muted">${item.count} 件検出</span>
        </div>
        <h2 class="detail-title">${esc(item.sk_name)} — ${esc(item.asc_description)}</h2>
        <div class="detail-subtitle">${esc(item.sk_ja_name)}</div>
      </div>

      <div class="detail-section">
        <h3>T10.org Sense Key 仕様</h3>
        <table class="kv-table">
          <tr><th>Sense Key</th><td class="mono">${esc(item.sk_code)} (0x${esc(item.sk_hex)}) — ${esc(item.sk_name)}</td></tr>
          <tr><th>日本語概要</th><td>${esc(item.sk_ja_description)}</td></tr>
          <tr><th>T10 英語定義</th><td>${esc(item.sk_description)}</td></tr>
        </table>
      </div>

      <div class="detail-section">
        <h3>T10.org ASC / ASCQ 仕様</h3>
        <table class="kv-table">
          <tr><th>ASC / ASCQ</th><td class="mono">${esc(item.asc_code)}</td></tr>
          <tr><th>Description</th><td><strong>${esc(item.asc_description)}</strong></td></tr>
          <tr><th>対象デバイス種別</th><td><div class="tag-list">${devTypesHtml}</div></td></tr>
        </table>
      </div>

      <div class="detail-section">
        <h3>ログ内で検出されたデバイス / パス (${(item.devices || []).length})</h3>
        <div class="tag-list">${devicesHtml}</div>
      </div>

      <div class="detail-section">
        <h3>ログ検出箇所 (${occs.length} 件)</h3>
        ${occsHtml}
      </div>
    `;
  }

  // ========================
  // T10.org Reference Search
  // ========================
  async function initReference() {
    try {
      const res = await fetch("/api/t10/sense-keys");
      const data = await res.json();
      state.senseKeysCatalog = data.sense_keys || [];
      state.senseKeysCatalog.forEach((sk) => {
        const opt = document.createElement("option");
        opt.value = sk.code.replace("h", "");
        opt.textContent = `${sk.code}: ${sk.name} (${sk.ja_name})`;
        refSkSelect.appendChild(opt);
      });
      runRefSearch();
    } catch (err) {
      console.error(err);
    }
  }

  async function runRefSearch() {
    const q = refQuery.value.trim();
    const sk = refSkSelect.value;
    const params = new URLSearchParams({ q, sk, limit: "250" });
    try {
      const res = await fetch(`/api/t10/search?${params.toString()}`);
      const data = await res.json();
      renderRefResults(data);
    } catch (err) {
      console.error(err);
    }
  }

  btnRefSearch.addEventListener("click", runRefSearch);
  refSkSelect.addEventListener("change", runRefSearch);
  refQuery.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runRefSearch();
  });

  function renderRefResults(data) {
    const sks = data.sense_keys || [];
    const ascs = data.asc_entries || [];
    refCount.textContent = `SK: ${sks.length} / ASC: ${ascs.length} (全 ${data.total_asc_loaded || 0} 件中)`;

    refSkList.innerHTML = sks
      .map(
        (sk) => `
      <div class="ref-sk-row" data-sk="${esc(sk.code.replace("h", ""))}">
        <span class="mono"><strong>${esc(sk.code)}</strong> ${esc(sk.name)}</span>
        <span class="muted">${esc(sk.ja_name)}</span>
      </div>`
      )
      .join("");

    refSkList.querySelectorAll(".ref-sk-row").forEach((row) => {
      row.addEventListener("click", () => {
        refSkList.querySelectorAll(".ref-sk-row").forEach((r) => r.classList.remove("active"));
        refAscList.querySelectorAll(".sense-item").forEach((r) => r.classList.remove("active"));
        row.classList.add("active");
        loadRefDetail(row.dataset.sk, null, null);
      });
    });

    refAscList.innerHTML = ascs
      .map(
        (a) => `
      <div class="sense-item" data-asc="${esc(a.asc)}" data-ascq="${esc(a.ascq)}">
        <div class="sense-item-top">
          <span class="sense-code">${esc(a.code)}</span>
          <span class="mono muted">${esc(a.device_flags)}</span>
        </div>
        <div class="sense-item-title">${esc(a.description)}</div>
      </div>`
      )
      .join("");

    refAscList.querySelectorAll(".sense-item").forEach((el) => {
      el.addEventListener("click", () => {
        refSkList.querySelectorAll(".ref-sk-row").forEach((r) => r.classList.remove("active"));
        refAscList.querySelectorAll(".sense-item").forEach((r) => r.classList.remove("active"));
        el.classList.add("active");
        const activeSk = refSkSelect.value || "0";
        loadRefDetail(activeSk, el.dataset.asc, el.dataset.ascq);
      });
    });
  }

  async function loadRefDetail(sk, asc, ascq) {
    const params = new URLSearchParams({ sk });
    if (asc) params.set("asc", asc);
    if (ascq) params.set("ascq", ascq);
    try {
      const res = await fetch(`/api/t10/detail?${params.toString()}`);
      const data = await res.json();
      const s = data.sense_key;
      const a = data.asc_ascq;

      let ascSection = "";
      if (a) {
        const dtHtml =
          a.device_types && a.device_types.length
            ? a.device_types.map((dt) => `<span class="tag">${esc(dt)}</span>`).join("")
            : '<span class="muted">-</span>';
        ascSection = `
          <div class="detail-section">
            <h3>T10.org ASC / ASCQ 仕様</h3>
            <table class="kv-table">
              <tr><th>ASC / ASCQ</th><td class="mono">${esc(a.code)}</td></tr>
              <tr><th>Description</th><td><strong>${esc(a.description)}</strong></td></tr>
              <tr><th>対象デバイス種別</th><td><div class="tag-list">${dtHtml}</div></td></tr>
            </table>
          </div>`;
      }

      refDetail.innerHTML = `
        <div class="detail-header">
          <div class="detail-code-row">
            <span class="detail-badge">SK ${esc(s.code)} (0x${esc(s.hex)})</span>
            ${a ? `<span class="detail-badge">ASC/ASCQ ${esc(a.code)}</span>` : ""}
          </div>
          <h2 class="detail-title">${a ? esc(a.description) : esc(s.name)}</h2>
          <div class="detail-subtitle">${esc(s.name)} — ${esc(s.ja_name)}</div>
        </div>
        ${ascSection}
        <div class="detail-section">
          <h3>T10.org Sense Key 仕様</h3>
          <table class="kv-table">
            <tr><th>Sense Key</th><td class="mono">${esc(s.code)} (0x${esc(s.hex)}) — ${esc(s.name)}</td></tr>
            <tr><th>日本語概要</th><td>${esc(s.ja_description)}</td></tr>
            <tr><th>T10 英語定義</th><td>${esc(s.description)}</td></tr>
          </table>
        </div>
      `;
    } catch (err) {
      console.error(err);
    }
  }

  initReference();
})();
