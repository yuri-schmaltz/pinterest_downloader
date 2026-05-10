/**
 * Popup UI Logic — Communicates with content script and service worker.
 */

(() => {
  "use strict";

  // ========== DOM References ==========
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const ui = {
    notPinterest: $("#not-pinterest"),
    privateWarning: $("#private-warning"),
    mainContent: $("#main-content"),
    pageDot: $("#page-status-dot"),
    pageText: $("#page-status-text"),
    statusText: $("#status-text"),

    btnDiscover: $("#btn-discover"),
    btnCollect: $("#btn-collect"),
    btnDownload: $("#btn-download"),
    btnCancel: $("#btn-cancel"),

    boardsSection: $("#boards-section"),
    boardsList: $("#boards-list"),
    boardsInfo: $("#boards-info"),
    selectAll: $("#select-all"),

    progressSection: $("#progress-section"),
    progressPhase: $("#progress-phase"),
    progressDetail: $("#progress-detail"),
    progressBar: $("#progress-bar"),
    progressCurrent: $("#progress-current"),
    progressTotal: $("#progress-total"),
    overallBar: $("#overall-bar"),
    overallCurrent: $("#overall-current"),
    overallTotal: $("#overall-total"),

    downloadControls: $("#download-controls"),

    logCount: $("#log-count"),
    logContent: $("#log-content"),

    optMaxPins: $("#opt-max-pins"),
    optScrollPause: $("#opt-scroll-pause"),
  };

  // ========== State ==========
  let currentTab = null;
  let pageInfo = null;
  let discoveredBoards = [];
  let selectedBoardUrls = new Set();
  let isWorking = false;
  let logEntries = 0;

  // ========== Init ==========
  async function init() {
    // Load saved options
    loadOptions();

    // Get current tab
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    currentTab = tabs[0];

    if (!currentTab || !currentTab.url || !currentTab.url.includes("pinterest.com")) {
      showNotPinterest();
      return;
    }

    // Inject content script if needed, then get page info
    try {
      await ensureContentScript();
      const info = await sendToTab("GET_PAGE_INFO");
      pageInfo = info;
      setupForPageType(info);
    } catch (err) {
      log(`Erro ao conectar: ${err.message}`, "error");
      showNotPinterest();
    }

    // Listen for messages from content script / service worker
    chrome.runtime.onMessage.addListener(handleMessage);

    // Bind events
    bindEvents();
  }

  /**
   * Ensure content script is injected in the current tab.
   */
  async function ensureContentScript() {
    try {
      await sendToTab("PING");
    } catch {
      // Inject manually
      await chrome.scripting.executeScript({
        target: { tabId: currentTab.id },
        files: ["lib/utils.js", "content/content.js"],
      });
      // Wait a bit for it to initialize
      await sleep(300);
    }
  }

  // ========== Page Type Detection ==========
  function setupForPageType(info) {
    const type = info.pageType;

    ui.mainContent.style.display = "block";
    ui.notPinterest.style.display = "none";
    ui.privateWarning.style.display = "none";

    ui.pageDot.className = "status-dot active";

    switch (type) {
      case "profile":
        ui.pageText.textContent = `Perfil: @${info.username}`;
        ui.btnDiscover.style.display = "flex";
        ui.btnCollect.style.display = "none";
        setStatus("Clique em 'Listar Quadros' para descobrir os boards.");
        break;

      case "board":
        ui.pageText.textContent = `Board: ${info.boardName}`;
        ui.btnDiscover.style.display = "none";
        ui.btnCollect.style.display = "flex";
        // Also allow collecting for a single board directly
        ui.downloadControls.style.display = "flex";
        ui.btnDownload.textContent = "⬇️ Baixar Este Board";
        ui.btnDownload.disabled = false;
        setStatus("Pronto para coletar pins deste board.");
        break;

      case "pin":
        ui.pageText.textContent = `Pin individual`;
        ui.pageDot.className = "status-dot warning";
        setStatus("Navegue para um perfil ou board para usar o downloader.");
        break;

      default:
        ui.pageText.textContent = `Página: ${type}`;
        ui.pageDot.className = "status-dot warning";
        setStatus("Navegue para um perfil ou board.");
        break;
    }
  }

  function showNotPinterest() {
    ui.notPinterest.style.display = "block";
    ui.mainContent.style.display = "none";
    ui.pageDot.className = "status-dot error";
    ui.pageText.textContent = "Fora do Pinterest";
    setStatus("Navegue para o Pinterest.");
  }

  // ========== Event Binding ==========
  function bindEvents() {
    ui.btnDiscover.addEventListener("click", discoverBoards);
    ui.btnCollect.addEventListener("click", collectCurrentBoard);
    ui.btnDownload.addEventListener("click", startDownload);
    ui.btnCancel.addEventListener("click", cancelOperation);
    ui.selectAll.addEventListener("change", toggleSelectAll);

    // Save options on change
    ui.optMaxPins.addEventListener("change", saveOptions);
    ui.optScrollPause.addEventListener("change", saveOptions);
  }

  // ========== Board Discovery ==========
  async function discoverBoards() {
    if (isWorking) return;
    setWorking(true);

    ui.btnDiscover.classList.add("loading");
    ui.btnDiscover.textContent = " Buscando…";
    ui.boardsList.innerHTML = "";
    ui.boardsSection.style.display = "block";
    ui.boardsInfo.textContent = "Buscando quadros…";
    ui.downloadControls.style.display = "none";

    log("Iniciando descoberta de boards…", "info");
    setStatus("Buscando quadros do perfil…");

    try {
      const result = await sendToTab("COLLECT_BOARDS");

      if (result.error === "private") {
        ui.privateWarning.style.display = "block";
        ui.boardsSection.style.display = "none";
        log("Perfil privado detectado.", "error");
        setStatus("Perfil privado — faça login no Pinterest.");
        return;
      }

      if (!result.boards || result.boards.length === 0) {
        ui.boardsInfo.textContent = "Nenhum quadro encontrado.";
        log("Nenhum quadro encontrado.", "error");
        setStatus("Nenhum quadro encontrado.");
        return;
      }

      discoveredBoards = result.boards;
      renderBoards(result.boards);
      ui.downloadControls.style.display = "flex";
      ui.btnDownload.innerHTML = '<span class="btn-icon">⬇️</span> Baixar Selecionados';
      log(`${result.boards.length} quadros encontrados.`, "success");
      setStatus(`${result.boards.length} quadros encontrados. Selecione e baixe.`);
    } catch (err) {
      log(`Erro: ${err.message}`, "error");
      setStatus("Erro ao buscar quadros.");
    } finally {
      ui.btnDiscover.classList.remove("loading");
      ui.btnDiscover.innerHTML = '<span class="btn-icon">📋</span> Listar Quadros';
      setWorking(false);
    }
  }

  // ========== Board Rendering ==========
  function renderBoards(boards) {
    ui.boardsList.innerHTML = "";
    selectedBoardUrls.clear();

    for (const board of boards) {
      const item = document.createElement("div");
      item.className = "board-item fade-in";
      item.dataset.url = board.url;

      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) {
          selectedBoardUrls.add(board.url);
          item.classList.add("selected");
        } else {
          selectedBoardUrls.delete(board.url);
          item.classList.remove("selected");
        }
        updateSelectionInfo();
      });

      let thumbEl;
      if (board.thumbnailUrl) {
        thumbEl = document.createElement("img");
        thumbEl.className = "board-thumb";
        thumbEl.src = board.thumbnailUrl;
        thumbEl.alt = board.title;
        thumbEl.loading = "lazy";
        thumbEl.onerror = () => {
          thumbEl.outerHTML = '<div class="board-thumb placeholder">📋</div>';
        };
      } else {
        thumbEl = document.createElement("div");
        thumbEl.className = "board-thumb placeholder";
        thumbEl.textContent = "📋";
      }

      const info = document.createElement("div");
      info.className = "board-info";

      const title = document.createElement("div");
      title.className = "board-title";
      title.textContent = board.title;
      title.title = board.title;

      const pins = document.createElement("div");
      pins.className = "board-pins";
      pins.textContent = board.pinCount
        ? `${board.pinCount} Pins`
        : "Pins";

      info.appendChild(title);
      info.appendChild(pins);

      item.appendChild(checkbox);
      item.appendChild(thumbEl);
      item.appendChild(info);

      // Click on item toggles checkbox
      item.addEventListener("click", (e) => {
        if (e.target === checkbox) return;
        checkbox.checked = !checkbox.checked;
        checkbox.dispatchEvent(new Event("change"));
      });

      ui.boardsList.appendChild(item);
    }

    ui.boardsInfo.textContent = `${boards.length} quadros encontrados.`;
    updateSelectionInfo();
  }

  function updateSelectionInfo() {
    const count = selectedBoardUrls.size;
    const total = discoveredBoards.length;
    ui.boardsInfo.textContent = count > 0
      ? `${count} de ${total} selecionados`
      : `${total} quadros encontrados.`;
    ui.btnDownload.disabled = count === 0;

    // Update select all state
    ui.selectAll.checked = count === total && total > 0;
    ui.selectAll.indeterminate = count > 0 && count < total;
  }

  function toggleSelectAll() {
    const checked = ui.selectAll.checked;
    const items = ui.boardsList.querySelectorAll('.board-item');
    items.forEach(item => {
      const cb = item.querySelector('input[type="checkbox"]');
      if (cb.checked !== checked) {
        cb.checked = checked;
        cb.dispatchEvent(new Event("change"));
      }
    });
  }

  // ========== Download Flow ==========
  async function startDownload() {
    if (isWorking) return;

    // Determine what to download
    let boardsToProcess = [];

    if (pageInfo.pageType === "board") {
      // Single board mode
      boardsToProcess = [{
        url: pageInfo.url || currentTab.url,
        title: pageInfo.boardName,
      }];
    } else {
      // Multi-board mode
      boardsToProcess = discoveredBoards.filter(b => selectedBoardUrls.has(b.url));
    }

    if (boardsToProcess.length === 0) {
      setStatus("Selecione ao menos um quadro.");
      return;
    }

    setWorking(true);
    ui.btnCancel.disabled = false;
    ui.progressSection.style.display = "block";
    ui.overallTotal.textContent = String(boardsToProcess.length);

    log(`Iniciando download de ${boardsToProcess.length} board(s)…`, "info");
    setStatus("Processando boards…");

    let totalDownloaded = 0;
    let totalPins = 0;

    for (let i = 0; i < boardsToProcess.length; i++) {
      const board = boardsToProcess[i];
      ui.overallCurrent.textContent = String(i);
      updateOverallBar(i, boardsToProcess.length);
      ui.progressPhase.textContent = `Board: ${board.title || board.url}`;

      log(`[${i + 1}/${boardsToProcess.length}] Processando: ${board.title}`, "info");

      try {
        // Navigate to board page if needed
        if (pageInfo.pageType !== "board" || currentTab.url !== board.url) {
          setStatus(`Navegando para ${board.title}…`);
          await chrome.tabs.update(currentTab.id, { url: board.url });
          await waitForTabLoad(currentTab.id);
          await sleep(2000);
          await ensureContentScript();
        }

        // Step 1: Collect pins
        ui.progressDetail.textContent = "Coletando pins…";
        updateProgressBar(0, 1);
        log(`  Coletando pins de ${board.title}…`);

        const collectResult = await sendToTab("COLLECT_PINS", {
          options: {
            maxPins: getMaxPins(),
            scrollPause: getScrollPause(),
          },
        });

        const pinUrls = collectResult.pins || [];
        log(`  ${pinUrls.length} pins encontrados.`, "success");

        if (pinUrls.length === 0) {
          log(`  Nenhum pin encontrado. Pulando.`, "error");
          continue;
        }

        // Step 2: Resolve images
        ui.progressDetail.textContent = "Resolvendo imagens…";
        log(`  Resolvendo ${pinUrls.length} imagens…`);

        const resolved = await sendToTab("RESOLVE_PINS", {
          pins: pinUrls,
          intercepted: collectResult.intercepted || {},
        });

        const imageCount = Object.keys(resolved).length;
        log(`  ${imageCount}/${pinUrls.length} imagens resolvidas.`,
          imageCount > 0 ? "success" : "error"
        );

        if (imageCount === 0) {
          log(`  Nenhuma imagem resolvida. Pulando.`, "error");
          continue;
        }

        // Step 3: Start downloads via service worker
        ui.progressDetail.textContent = "Baixando…";
        log(`  Enviando ${imageCount} imagens para download…`);

        const dlResult = await chrome.runtime.sendMessage({
          type: "START_DOWNLOADS",
          boardUrl: board.url,
          images: resolved,
        });

        log(`  Downloads enfileirados: ${dlResult.total} → ${dlResult.folder}`, "info");

        // Wait for downloads to complete
        await waitForDownloadsComplete(dlResult.total);

        totalDownloaded += dlResult.total;
        totalPins += pinUrls.length;

      } catch (err) {
        log(`  Erro no board ${board.title}: ${err.message}`, "error");
      }

      ui.overallCurrent.textContent = String(i + 1);
      updateOverallBar(i + 1, boardsToProcess.length);
    }

    // Done
    ui.progressPhase.textContent = "Concluído!";
    ui.progressDetail.textContent = "";
    updateProgressBar(1, 1);
    updateOverallBar(boardsToProcess.length, boardsToProcess.length);

    log(`✅ Total: ${totalDownloaded} imagens baixadas de ${boardsToProcess.length} board(s).`, "success");
    setStatus(`Concluído: ${totalDownloaded} imagens de ${boardsToProcess.length} boards.`);

    setWorking(false);
    ui.btnCancel.disabled = true;
  }

  async function collectCurrentBoard() {
    if (isWorking) return;
    // Treat as single board download
    pageInfo.url = currentTab.url;
    await startDownload();
  }

  async function cancelOperation() {
    try {
      await sendToTab("CANCEL");
      await chrome.runtime.sendMessage({ type: "CANCEL_DOWNLOADS" });
    } catch { /* ignore */ }
    log("Operação cancelada.", "error");
    setStatus("Cancelado.");
    setWorking(false);
    ui.btnCancel.disabled = true;
  }

  // ========== Download Monitoring ==========
  async function waitForDownloadsComplete(expectedTotal) {
    let lastCompleted = 0;
    const maxWait = 300; // 5 min max
    for (let i = 0; i < maxWait; i++) {
      await sleep(1000);

      try {
        const status = await chrome.runtime.sendMessage({ type: "GET_DOWNLOAD_STATUS" });
        if (status.cancelled) break;

        const completed = status.completed + status.failed;
        updateProgressBar(completed, status.total);
        ui.progressCurrent.textContent = String(completed);
        ui.progressTotal.textContent = String(status.total);

        if (completed !== lastCompleted) {
          ui.progressDetail.textContent = `${status.completed} ok, ${status.failed} falhas, ${status.active} ativos`;
          lastCompleted = completed;
        }

        if (completed >= status.total) {
          log(`  Download completo: ${status.completed} ok, ${status.failed} falhas.`,
            status.failed > 0 ? "error" : "success"
          );
          break;
        }
      } catch {
        break;
      }
    }
  }

  // ========== Message Handling ==========
  function handleMessage(msg) {
    switch (msg.type) {
      case "PIN_COLLECT_PROGRESS":
        ui.progressDetail.textContent = `${msg.count} pins coletados…`;
        break;

      case "RESOLVE_PROGRESS":
        updateProgressBar(msg.resolved, msg.total);
        ui.progressDetail.textContent = `${msg.resolved}/${msg.total} resolvidos`;
        break;

      case "DOWNLOAD_PROGRESS":
        updateProgressBar(msg.completed + msg.failed, msg.total);
        break;

      case "DOWNLOAD_COMPLETE":
        log(`Download completo: ${msg.completed}/${msg.total}`, "success");
        break;
    }
  }

  // ========== Communication Helpers ==========
  function sendToTab(type, extra = {}) {
    return new Promise((resolve, reject) => {
      chrome.tabs.sendMessage(
        currentTab.id,
        { type, ...extra },
        (response) => {
          if (chrome.runtime.lastError) {
            reject(new Error(chrome.runtime.lastError.message));
          } else {
            resolve(response);
          }
        }
      );
    });
  }

  function waitForTabLoad(tabId) {
    return new Promise((resolve) => {
      function onUpdated(id, info) {
        if (id === tabId && info.status === "complete") {
          chrome.tabs.onUpdated.removeListener(onUpdated);
          resolve();
        }
      }
      chrome.tabs.onUpdated.addListener(onUpdated);

      // Safety timeout
      setTimeout(() => {
        chrome.tabs.onUpdated.removeListener(onUpdated);
        resolve();
      }, 30000);
    });
  }

  // ========== UI Helpers ==========
  function setStatus(text) {
    ui.statusText.textContent = text;
  }

  function setWorking(working) {
    isWorking = working;
    ui.btnDiscover.disabled = working;
    ui.btnDownload.disabled = working && selectedBoardUrls.size === 0;
  }

  function updateProgressBar(current, total) {
    const pct = total > 0 ? Math.min((current / total) * 100, 100) : 0;
    ui.progressBar.style.width = `${pct}%`;
    ui.progressCurrent.textContent = String(current);
    ui.progressTotal.textContent = String(total);
  }

  function updateOverallBar(current, total) {
    const pct = total > 0 ? Math.min((current / total) * 100, 100) : 0;
    ui.overallBar.style.width = `${pct}%`;
    ui.overallCurrent.textContent = String(current);
    ui.overallTotal.textContent = String(total);
  }

  function log(message, type = "") {
    const entry = document.createElement("div");
    entry.className = `log-entry ${type}`;
    entry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    ui.logContent.appendChild(entry);
    ui.logContent.scrollTop = ui.logContent.scrollHeight;
    logEntries++;
    ui.logCount.textContent = String(logEntries);
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  // ========== Options Persistence ==========
  function getMaxPins() {
    const val = parseInt(ui.optMaxPins.value, 10);
    return val > 0 ? val : null;
  }

  function getScrollPause() {
    return parseFloat(ui.optScrollPause.value) || 1.2;
  }

  function saveOptions() {
    chrome.storage.sync.set({
      pbdMaxPins: parseInt(ui.optMaxPins.value, 10) || 0,
      pbdScrollPause: parseFloat(ui.optScrollPause.value) || 1.2,
    });
  }

  function loadOptions() {
    chrome.storage.sync.get(["pbdMaxPins", "pbdScrollPause"], (data) => {
      if (data.pbdMaxPins !== undefined) ui.optMaxPins.value = data.pbdMaxPins;
      if (data.pbdScrollPause !== undefined) ui.optScrollPause.value = data.pbdScrollPause;
    });
  }

  // ========== Start ==========
  init();
})();
