// Visor (view.html): texto (ajustar líneas, que se recuerda en este navegador, y copiar todo) y diagramas Mermaid
// de los .md, que se dibujan cada uno en un marco aislado (/diagram-frame, diagram-frame.js).
(function () {
  "use strict";
  var t = window.SW.t;

  // ------------------------------------------------------------------ texto
  var box = document.getElementById("viewer-text");
  if (box) {
    var KEY = "storageweb.viewer.wrap";
    var wrap = document.getElementById("viewer-wrap");
    if (wrap) {
      try { wrap.checked = window.localStorage.getItem(KEY) === "1"; } catch (e) { /* sin almacenamiento */ }
      var apply = function () { box.classList.toggle("is-wrapped", wrap.checked); };
      apply();
      wrap.addEventListener("change", function () {
        apply();
        try { window.localStorage.setItem(KEY, wrap.checked ? "1" : "0"); } catch (e) { /* sin almacenamiento */ }
      });
    }
    var copy = document.getElementById("viewer-copy");
    if (copy) {
      copy.addEventListener("click", function () {
        if (!navigator.clipboard) return;
        var text = Array.prototype.map.call(box.children, function (li) { return li.textContent; }).join("\n");
        navigator.clipboard.writeText(text).then(function () {
          copy.querySelector("span").textContent = t("Copied");
        });
      });
    }
  }

  // ------------------------------------------------------------------ diagramas
  var article = document.querySelector("article.md[data-diagram-frame]");
  if (!article) return;

  function dark() {
    var theme = document.documentElement.getAttribute("data-theme");
    if (theme === "dark") return true;
    if (theme === "light") return false;
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  var frames = [];
  var url = article.getAttribute("data-diagram-frame") + (dark() ? "?dark=1" : "");
  article.querySelectorAll(".md-diagram").forEach(function (holder) {
    var code = holder.querySelector("code");
    if (!code) return;
    var frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "allow-scripts");   // y la CSP del marco: origen opaco, sin la sesión
    frame.setAttribute("title", t("Diagram"));
    frame.setAttribute("referrerpolicy", "no-referrer");
    frame.className = "md-diagram-frame";
    frame.src = url;
    holder.appendChild(frame);
    frames.push({ holder: holder, frame: frame, code: code.textContent });
  });

  window.addEventListener("message", function (e) {
    var item = null;
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].frame.contentWindow === e.source) { item = frames[i]; break; }
    }
    var data = e.data || {};
    if (!item || data.sw !== "diagram") return;
    if (data.type === "ready") {
      item.frame.contentWindow.postMessage({ sw: "diagram", type: "render", code: item.code }, "*");
    } else if (data.type === "size" && typeof data.height === "number") {
      item.frame.style.height = Math.min(Math.max(Math.round(data.height), 40), 4000) + "px";
      item.holder.classList.add("is-drawn");
    } else if (data.type === "error") {
      item.frame.remove();
      var note = document.createElement("p");
      note.className = "md-diagram-error";
      note.textContent = t("This diagram could not be drawn: %(error)s", { error: String(data.message || "") });
      item.holder.insertBefore(note, item.holder.firstChild);
    }
  });
})();
