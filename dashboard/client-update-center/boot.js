// Incremental enterprise-center entry. Other tabs keep their existing bundles.
(() => {
  if (window.top !== window) return;
  const identifier = "octop-joint-client-update-center";
  function mount() {
    if (location.pathname !== "/enterprise/admin") return;
    const panel = document.querySelector(
      '[role="tabpanel"][id$="-panel-client-updates"]',
    );
    if (!panel) return;
    let frame = document.getElementById(identifier);
    if (!frame) {
      frame = document.createElement("iframe");
      frame.id = identifier;
      frame.title = "Octop";
      frame.src = "/client-update-center/index.html?v=112601";
      frame.style.cssText =
        "display:block;width:100%;height:900px;border:0;background:transparent";
      panel.appendChild(frame);
    }
    for (const child of panel.children)
      if (child !== frame) child.style.display = "none";
  }
  window.addEventListener("message", (event) => {
    const frame = document.getElementById(identifier);
    if (
      event.origin !== location.origin ||
      !frame ||
      event.source !== frame.contentWindow ||
      event.data?.type !== "octop:client-update-center-size"
    )
      return;
    const height = Number(event.data.height);
    if (Number.isFinite(height) && height >= 200 && height <= 6000)
      frame.style.height = `${height + 8}px`;
  });
  const start = () => {
    new MutationObserver(mount).observe(document.body, {
      childList: true,
      subtree: true,
    });
    mount();
  };
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
