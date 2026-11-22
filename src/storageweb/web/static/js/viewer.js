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
      wrap.checked = window.SW.store(KEY) === "1";
      var apply = function () { box.classList.toggle("is-wrapped", wrap.checked); };
      apply();
      wrap.addEventListener("change", function () {
        apply();
        window.SW.store(KEY, wrap.checked ? "1" : "0");
      });
    }
    var copy = document.getElementById("viewer-copy");
    if (copy) {
      copy.addEventListener("click", function () {
        var text = Array.prototype.map.call(box.children, function (li) { return li.textContent; }).join("\n");
        window.SW.copy(text).then(function (ok) { if (ok) copy.querySelector("span").textContent = t("Copied"); });
      });
    }
  }

  // ------------------------------------------------------------------ imágenes, PDF, vídeo y audio
  // Una imagen se ve entera en la ventana; pulsarla la pone a su tamaño real (y otra vez, de vuelta)
  var imageButton = document.getElementById("viewer-image");
  if (imageButton) {
    imageButton.addEventListener("click", function () {
      var zoomed = imageButton.classList.toggle("is-zoomed");
      imageButton.setAttribute("aria-pressed", zoomed ? "true" : "false");
    });
  }
  // Si el navegador no sabe abrirlo (un códec que no tiene, una imagen rota), el aviso con la descarga. El error
  // puede llegar antes que este script: se mira también cómo quedó
  var media = document.querySelector(".viewer-media img, .viewer-media video, .viewer-media audio");
  var mediaError = document.getElementById("viewer-media-error");
  if (media && mediaError) {
    var failed = function () {
      media.hidden = true;
      if (imageButton) imageButton.hidden = true;
      mediaError.hidden = false;
    };
    media.addEventListener("error", failed);
    if (media.tagName === "IMG" ? (media.complete && media.naturalWidth === 0) : media.error) failed();
  }

  // Un log grande se abre por el final: se baja hasta la última línea (después de ajustar las líneas)
  if (box && box.hasAttribute("data-scroll-end") && box.lastElementChild) {
    box.lastElementChild.scrollIntoView({ block: "end" });
  }

  // ------------------------------------------------------------------ colores del código (highlight.js)
  // Solo si la página lo cargó (preview.highlight). highlight.js escapa el texto y solo añade <span class="hljs-…">

  /** Parte el HTML coloreado en líneas, cerrando al final de cada una los <span> abiertos y abriéndolos en la
   * siguiente (un comentario o una cadena de varias líneas). */
  function splitLines(html) {
    var lines = [], open = [], line = "", last = 0, m;
    var re = /<span[^>]*>|<\/span>|\n/g;
    while ((m = re.exec(html))) {
      line += html.slice(last, m.index);
      last = re.lastIndex;
      if (m[0] === "\n") {
        lines.push(line + "</span>".repeat(open.length));
        line = open.join("");
      } else if (m[0] === "</span>") {
        open.pop();
        line += m[0];
      } else {
        open.push(m[0]);
        line += m[0];
      }
    }
    lines.push(line + html.slice(last));
    return lines;
  }

  function colorize(text, lang) {
    try {
      return window.hljs.highlight(text, { language: lang, ignoreIllegals: true }).value;
    } catch (e) {
      return null;   // un lenguaje raro o un fallo de la biblioteca: se queda sin colores
    }
  }

  var hljs = window.hljs;
  if (hljs && box && box.dataset.lang && hljs.getLanguage(box.dataset.lang)) {
    var items = box.children;
    var source = Array.prototype.map.call(items, function (li) { return li.textContent; }).join("\n");
    var colored = colorize(source, box.dataset.lang);
    var lines = colored === null ? [] : splitLines(colored);
    if (lines.length === items.length) {
      // Cada línea es una rejilla (número | texto): el texto coloreado va en un solo elemento
      for (var i = 0; i < items.length; i++) items[i].innerHTML = '<span class="code-text">' + lines[i] + "</span>";
      box.classList.add("hljs");
    }
  }
  if (hljs) {
    // Los bloques de código de un .md (```python…); los de Mermaid son diagramas y no se tocan
    document.querySelectorAll("article.md pre > code[class*='language-']").forEach(function (code) {
      if (code.closest(".md-diagram")) return;
      var lang = (code.className.match(/language-([\w+#.-]+)/) || [])[1];
      if (!lang || !hljs.getLanguage(lang)) return;
      var html = colorize(code.textContent, lang);
      if (html !== null) {
        code.innerHTML = html;
        code.classList.add("hljs");
      }
    });
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
