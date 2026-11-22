// Las tablas de la aplicación (table.files): ordenar al pulsar una cabecera y elegir qué columnas se ven. Lo hace este
// script para todas (se carga en todas las páginas, después de common.js), sin que cada plantilla tenga que hacer
// nada; también con las que llegan después sin recargar (paneles, resultados de importar…: SW.onWire).
//
// Ordenar
// * En el navegador, ascendente y descendente. El tipo de cada columna sale de su <th data-sort> («text», «number»,
//   «version», «date», «size») o, si no lo trae, de lo que hay en ella: números, fechas como las escribe la página
//   (22/11/26, 16:46 en castellano; 11/22/26, 4:46 PM en inglés), tamaños (1,2 MB) o texto (sin distinguir mayúsculas
//   ni tildes; 1.10 después de 1.9). El valor es el texto de la celda o su data-sort-value. Lo vacío («—») va siempre al
//   final.
// * En el servidor, las tablas que van por páginas (Usuarios, Auditoría): solo las columnas con <th
//   data-sort-server="clave">, que llevan a la misma página con ?sort=clave&order=asc|desc; la tabla dice cómo está
//   ordenada con data-sort-key y data-sort-order.
// * No se ordenan la columna de las casillas, la de las acciones (cabecera vacía o solo para lectores de pantalla) ni
//   las <th data-no-sort>. Las cabeceras pasan a ser botones (teclado y lectores de pantalla) y llevan aria-sort.
//
// Columnas
// * Con 3 o más columnas que se puedan quitar, un botón «Columnas» encima abre la lista para enseñar u ocultar cada
//   una (la primera, las casillas y las acciones siempre se ven). Se recuerda por tabla en este navegador
//   (SW.store; la tabla se identifica por data-table o, si no lo trae, por la página y su posición en ella).
//   Ocultar es una clase en la tabla (hide-col-N, admin.css): vale también para las filas que lleguen después.
//
// No se tocan: table[data-plain] (el explorador de archivos, la matriz de accesos, formularios en tabla).
(function () {
  "use strict";

  var t = window.SW.t;
  var lang = (document.documentElement.lang || "en").toLowerCase();
  var collator = new Intl.Collator(lang || undefined, { numeric: true, sensitivity: "base" });
  var MAX_COLUMNS = 20;          // las clases hide-col-1 … hide-col-20 de admin.css

  // ------------------------------------------------------------------ valores
  function cellValue(row, index) {
    var cell = row.cells[index];
    if (!cell) return "";
    return cell.hasAttribute("data-sort-value") ? cell.getAttribute("data-sort-value") : cell.textContent.trim();
  }

  function isEmpty(value) { return value === "" || value === "—" || value === "-"; }

  var SIZE_UNITS = { b: 1, kb: 1024, mb: 1048576, gb: 1073741824, tb: 1099511627776 };
  var SIZE_RE = /^(-?[\d.,]+)\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)$/i;
  var DATE_RE = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:,?\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AaPp]\.?\s?[Mm]\.?)?)?$/;
  var NUMBER_RE = /^-?[\d\s.,]*\d$/;

  function toNumber(text) {
    var s = text.replace(/\s/g, "");
    // «1.234,5» (castellano) o «1,234.5» (inglés): el último separador con 1–2 cifras detrás es el decimal
    if (/,\d{1,2}$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
    else s = s.replace(/,/g, "");
    return parseFloat(s);
  }

  function toSize(text) {
    var m = SIZE_RE.exec(text);
    if (!m) return NaN;
    return toNumber(m[1]) * (SIZE_UNITS[m[2].toLowerCase().replace("i", "")] || 1);
  }

  function toDate(text) {
    var m = DATE_RE.exec(text);
    if (!m) return NaN;
    var a = +m[1], b = +m[2], year = +m[3];
    var day = lang.indexOf("en") === 0 ? b : a, month = lang.indexOf("en") === 0 ? a : b;
    if (year < 100) year += 2000;
    var hour = m[4] ? +m[4] : 0;
    if (m[7]) {                                          // 4:46 PM
      var pm = /^p/i.test(m[7]);
      if (hour === 12) hour = pm ? 12 : 0; else if (pm) hour += 12;
    }
    return Date.UTC(year, month - 1, day, hour, m[5] ? +m[5] : 0, m[6] ? +m[6] : 0);
  }

  // El tipo de una columna: el de su <th data-sort> o el que tienen todos sus valores no vacíos
  function columnType(table, th) {
    if (th.dataset.sort) return th.dataset.sort;
    var values = Array.prototype.map.call(table.tBodies[0].rows, function (row) { return cellValue(row, th.cellIndex); })
      .filter(function (v) { return !isEmpty(v); });
    if (!values.length) return "text";
    var all = function (test) { return values.every(test); };
    if (all(function (v) { return !isNaN(toDate(v)); })) return "date";
    if (all(function (v) { return !isNaN(toSize(v)); })) return "size";
    if (all(function (v) { return NUMBER_RE.test(v) && !isNaN(toNumber(v)); })) return "number";
    return "text";
  }

  function compare(type, a, b) {
    if (type === "number" || type === "date" || type === "size") {
      var parse = type === "date" ? toDate : type === "size" ? toSize : toNumber;
      var x = parse(a), y = parse(b);
      if (!isNaN(x) && !isNaN(y)) return x - y;
    }
    return collator.compare(a, b);      // «version» también: la comparación numérica ordena 1.9 < 1.10
  }

  // ------------------------------------------------------------------ ordenar
  function sortBy(table, th, descending) {
    var index = th.cellIndex;
    var type = columnType(table, th);
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows).filter(function (r) { return r.cells.length > 1 || !r.cells[0] || r.cells[0].colSpan <= 1; });
    if (rows.length < 2) return setSorted(table, th, descending);
    rows.sort(function (r1, r2) {
      var a = cellValue(r1, index), b = cellValue(r2, index);
      var blank = isEmpty(a) || isEmpty(b);
      if (blank) return isEmpty(a) === isEmpty(b) ? 0 : (isEmpty(a) ? 1 : -1);   // lo vacío, al final (también en descendente)
      var result = compare(type, a, b);
      return descending ? -result : result;
    });
    rows.forEach(function (row) { body.appendChild(row); });
    setSorted(table, th, descending);
  }

  function setSorted(table, th, descending) {
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (cell) {
      if (cell.hasAttribute("aria-sort")) cell.setAttribute("aria-sort", "none");
    });
    th.setAttribute("aria-sort", descending ? "descending" : "ascending");
  }

  // La dirección de la misma página ordenada por ``key`` (en el servidor): vuelve a la primera página
  function serverUrl(key, descending) {
    var url = new URL(location.href);
    url.searchParams.set("sort", key);
    url.searchParams.set("order", descending ? "desc" : "asc");
    url.searchParams.delete("page");
    return url.toString();
  }

  // Las columnas que no se ordenan ni se quitan: casillas, acciones (sin texto visible) y las marcadas
  function isCheckColumn(th) { return th.classList.contains("col-check") || th.classList.contains("check-col") || !!th.querySelector("input[type=checkbox]"); }
  function isActionsColumn(th) {
    var visible = th.cloneNode(true);
    Array.prototype.forEach.call(visible.querySelectorAll(".sr-only"), function (n) { n.remove(); });
    return !visible.textContent.trim() || th.classList.contains("actions");
  }
  function label(th) {
    var visible = th.cloneNode(true);
    Array.prototype.forEach.call(visible.querySelectorAll(".sr-only, .sort-arrow"), function (n) { n.remove(); });
    return visible.textContent.trim().replace(/\s+/g, " ");
  }

  function wireSort(table) {
    var server = table.querySelector("th[data-sort-server]") !== null;
    var current = table.dataset.sortKey || "";
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th) {
      if (th.hasAttribute("data-no-sort") || isCheckColumn(th) || isActionsColumn(th)) return;
      if (server && !th.dataset.sortServer) return;          // van por páginas: solo las que sabe ordenar el servidor
      var text = label(th);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "sort-btn";
      button.title = t("Sort by %(column)s", { column: text });
      while (th.firstChild) button.appendChild(th.firstChild);
      th.appendChild(button);
      th.setAttribute("aria-sort", "none");
      if (server && th.dataset.sortServer === current) {
        th.setAttribute("aria-sort", table.dataset.sortOrder === "desc" ? "descending" : "ascending");
      }
      button.addEventListener("click", function () {
        var descending = th.getAttribute("aria-sort") === "ascending";   // la primera vez, ascendente; luego alterna
        if (server) location.href = serverUrl(th.dataset.sortServer, descending);
        else sortBy(table, th, descending);
      });
    });
  }

  // ------------------------------------------------------------------ columnas
  function tableKey(table) {
    if (table.dataset.table) return "sw-cols:" + table.dataset.table;
    var all = Array.prototype.slice.call(document.querySelectorAll("table.files:not([data-plain])"));
    return "sw-cols:" + location.pathname + ":" + Math.max(all.indexOf(table), 0);
  }

  function readHidden(key) {
    try { return JSON.parse(window.SW.store(key) || "[]"); } catch (e) { return []; }
  }

  function applyHidden(table, columns, hidden) {
    columns.forEach(function (col) {
      var off = hidden.indexOf(col.label) !== -1;
      table.classList.toggle("hide-col-" + (col.th.cellIndex + 1), off);
      col.box.checked = !off;
    });
  }

  function wireColumns(table) {
    if (table.hasAttribute("data-no-columns")) return;
    var cells = Array.prototype.slice.call(table.tHead.rows[0].cells);
    if (cells.length > MAX_COLUMNS) return;
    var columns = cells.filter(function (th, i) {
      return i > 0 && !isCheckColumn(th) && !isActionsColumn(th) && !(i === 1 && isCheckColumn(cells[0]));
    }).map(function (th) { return { th: th, label: label(th) }; });
    if (columns.length < 3) return;                           // tablas pequeñas: no hace falta
    var key = tableKey(table);

    var menu = window.SW.el("details", "popover table-columns");
    var summary = window.SW.el("summary", "btn btn-small");
    summary.appendChild(window.SW.icon("list", "icon-sm"));
    summary.appendChild(document.createTextNode(t("Columns")));
    menu.appendChild(summary);
    var body = window.SW.el("div", "popover-body table-columns-body");
    body.setAttribute("role", "group");
    body.setAttribute("aria-label", t("Columns"));
    columns.forEach(function (col) {
      var row = window.SW.el("label", "check");
      col.box = document.createElement("input");
      col.box.type = "checkbox";
      col.box.checked = true;
      row.appendChild(col.box);
      row.appendChild(document.createTextNode(" " + col.label));
      body.appendChild(row);
      col.box.addEventListener("change", function () {
        var hidden = columns.filter(function (c) { return !c.box.checked; }).map(function (c) { return c.label; });
        window.SW.store(key, hidden.length ? JSON.stringify(hidden) : null);
        applyHidden(table, columns, hidden);
      });
    });
    var reset = window.SW.el("button", "btn btn-small btn-ghost", t("Show all columns"));
    reset.type = "button";
    reset.addEventListener("click", function () {
      window.SW.store(key, null);
      applyHidden(table, columns, []);
    });
    body.appendChild(reset);
    menu.appendChild(body);

    var bar = window.SW.el("div", "table-tools");
    bar.appendChild(menu);
    var anchor = table.closest(".table-scroll") || table;
    anchor.parentNode.insertBefore(bar, anchor);
    applyHidden(table, columns, readHidden(key));
  }

  // ------------------------------------------------------------------ todas
  function wire(table) {
    if (!table.tHead || !table.tHead.rows.length || !table.tBodies.length || table.dataset.tableReady === "1") return;
    if (table.hasAttribute("data-plain")) return;
    table.dataset.tableReady = "1";
    wireSort(table);
    wireColumns(table);
  }

  window.SW.onWire(function (root) {
    Array.prototype.forEach.call(root.querySelectorAll("table.files"), wire);
  });
  // Lo de antes (Personas → Importar lo llama con los resultados que llegan mientras se escribe)
  window.SW.sortable = function (root) {
    Array.prototype.forEach.call((root || document).querySelectorAll("table.files"), wire);
  };
})();
