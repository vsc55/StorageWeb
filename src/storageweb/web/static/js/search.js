// Buscador de la administración: Ctrl+K (o /) abre el diálogo; consulta /admin/search?format=json.
// Sin JavaScript, el formulario lleva a la página de resultados /admin/search?q=…
(function () {
  "use strict";
  var dialog = document.getElementById("admin-search");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var form = dialog.querySelector("form");
  var input = dialog.querySelector("input[name=q]");
  var list = document.getElementById("admin-search-results");
  var url = form.getAttribute("data-search-url");
  var t = window.SW.t;

  var items = [];
  var active = 0;
  var timer = null;
  var seq = 0;

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text) node.textContent = text;
    return node;
  }

  function icon(name, fallback) {
    var box = el("span", "result-icon");
    if (name) {
      var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "icon");
      svg.setAttribute("aria-hidden", "true");
      var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
      use.setAttribute("href", "#i-" + name);
      svg.appendChild(use);
      box.appendChild(svg);
    } else {
      box.textContent = fallback;
    }
    return box;
  }

  function render(results, query) {
    list.textContent = "";
    items = [];
    active = 0;
    var last = "";
    results.forEach(function (r) {
      if (r.group !== last) {
        var head = el("li", null);
        head.setAttribute("role", "presentation");
        head.appendChild(el("span", "result-group", r.group));
        list.appendChild(head);
        last = r.group;
      }
      var li = el("li", null);
      li.setAttribute("role", "presentation");
      var a = el("a", "result result-" + r.kind);
      a.href = r.url;
      a.setAttribute("role", "option");
      a.id = "search-result-" + items.length;
      a.appendChild(icon(r.icon, r.kind === "setting" ? "#" : r.title.charAt(0).toUpperCase()));
      var text = el("span", "result-text");
      text.appendChild(el("strong", null, r.title));
      if (r.path) text.appendChild(el("span", null, r.path));
      a.appendChild(text);
      if (r.hint) a.appendChild(el("span", "result-hint", r.hint));
      li.appendChild(a);
      list.appendChild(li);
      items.push(a);
    });
    if (!results.length) {
      var empty = el("li", "palette-empty", t("Nothing found for «%(query)s».", { query: query }));
      list.appendChild(empty);
    }
    highlight();
  }

  function highlight() {
    items.forEach(function (a, i) {
      var on = i === active;
      a.classList.toggle("is-active", on);
      a.setAttribute("aria-selected", on ? "true" : "false");
      if (on) {
        input.setAttribute("aria-activedescendant", a.id);
        a.scrollIntoView({ block: "nearest" });
      }
    });
    if (!items.length) input.removeAttribute("aria-activedescendant");
  }

  function query() {
    var q = input.value;
    var mine = ++seq;
    fetch(url + "&q=" + encodeURIComponent(q), { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) { if (mine === seq) render(data.results, q); })
      .catch(function () { /* se puede seguir con Enter: página de resultados */ });
  }

  function open(initial) {
    if (dialog.open) return;
    dialog.showModal();
    input.value = initial || "";
    query();
    input.focus();
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(query, 120);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      highlight();
    } else if (e.key === "Enter" && items[active]) {
      e.preventDefault();
      window.location.href = items[active].href;
      dialog.close();
    }
  });
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog) dialog.close();  // clic fuera del cuadro
  });
  // Ir a un ajuste de la misma página: el ancla cambia y no se recarga, así que se cierra el diálogo
  list.addEventListener("click", function (e) {
    if (e.target.closest("a")) dialog.close();
  });

  document.addEventListener("keydown", function (e) {
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      open();
    } else if (e.key === "/" && !typing && !dialog.open) {
      e.preventDefault();
      open();
    }
  });
  document.querySelectorAll("[data-open-search]").forEach(function (box) {
    var field = box.querySelector("input");
    box.addEventListener("submit", function (e) { e.preventDefault(); open(field ? field.value : ""); });
    if (field) {
      field.addEventListener("focus", function () { open(field.value); field.blur(); });
    }
  });
})();
