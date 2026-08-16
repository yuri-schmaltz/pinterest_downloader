document.getElementById('download-btn').addEventListener('click', () => {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs[0]?.id) {
      chrome.scripting.executeScript({
        target: { tabId: tabs[0].id },
        func: () => {
          const btn = document.getElementById('pinterest-pro-toolbar');
          if (btn) btn.click();
        }
      });
    }
  });
});
