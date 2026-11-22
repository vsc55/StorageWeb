// Explorador de archivos (browse.html): el núcleo. Renombrar, quitar favoritos, selección, panel de detalle,
// borrar, descargar y la barra de acciones. Lo demás va en js/files/, cargado detrás de este en el mismo orden:
//   files/transfer.js  mover y copiar (selector de destino y arrastrar filas a una carpeta)
//   files/listing.js   carpetas que no caben en la página (cargar más, filtro en el servidor) y el filtro
//   files/upload.js    subida por partes (no depende de la tabla)
// Comparten lo de aquí a través de SW.files (solo si hay tabla): las filas, la selección y dos registros,
// onRow (lo que se engancha a cada fila, también a las que llegan después) y actions (botones de la barra).
(function () {
  "use strict";

  var csrf = document.querySelector('meta[name="csrf-token"]').getAttribute("content");
  var t = window.SW.t;

  // ------------------------------------------------------------------ acciones de la tabla

  function wireRename(f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.renamed === "1") { delete f.dataset.renamed; return; }
      e.preventDefault();
      window.SW.prompt(t("New name:"), f.dataset.name).then(function (name) {
        name = (name || "").trim();
        if (!name || name === f.dataset.name) return;
        f.querySelector('input[name="name"]').value = name;
        f.dataset.renamed = "1";
        f.submit();
      });
    });
  }
  document.querySelectorAll("form.js-rename").forEach(wireRename);

  // ------------------------------------------------------------------ favoritos: la X de la lista
  // Quita el favorito sin recargar; si es la carpeta en la que estás, el formulario sigue (y la estrella se apaga)
  document.querySelectorAll("form.fav-remove").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.hasAttribute("data-here")) return;
      e.preventDefault();
      // getAttribute: el formulario tiene un campo «action», que tapa la propiedad f.action
      fetch(f.getAttribute("action"), { method: "POST", body: new FormData(f), credentials: "same-origin",
                        headers: { "Accept": "application/json" } })
        .then(function (r) {
          if (!r.ok) throw new Error(r.status);
          var li = f.closest("li");
          var list = li.parentNode;
          li.remove();
          // La fila del explorador, si está a la vista, deja de ser favorita (panel de detalle)
          var table = document.getElementById("file-table");
          if (table && table.dataset.root === f.elements.root.value) {
            table.querySelectorAll("tr.file-row").forEach(function (row) {
              if (row.dataset.rel === f.elements.path.value) row.dataset.fav = "0";
            });
          }
          if (!list.children.length) {   // sin favoritos: fuera la sección
            var title = list.previousElementSibling;
            if (title && title.classList.contains("panel-title")) title.remove();
            list.remove();
          }
        })
        .catch(function () { window.SW.alert(t("Network error.")); });
    });
  });

  // ------------------------------------------------------------------ explorador: selección y detalle

  var table = document.getElementById("file-table");
  if (!table) return;

  // Las filas de la página. Es SIEMPRE el mismo array (cargar más y el filtro lo cambian en el sitio): los
  // módulos de js/files/ lo leen a través de SW.files.rows
  var rows = Array.prototype.slice.call(table.querySelectorAll("tr.file-row"));
  var selectAll = document.getElementById("select-all");
  var bar = document.getElementById("selection-bar");
  var barCount = document.getElementById("selection-count");
  var details = {
    empty: document.getElementById("details-empty"),
    multi: document.getElementById("details-multi"),
    multiCount: document.getElementById("details-multi-count"),
    body: document.getElementById("details-body"),
    icon: document.getElementById("details-icon"),
    name: document.getElementById("details-name"),
    kind: document.getElementById("details-kind"),
    size: document.getElementById("details-size"),
    mtime: document.getElementById("details-mtime"),
    open: document.getElementById("details-open"),
    download: document.getElementById("details-download"),
    fav: document.getElementById("details-fav"),
    thumb: document.getElementById("details-thumb")
  };
  var rowHooks = [];
  var actions = {};

  function checkbox(row) { return row.querySelector("input.row-check"); }
  function selected() { return rows.filter(function (r) { return checkbox(r).checked; }); }
  function isDir(row) { return row.dataset.dir === "1"; }

  // Envía un formulario de fila como si lo hubiera enviado el usuario (con su confirmación/prompt)
  function submitForm(f) {
    if (!f) return;
    if (typeof f.requestSubmit === "function") { f.requestSubmit(); return; }
    var ev = new Event("submit", { cancelable: true });
    if (f.dispatchEvent(ev)) f.submit();
  }

  function countText(n) {
    return n === 1 ? t("1 item selected") : t("%(num)s items selected", { num: n });
  }

  function update() {
    var sel = selected();
    var n = sel.length;
    rows.forEach(function (r) { r.classList.toggle("selected", checkbox(r).checked); });
    if (bar) {
      bar.hidden = n === 0;
      barCount.textContent = countText(n);
      bar.querySelectorAll("[data-action]").forEach(function (b) {
        var a = b.dataset.action;
        if (a === "download") b.disabled = n === 0 || sel.some(function (r) { return !r.dataset.zip; });
        if (a === "move" || a === "copy") b.disabled = n === 0;
        if (a === "rename" || a === "share") b.disabled = n !== 1;
        if (a === "delete") b.disabled = n === 0;
      });
    }
    var visible = rows.filter(function (r) { return !r.hidden; });
    if (selectAll) {
      selectAll.checked = n > 0 && n === visible.length;
      selectAll.indeterminate = n > 0 && n < visible.length;
    }
    details.empty.hidden = n !== 0;
    details.multi.hidden = n < 2;
    details.body.hidden = n !== 1;
    if (n >= 2) details.multiCount.textContent = countText(n);
    if (n === 1) {
      var r = sel[0];
      details.name.textContent = r.dataset.name;
      details.kind.textContent = r.dataset.kind;
      details.size.textContent = r.dataset.size;
      details.mtime.textContent = r.dataset.mtime;
      details.icon.querySelector("use").setAttribute("href", isDir(r) ? "#i-folder" : "#i-file");
      details.icon.setAttribute("class", "icon icon-xl " + (isDir(r) ? "folder-icon" : "file-icon"));
      showThumb(r.dataset.thumb || "");
      details.open.hidden = !isDir(r) && !r.dataset.view;     // carpetas y archivos que se ven en el visor
      details.open.setAttribute("href", isDir(r) ? r.dataset.href : (r.dataset.view || "#"));
      if (details.download) {
        var link = isDir(r) ? r.dataset.zip : r.dataset.download;  // una carpeta se descarga como ZIP
        details.download.hidden = !link;
        details.download.setAttribute("href", link || "#");
      }
      if (details.fav) {
        var on = r.dataset.fav === "1";
        details.fav.dataset.rel = r.dataset.rel;
        details.fav.classList.toggle("is-on", on);
        details.fav.setAttribute("aria-pressed", on ? "true" : "false");
        details.fav.querySelector("span").textContent = on ? t("Remove from favorites") : t("Add to favorites");
      }
    }
  }

  // La miniatura en el panel de detalle (imágenes con data-thumb): en lugar del icono, si llega a cargar
  function showThumb(url) {
    if (!details.thumb) return;
    details.thumb.hidden = true;
    details.icon.hidden = false;
    if (!url) { details.thumb.removeAttribute("src"); return; }
    details.thumb.onload = function () { details.thumb.hidden = false; details.icon.hidden = true; };
    details.thumb.onerror = function () { details.thumb.hidden = true; details.icon.hidden = false; };
    details.thumb.src = url;
  }

  // Favoritos desde el panel de detalle: se marca o se quita y se recarga (el panel izquierdo cambia)
  if (details.fav) {
    details.fav.addEventListener("click", function () {
      var body = new URLSearchParams({ root: details.fav.dataset.root, path: details.fav.dataset.rel || "" });
      fetch(details.fav.dataset.favUrl, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf, "Accept": "application/json" }
      }).then(function (res) {
        if (!res.ok) throw new Error(String(res.status));
        window.location.reload();
      }).catch(function () { window.SW.alert(t("Network error.")); });
    });
  }

  function selectOnly(row) {
    rows.forEach(function (r) { checkbox(r).checked = r === row; });
    update();
  }

  // Eventos de una fila: las de la página y las que llegan después (cargar más, filtro en el servidor). Lo de
  // los módulos (arrastrar, en files/transfer.js) llega por onRow
  function wireRow(row) {
    checkbox(row).addEventListener("change", update);
    row.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      selectOnly(row);
    });
    row.addEventListener("dblclick", function (e) {
      if (e.target.closest("a, button, input, label, form")) return;
      if (row.dataset.href) window.location.href = row.dataset.href;
    });
    rowHooks.forEach(function (fn) { fn(row); });
  }
  rows.forEach(wireRow);

  if (selectAll) {
    selectAll.addEventListener("change", function () {
      rows.forEach(function (r) { if (!r.hidden) checkbox(r).checked = selectAll.checked; });
      update();
    });
  }

  function deleteMany(sel) {
    window.SW.confirm(t("Delete %(num)s items? This cannot be undone.", { num: sel.length }), { danger: true })
      .then(function (ok) { if (ok) deleteNow(sel); });
  }

  function deleteNow(sel) {
    var forms = sel.map(function (r) { return r.querySelector("form.js-delete"); }).filter(Boolean);
    var chain = Promise.resolve();
    forms.forEach(function (f) {
      chain = chain.then(function () {
        return fetch(f.action, { method: "POST", body: new FormData(f), headers: { "X-CSRF-Token": csrf },
                                 credentials: "same-origin" });
      });
    });
    chain.then(function () { window.location.reload(); },
               function () { window.SW.alert(t("Network error.")).then(function () { window.location.reload(); }); });
  }

  // ------------------------------------------------------------------ descargar (uno, o varios como ZIP)

  function downloadMany(sel) {
    if (sel.length === 1 && !isDir(sel[0]) && sel[0].dataset.download) { window.location.href = sel[0].dataset.download; return; }
    if (sel.length === 1 && sel[0].dataset.zip) { window.location.href = sel[0].dataset.zip; return; }
    var f = document.getElementById("zip-form");
    if (!f) return;
    f.querySelectorAll('input[name="items"]').forEach(function (i) { i.remove(); });
    sel.forEach(function (r) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = "items"; i.value = r.dataset.rel;
      f.appendChild(i);
    });
    f.submit();  // la respuesta es un adjunto: la página se queda donde está
  }

  // ------------------------------------------------------------------ la barra de acciones

  actions.download = downloadMany;
  actions.rename = function (sel) { if (sel.length === 1) submitForm(sel[0].querySelector("form.js-rename")); };
  actions["delete"] = function (sel) {
    if (sel.length === 1) submitForm(sel[0].querySelector("form.js-delete"));
    else deleteMany(sel);
  };

  function runAction(action) {
    var sel = selected();
    if (action === "clear") { rows.forEach(function (r) { checkbox(r).checked = false; }); update(); return; }
    if (sel.length && actions[action]) actions[action](sel);
  }

  document.querySelectorAll("#selection-bar [data-action], #details [data-action]").forEach(function (b) {
    b.addEventListener("click", function () { runAction(b.dataset.action); });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && selected().length && !e.target.closest("input, textarea, select")) runAction("clear");
  });

  // ------------------------------------------------------------------ lo que usan los módulos de js/files/

  window.SW.files = {
    table: table,
    here: { root: table.dataset.root, path: table.dataset.path || "" },
    csrf: csrf,
    rows: rows,
    checkbox: checkbox,
    selected: selected,
    isDir: isDir,
    selectOnly: selectOnly,
    update: update,
    wireRow: wireRow,
    wireRename: wireRename,
    actions: actions,
    // Engancha ``fn`` a cada fila: a las que ya hay y a las que lleguen después (wireRow)
    onRow: function (fn) { rowHooks.push(fn); rows.forEach(fn); }
  };

  update();
})();
