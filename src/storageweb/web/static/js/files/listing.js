// Explorador: el filtro de la carpeta y las carpetas que no caben en la página (storage.page_size /
// listing_mode, files._listing). Con toda la carpeta en la página, el filtro esconde filas al momento; si no
// (#listing-foot), «scroll» carga más filas al bajar y el filtro pregunta al servidor (entre todas las de la
// carpeta), también por trozos. Las filas nuevas pasan por SW.files.wireRow. Necesita el núcleo (app.js).
(function () {
  "use strict";

  var files = window.SW && window.SW.files;
  if (!files) return;
  var t = window.SW.t;
  var rows = files.rows;                 // el array del núcleo: se cambia en el sitio, nunca se sustituye

  var filterInput = document.getElementById("filter-input");
  var filterEmpty = document.getElementById("filter-empty");
  var foot = document.getElementById("listing-foot");
  var tbody = files.table.tBodies[0];
  var pager = document.getElementById("listing-pager");
  var loadMoreBtn = document.getElementById("load-more");
  var statusEl = document.getElementById("listing-status");
  var initialStatus = statusEl ? statusEl.textContent : "";
  var mode = foot ? foot.dataset.mode : "";
  var nextRows = foot ? foot.dataset.next : "";
  var query = filterInput ? filterInput.value.trim() : "";
  var total = foot ? parseInt(foot.dataset.total, 10) || 0 : 0;
  var loading = false;
  var seq = 0;

  function canLoadMore() { return !!nextRows && (mode === "scroll" || query !== ""); }

  function refreshFoot() {
    if (!foot) return;
    if (pager) pager.hidden = mode !== "pages" || query !== "";
    if (loadMoreBtn) loadMoreBtn.hidden = !canLoadMore();
    if (statusEl && (mode === "scroll" || query !== "")) {
      statusEl.textContent = query
        ? t("%(shown)s of %(total)s items match «%(query)s»", { shown: rows.length, total: total, query: query })
        : t("%(shown)s of %(total)s items", { shown: rows.length, total: total });
    } else if (statusEl) {
      statusEl.textContent = initialStatus;
    }
    if (filterEmpty) filterEmpty.hidden = rows.length > 0 || query === "";
  }

  function fetchRows(url) {
    return fetch(url, { credentials: "same-origin", headers: { "Accept": "text/html" } }).then(function (r) {
      if (!r.ok) throw new Error(r.status);
      return r.text().then(function (html) {
        return { html: html, next: r.headers.get("X-Next") || "", total: parseInt(r.headers.get("X-Total"), 10) || 0 };
      });
    });
  }

  function putRows(html, replace) {
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    if (replace) {
      rows.forEach(function (r) { r.remove(); });
      rows.length = 0;
    }
    var empty = tbody.querySelector("tr.row-empty");
    if (empty) empty.remove();
    Array.prototype.forEach.call(tpl.content.querySelectorAll("tr.file-row"), function (row) {
      tbody.appendChild(row);
      rows.push(row);
      files.wireRow(row);
      row.querySelectorAll("form.js-rename").forEach(files.wireRename);
      row.querySelectorAll("form.js-confirm").forEach(window.SW.confirmForm);
    });
    files.update();
  }

  function loadMore() {
    if (loading || !canLoadMore()) return;
    loading = true;
    var mine = seq;
    fetchRows(nextRows).then(function (res) {
      if (mine !== seq) return;          // el filtro cambió mientras tanto
      putRows(res.html, false);
      nextRows = res.next;
      total = res.total;
      refreshFoot();
      return true;
    }).catch(function () { window.SW.alert(t("Network error.")); return false; })
      .then(function (ok) {
        loading = false;
        // El observador solo avisa cuando cambia de estado: si se llega al botón antes de que vea que las filas
        // nuevas lo apartaron, nunca vuelve a avisar. Observarlo de nuevo da su estado de ahora (y si sigue
        // cerca, se carga otro trozo).
        if (ok && mine === seq && observer) { observer.unobserve(loadMoreBtn); observer.observe(loadMoreBtn); }
      });
  }

  var observer = null;
  if (foot) {
    if (mode === "scroll" && pager) pager.hidden = true;   // sin JavaScript, el paginador
    if (loadMoreBtn) {
      loadMoreBtn.addEventListener("click", loadMore);
      if ("IntersectionObserver" in window) {
        observer = new IntersectionObserver(function (entries) {
          if (entries[entries.length - 1].isIntersecting) loadMore();
        }, { rootMargin: "600px 0px" });
        observer.observe(loadMoreBtn);
      }
    }
    refreshFoot();
  }

  // El filtro: en una carpeta entera en la página, al momento sobre las filas; si no, pregunta al servidor
  var filterTimer = null;
  function serverFilter() {
    var mine = ++seq;
    loading = false;
    // Sin filtro, vuelve a lo de antes: la página del paginador o el principio
    var url = foot.dataset.filter + (query ? "&q=" + encodeURIComponent(query)
      : (mode === "pages" ? "&page=" + foot.dataset.page : ""));
    fetchRows(url).then(function (res) {
      if (mine !== seq) return;
      putRows(res.html, true);
      nextRows = res.next;
      total = res.total;
      refreshFoot();
    }).catch(function () { window.SW.alert(t("Network error.")); });
  }

  if (filterInput) {
    filterInput.addEventListener("input", function () {
      if (foot) {
        query = filterInput.value.trim();
        clearTimeout(filterTimer);
        filterTimer = setTimeout(serverFilter, 250);
        return;
      }
      var q = filterInput.value.trim().toLowerCase();
      var shown = 0;
      rows.forEach(function (r) {
        var match = !q || r.dataset.name.toLowerCase().indexOf(q) !== -1;
        r.hidden = !match;
        if (!match) files.checkbox(r).checked = false;
        if (match) shown++;
      });
      if (filterEmpty) filterEmpty.hidden = shown > 0 || rows.length === 0;
      files.update();
    });
  }
})();
