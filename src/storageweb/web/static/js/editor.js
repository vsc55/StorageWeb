// Editor de texto (edit.html): Ctrl+S guarda; Tab sangra (Esc y luego Tab sale del cuadro); barra de herramientas
// (Markdown: formato; código: comentar con Ctrl+/ e indentar); colores con highlight.js; avisa
// al salir con cambios sin guardar.
(function () {
  "use strict";
  var form = document.getElementById("editor-form");
  var box = document.getElementById("editor-text");
  if (!form || !box) return;
  var state = document.getElementById("editor-state");
  var original = box.value;
  var eolInput = document.getElementById("editor-eol-value");   // LF / CRLF con los que se guarda (barra de estado)
  var originalEol = eolInput ? eolInput.value : "";
  var dirty = box.hasAttribute("data-dirty");   // tras un conflicto, lo escrito aún no está guardado
  var saving = false;
  var escaped = false;

  // ------------------------------------------------------------------ colores (highlight.js, si la página lo cargó)
  // El código coloreado va debajo del cuadro, que tiene el texto transparente: hay que repintarlo al escribir y
  // moverlo a la vez que el cuadro
  var colors = document.getElementById("editor-colors");
  var wrap = box.closest(".editor-wrap");
  var lang = box.getAttribute("data-lang");
  var hljs = window.hljs;
  var canColor = Boolean(colors && wrap && lang && hljs && hljs.getLanguage(lang));
  var paintTimer = null;

  // ------------------------------------------------------------------ números de línea
  // Una columna aparte a la izquierda: se mueve en vertical con el texto y marca la línea del cursor
  var gutter = document.getElementById("editor-gutter");
  var numbers = document.getElementById("editor-lines");
  var current = document.getElementById("editor-current");
  var lineCount = 0;

  function countLines(text) {
    var n = 1;
    for (var i = text.indexOf("\n"); i !== -1; i = text.indexOf("\n", i + 1)) n++;
    return n;
  }

  function showLines() {
    if (!numbers) return;
    var n = countLines(box.value);
    if (n === lineCount) return;
    var parts = new Array(n);
    for (var i = 0; i < n; i++) parts[i] = i + 1;
    numbers.textContent = parts.join("\n");
    lineCount = n;
    // Ancho a medida de las cifras (como poco, dos)
    wrap.style.setProperty("--gutter", (Math.max(String(n).length, 2) + 2.4) + "ch");
  }

  function showCurrent() {
    if (!current) return;
    var style = window.getComputedStyle(box);
    var height = parseFloat(style.lineHeight) || 22;
    var top = parseFloat(style.paddingTop) || 0;
    var line = countLines(box.value.slice(0, box.selectionStart));
    current.style.height = height + "px";
    current.style.top = (top + (line - 1) * height) + "px";
  }

  // Se pueden quitar (botón de la barra de estado); la elección se recuerda en este navegador
  var NUMBERS_KEY = "storageweb.editor.numbers";
  var numbersButton = document.getElementById("editor-numbers");
  function setNumbers(on) {
    wrap.classList.toggle("no-numbers", !on);
    if (numbersButton) numbersButton.setAttribute("aria-pressed", on ? "true" : "false");
  }
  var numbersOn = true;
  numbersOn = window.SW.store(NUMBERS_KEY) !== "0";
  setNumbers(numbersOn);
  if (numbersButton) {
    numbersButton.addEventListener("click", function () {
      numbersOn = !numbersOn;
      setNumbers(numbersOn);
      window.SW.store(NUMBERS_KEY, numbersOn ? "1" : "0");
      sync();
      box.focus();
    });
  }

  function sync() {
    if (gutter) gutter.scrollTop = box.scrollTop;
    if (!canColor) return;
    colors.parentNode.scrollTop = box.scrollTop;
    colors.parentNode.scrollLeft = box.scrollLeft;
  }

  function paint() {
    paintTimer = null;
    if (!canColor) return;
    var html;
    try {
      html = hljs.highlight(box.value, { language: lang, ignoreIllegals: true }).value;
    } catch (e) {
      wrap.classList.remove("is-colored");   // sin colores: se ve el texto del cuadro
      canColor = false;
      return;
    }
    // Un salto de línea final no ocupa línea en un <pre>: se añade otro para que mida lo mismo que el cuadro
    colors.innerHTML = html + "\n ";
    wrap.classList.add("is-colored");
    sync();
  }

  function schedulePaint() {
    if (!canColor || paintTimer) return;
    // Archivos medianos: se espera a una pausa al escribir para no frenar cada tecla
    paintTimer = setTimeout(paint, box.value.length > 50000 ? 250 : 30);
  }

  box.addEventListener("scroll", sync);
  paint();

  function mark() {
    dirty = box.value !== original || box.hasAttribute("data-dirty") || (eolInput && eolInput.value !== originalEol);
    if (state) state.hidden = !dirty;
    schedulePaint();
  }
  mark();
  box.addEventListener("input", function () {
    box.removeAttribute("data-dirty");
    showLines();
    mark();
  });
  showLines();

  // ------------------------------------------------------------------ herramientas (barra y atajos)
  var commentStart = box.getAttribute("data-comment") || "";
  var commentEnd = box.getAttribute("data-comment-end") || "";
  var markdown = box.hasAttribute("data-markdown");
  // La sangría del archivo: tabuladores si ya los usa; si no, espacios (los de la primera línea sangrada, si son 2
  // o 4; si no hay ninguna, 2 en YAML y JSON y 4 en lo demás). Se cambia en la barra de estado
  function detectUnit(text) {
    if (/^\t/m.test(text)) return "\t";
    var found = text.match(/^( +)\S/m);
    if (found && (found[1].length === 2 || found[1].length === 4)) return found[1];
    return lang === "yaml" || lang === "json" ? "  " : "    ";
  }
  var unit = detectUnit(box.value);

  /** Sustituye [start, end) por ``text`` como si se hubiera escrito (Ctrl+Z lo deshace) y selecciona
   * [selStart, selEnd). */
  function replace(start, end, text, selStart, selEnd) {
    box.focus();
    box.setSelectionRange(start, end);
    var done = false;
    try {
      done = text !== "" && document.execCommand("insertText", false, text);
    } catch (e) { done = false; }
    if (!done) {
      box.setRangeText(text, start, end, "end");
      box.dispatchEvent(new Event("input"));
    }
    box.setSelectionRange(selStart, selEnd);
  }

  /** Las líneas enteras que toca la selección: [inicio, fin) y su texto. */
  function selectedLines() {
    var value = box.value, start = box.selectionStart, end = box.selectionEnd;
    if (end > start && value.charAt(end - 1) === "\n") end--;   // la selección acaba al principio de otra línea
    var from = value.lastIndexOf("\n", start - 1) + 1;
    var to = value.indexOf("\n", end);
    if (to < 0) to = value.length;
    return { from: from, to: to, lines: value.slice(from, to).split("\n") };
  }

  function setLines(sel, lines) {
    var text = lines.join("\n");
    replace(sel.from, sel.to, text, sel.from, sel.from + text.length);
  }

  /** Pone o quita ``prefix`` al principio de cada línea (comentar, listas, citas, títulos). */
  function togglePrefix(prefix, keepIndent) {
    var sel = selectedLines();
    var used = sel.lines.filter(function (l) { return l.trim() !== ""; });
    if (!used.length) used = sel.lines;
    var indent = keepIndent ? Math.min.apply(null, used.map(function (l) { return l.match(/^\s*/)[0].length; })) : 0;
    var all = used.every(function (l) { return l.slice(indent).trimStart().indexOf(prefix.trim()) === 0; });
    setLines(sel, sel.lines.map(function (l, i) {
      if (l.trim() === "" && sel.lines.length > 1) return l;
      if (all) {
        var at = l.indexOf(prefix.trim());
        var cut = prefix.trim().length + (l.charAt(at + prefix.trim().length) === " " ? 1 : 0);
        return at < 0 ? l : l.slice(0, at) + l.slice(at + cut);
      }
      var number = /^1\. $/.test(prefix) ? (i + 1) + ". " : prefix;
      return l.slice(0, indent) + number + l.slice(indent);
    }));
  }

  function comment() {
    if (!commentStart) return;
    if (!commentEnd) { togglePrefix(commentStart + " ", true); return; }
    // Comentario de bloque (CSS, HTML): se envuelven las líneas, o se quita si ya lo están
    var sel = selectedLines();
    var text = sel.lines.join("\n");
    var trimmed = text.trim();
    if (trimmed.indexOf(commentStart) === 0 && trimmed.slice(-commentEnd.length) === commentEnd) {
      var inner = trimmed.slice(commentStart.length, trimmed.length - commentEnd.length).replace(/^ /, "").replace(/ $/, "");
      var lead = text.match(/^\s*/)[0];
      setLines(sel, [lead + inner]);
    } else {
      setLines(sel, [commentStart + " " + text + " " + commentEnd]);
    }
  }

  function indent(outdent) {
    var sel = selectedLines();
    setLines(sel, sel.lines.map(function (l) {
      if (!outdent) return l === "" ? l : unit + l;
      if (l.charAt(0) === "\t") return l.slice(1);
      return l.replace(new RegExp("^ {1," + Math.max(unit.length, 1) + "}"), "");
    }));
  }

  /** Markdown: envuelve la selección con ``mark`` (negrita, cursiva…) o se lo quita si ya lo tiene. */
  function wrapWith(marker, placeholder) {
    var value = box.value, start = box.selectionStart, end = box.selectionEnd;
    var n = marker.length;
    if (value.slice(start - n, start) === marker && value.slice(end, end + n) === marker) {
      replace(start - n, end + n, value.slice(start, end), start - n, end - n);
      return;
    }
    var text = value.slice(start, end) || placeholder;
    replace(start, end, marker + text + marker, start + n, start + n + text.length);
  }

  function link() {
    var start = box.selectionStart, end = box.selectionEnd;
    var text = box.value.slice(start, end) || t("text");
    var url = "https://";
    replace(start, end, "[" + text + "](" + url + ")", start + text.length + 3, start + text.length + 3 + url.length);
  }

  function codeBlock() {
    var sel = selectedLines();
    var text = sel.lines.join("\n");
    var fenced = "```\n" + text + "\n```";
    replace(sel.from, sel.to, fenced, sel.from + 3, sel.from + 3);
  }

  var t = window.SW && window.SW.t ? window.SW.t : function (s) { return s; };

  // ------------------------------------------------------------------ barra de estado
  var position = document.getElementById("editor-position");
  var indentButton = document.getElementById("editor-indent");
  var eolButton = document.getElementById("editor-eol");

  function showPosition() {
    if (!position) return;
    var value = box.value, start = box.selectionStart, end = box.selectionEnd;
    var line = value.slice(0, start).split("\n").length;
    var col = start - value.lastIndexOf("\n", start - 1);
    var text = t("Line %(line)s, column %(col)s", { line: line, col: col });
    if (end > start) {
      var lines = value.slice(start, end).split("\n").length;
      text += " · " + (lines > 1 ? t("%(num)s lines selected", { num: lines })
                                 : t("%(num)s characters selected", { num: end - start }));
    }
    position.textContent = text;
    showCurrent();
  }
  ["keyup", "click", "select", "input", "focus"].forEach(function (name) { box.addEventListener(name, showPosition); });
  document.addEventListener("selectionchange", function () { if (document.activeElement === box) showPosition(); });

  function showIndent() {
    if (indentButton) indentButton.textContent = unit === "\t" ? t("Tabs") : t("Spaces: %(num)s", { num: unit.length });
  }
  if (indentButton) {
    // 2 espacios → 4 espacios → tabuladores → 2 espacios…
    indentButton.addEventListener("click", function () {
      unit = unit === "  " ? "    " : unit === "    " ? "\t" : "  ";
      showIndent();
      box.focus();
    });
  }
  if (eolButton && eolInput) {
    eolButton.addEventListener("click", function () {
      eolInput.value = eolInput.value === "crlf" ? "lf" : "crlf";
      eolButton.textContent = eolInput.value === "crlf" ? "CRLF" : "LF";
      mark();
      box.focus();
    });
  }
  showIndent();
  showPosition();
  var commands = {
    bold: function () { wrapWith("**", t("bold text")); },
    italic: function () { wrapWith("*", t("italic text")); },
    strike: function () { wrapWith("~~", t("text")); },
    code: function () { wrapWith("`", t("code")); },
    link: link,
    heading: function () { togglePrefix("## ", false); },
    list: function () { togglePrefix("- ", true); },
    numbered: function () { togglePrefix("1. ", true); },
    quote: function () { togglePrefix("> ", false); },
    codeblock: codeBlock,
    comment: comment,
    indent: function () { indent(false); },
    outdent: function () { indent(true); },
  };

  document.querySelectorAll(".editor-toolbar [data-cmd]").forEach(function (button) {
    // Sin quitar el foco al cuadro (la selección se conserva)
    button.addEventListener("mousedown", function (e) { e.preventDefault(); });
    button.addEventListener("click", function () {
      var run = commands[button.getAttribute("data-cmd")];
      if (run) run();
    });
  });

  box.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { escaped = true; return; }
    var ctrl = (e.ctrlKey || e.metaKey) && !e.altKey;
    if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey && !escaped) {
      e.preventDefault();
      var multi = box.value.slice(box.selectionStart, box.selectionEnd).indexOf("\n") >= 0;
      if (e.shiftKey || multi) indent(e.shiftKey);
      else replace(box.selectionStart, box.selectionEnd, unit, box.selectionStart + unit.length,
                   box.selectionStart + unit.length);
      return;
    }
    if (ctrl && (e.key === "/" || e.code === "Slash") && commentStart) { e.preventDefault(); comment(); return; }
    if (ctrl && markdown && (e.key === "b" || e.key === "B")) { e.preventDefault(); commands.bold(); return; }
    if (ctrl && markdown && (e.key === "i" || e.key === "I")) { e.preventDefault(); commands.italic(); return; }
    escaped = false;
  });

  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === "s" || e.key === "S")) {
      e.preventDefault();
      window.SW.submit(form);
    }
  });

  form.addEventListener("submit", function () { saving = true; });
  window.SW.guardUnload(function () { return dirty && !saving; });
  box.focus();
})();
