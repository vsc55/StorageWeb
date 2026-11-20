// Dentro del marco aislado (diagram_frame.html): dibuja con Mermaid el código que manda el visor (viewer.js) y le
// devuelve solo su altura. Origen opaco: no ve las cookies ni la página de la aplicación.
(function () {
  "use strict";
  var started = false;

  function tell(message) {
    message.sw = "diagram";
    window.parent.postMessage(message, "*");  // el padre comprueba que viene de este marco
  }

  function size() {
    tell({ type: "size", height: Math.ceil(document.documentElement.getBoundingClientRect().height) });
  }

  window.addEventListener("message", function (e) {
    if (e.source !== window.parent || started) return;
    var data = e.data || {};
    if (data.sw !== "diagram" || data.type !== "render" || typeof data.code !== "string") return;
    started = true;
    var out = document.getElementById("out");
    window.mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",                 // sin HTML en las etiquetas ni enlaces con JavaScript
      theme: document.body.dataset.dark === "1" ? "dark" : "default",
      fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
    });
    window.mermaid.render("diagram", data.code).then(function (result) {
      out.innerHTML = result.svg;              // SVG de Mermaid, ya saneado (y aquí no hay nada que robar)
      size();
      if (window.ResizeObserver) new ResizeObserver(size).observe(out);
    }).catch(function (err) {
      tell({ type: "error", message: String((err && err.message) || err).slice(0, 300) });
    });
  });

  document.addEventListener("DOMContentLoaded", function () { tell({ type: "ready" }); });
})();
