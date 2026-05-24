/** 浏览器页与 Gateway API/WS 的地址（Web 与 Gateway 分进程时使用 VVC_GATEWAY） */
(function () {
  function gatewayOrigin() {
    const raw = window.VVC_GATEWAY;
    if (raw) return String(raw).replace(/\/$/, "");
    return window.location.origin;
  }

  function gatewayWsUrl() {
    const base = gatewayOrigin();
    const u = new URL("/ws", base.endsWith("/") ? base : `${base}/`);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    return u.toString();
  }

  window.vvcGatewayOrigin = gatewayOrigin;
  window.vvcGatewayWsUrl = gatewayWsUrl;
})();
