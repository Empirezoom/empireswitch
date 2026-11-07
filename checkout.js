/**
 * EmpireSwitch Drop-in Checkout SDK v2.0
 * Embeddable high-availability multi-gateway checkout widget.
 */
(function (window) {
  window.EmpireSwitch = {
    open: function (options) {
      if (!options.amount || !options.email) {
        console.error(
          "[EmpireSwitch] 'amount' and 'email' are required options.",
        );
        return;
      }

      const overlay = document.createElement("div");
      overlay.id = "empireswitch-modal-overlay";
      overlay.style.cssText =
        "position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.85);z-index:999999;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(6px);animation:fadeIn 0.2s ease;";

      const container = document.createElement("div");
      container.style.cssText =
        "position:relative;width:100%;max-width:480px;height:680px;margin:16px;";

      const closeBtn = document.createElement("button");
      closeBtn.innerHTML = "&times;";
      closeBtn.style.cssText =
        "position:absolute;top:-14px;right:-14px;background:#ef4444;color:white;border:none;border-radius:50%;width:32px;height:32px;font-size:20px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 6px rgba(0,0,0,0.3);z-index:1000000;";
      closeBtn.onclick = function () {
        document.body.removeChild(overlay);
        if (options.onClose) options.onClose();
      };

      const iframe = document.createElement("iframe");
      const baseUrl = window.location.origin;
      const ref =
        options.ref || `EMP-SW-${Date.now().toString(16).toUpperCase()}`;
      iframe.src = `${baseUrl}/checkout.html?amount=${options.amount}&email=${encodeURIComponent(options.email)}&ref=${ref}`;
      iframe.style.cssText =
        "width:100%;height:100%;border:none;border-radius:16px;box-shadow:0 25px 50px -12px rgba(0,0,0,0.8);";

      container.appendChild(closeBtn);
      container.appendChild(iframe);
      overlay.appendChild(container);
      document.body.appendChild(overlay);

      // Listen for postMessage from checkout modal
      window.addEventListener("message", function handler(e) {
        if (e.data && e.data.event === "empireswitch_success") {
          if (options.onSuccess) options.onSuccess(e.data.reference);
          setTimeout(() => {
            if (document.body.contains(overlay)) {
              document.body.removeChild(overlay);
            }
          }, 2000);
        }
      });
    },
  };
})(window);
