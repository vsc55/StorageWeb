// Importar de un directorio (Personas → Importar y Grupos → Importar, de Entra ID): la lista se va formando mientras se
// escribe, sin pulsar Buscar; «Mostrar todos» la trae por páginas y carga las siguientes al bajar; y se pueden marcar
// varios e importarlos de una vez («Importar seleccionados»), también de búsquedas distintas: la selección se conserva
// al buscar otra cosa. Las dos páginas usan los mismos id (import-search, import-results, import-bulk…).
//
// Los resultados los da el servidor ya pintados: ?partial=1 (la lista entera) y ?rows=1 (solo las filas de la página
// siguiente, con la dirección de la otra en X-Next). Las casillas son del formulario #import-bulk (form="import-bulk");
// las seleccionadas que no están a la vista viajan en campos ocultos. Una respuesta que llega tarde (de lo que se
// escribía antes) se descarta. Sin JavaScript: Buscar, Mostrar todos, Cargar más y las casillas de la lista a la vista.
(function () {
  "use strict";

  var form = document.getElementById("import-search");
  var results = document.getElementById("import-results");
  var bulk = document.getElementById("import-bulk");
  if (!form || !results || !bulk) return;
  var t = window.SW.t;
  var input = form.querySelector("input[name=q]");
  var source = form.querySelector("[name=source]");
  var showAll = document.getElementById("import-all");
  var kept = document.getElementById("import-kept");
  var count = document.getElementById("import-count");
  var clearBtn = document.getElementById("import-clear");
  var importBtn = document.getElementById("import-selected");
  var base = form.dataset.results;

  var selected = {};            // id → nombre: la selección, también de búsquedas anteriores
  var timer = null;
  var seq = 0;
  var controller = null;
  var observer = null;
  var loadingMore = false;
  var last = input.value.trim();

  // ------------------------------------------------------------------ la selección
  function picks() { return results.querySelectorAll("input.import-pick"); }

  function paintSelection() {
    var ids = Object.keys(selected);
    // Las que no están a la vista viajan en campos ocultos; las visibles, en su casilla
    var visible = {};
    Array.prototype.forEach.call(picks(), function (box) { visible[box.value] = true; box.checked = !!selected[box.value]; });
    kept.innerHTML = "";
    ids.forEach(function (id) {
      if (visible[id]) return;
      var hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = "ids";
      hidden.value = id;
      kept.appendChild(hidden);
    });
    count.textContent = ids.length ? count.dataset.template.replace("%(num)s", ids.length) : "";
    clearBtn.hidden = !ids.length;
    importBtn.disabled = !ids.length;
    var all = document.getElementById("import-all-rows");
    if (all) {
      all.hidden = !picks().length;
      var boxes = Array.prototype.slice.call(picks());
      all.checked = boxes.length > 0 && boxes.every(function (b) { return b.checked; });
      all.indeterminate = !all.checked && boxes.some(function (b) { return b.checked; });
    }
  }

  results.addEventListener("change", function (event) {
    var box = event.target;
    if (box.id === "import-all-rows") {
      Array.prototype.forEach.call(picks(), function (b) {
        if (box.checked) selected[b.value] = b.dataset.name; else delete selected[b.value];
      });
    } else if (box.classList && box.classList.contains("import-pick")) {
      if (box.checked) selected[box.value] = box.dataset.name; else delete selected[box.value];
    } else {
      return;
    }
    paintSelection();
  });

  clearBtn.addEventListener("click", function () { selected = {}; paintSelection(); });

  // ------------------------------------------------------------------ los resultados
  function params(extra) {
    var p = new URLSearchParams();
    if (source) p.set("source", source.value);
    Object.keys(extra).forEach(function (k) { if (extra[k] !== "") p.set(k, extra[k]); });
    return p;
  }

  function wire() {
    if (window.SW.sortable) window.SW.sortable(results);
    paintSelection();
    watchMore();
  }

  function load(extra, address) {
    window.history.replaceState(null, "", base + "?" + params(address).toString());
    var mine = ++seq;
    if (controller) controller.abort();
    controller = "AbortController" in window ? new AbortController() : null;
    extra.partial = "1";
    results.setAttribute("aria-busy", "true");
    window.SW.page(base + "?" + params(extra).toString(), {
      signal: controller ? controller.signal : undefined
    }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text();
    }).then(function (html) {
      if (mine !== seq) return;          // llegó tarde: ya se pedía otra cosa
      results.innerHTML = html;
      wire();
    }).catch(function (err) {
      if (err && err.name === "AbortError") return;
      if (mine === seq) window.SW.alert(t("Network error."));
    }).then(function () {
      if (mine === seq) results.removeAttribute("aria-busy");
    });
  }

  function search() {
    var text = input.value.trim();
    if (text === last) return;
    last = text;
    if (text.length < 2) {
      ++seq;
      results.innerHTML = "";
      window.history.replaceState(null, "", base + "?" + params({ q: text }).toString());
      paintSelection();
      return;
    }
    load({ q: text }, { q: text });
  }

  input.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(search, 300);
  });
  if (source) source.addEventListener("change", function () { last = null; search(); });
  form.addEventListener("submit", function (event) {          // Enter: ya, sin esperar a la pausa ni recargar
    event.preventDefault();
    clearTimeout(timer);
    last = null;
    search();
  });
  if (showAll) {
    showAll.addEventListener("click", function (event) {
      event.preventDefault();
      clearTimeout(timer);
      input.value = "";
      last = "";
      load({ all: "1" }, { all: "1" });
    });
  }

  // ------------------------------------------------------------------ al bajar, la página siguiente
  function loadMore(link) {
    if (loadingMore || !link.dataset.next) return;
    loadingMore = true;
    var mine = seq;
    window.SW.page(link.dataset.next)
      .then(function (r) {
        if (!r.ok) throw new Error(r.status);
        return r.text().then(function (html) { return { html: html, next: r.headers.get("X-Next") || "" }; });
      }).then(function (page) {
        if (mine !== seq) return;        // entretanto se buscó otra cosa
        var tpl = document.createElement("template");
        tpl.innerHTML = page.html;
        var body = results.querySelector("tbody");
        Array.prototype.forEach.call(tpl.content.querySelectorAll("tr"), function (row) { body.appendChild(row); });
        if (page.next) {
          link.dataset.next = page.next;
          link.href = page.next.replace("rows=1", "rows=0");
        } else {
          link.parentNode.remove();
        }
        paintSelection();
      }).catch(function () { window.SW.alert(t("Network error.")); })
      .then(function () {
        loadingMore = false;
        // Observarlo de nuevo da su estado de ahora: si sigue cerca (pantallas altas), otra página
        if (observer && document.getElementById("import-more")) {
          observer.unobserve(link); observer.observe(link);
        }
      });
  }

  function watchMore() {
    if (observer) observer.disconnect();
    var link = document.getElementById("import-more");
    if (!link) return;
    link.addEventListener("click", function (event) { event.preventDefault(); loadMore(link); });
    if ("IntersectionObserver" in window) {
      observer = new IntersectionObserver(function (entries) {
        if (entries[entries.length - 1].isIntersecting) loadMore(link);
      }, { rootMargin: "400px 0px" });
      observer.observe(link);
    }
  }

  // Sin seleccionar nada, el botón no hace nada (sin JavaScript, el servidor lo dice)
  bulk.addEventListener("submit", function (event) {
    if (!Object.keys(selected).length) event.preventDefault();
  });
  wire();
})();
