// Explorador: mover y copiar. El selector de carpeta de destino (botones Mover/Copiar de la barra) y arrastrar
// filas a una carpeta de la tabla o del árbol (Ctrl o Alt: copiar). Los dos acaban en el mismo formulario
// (#transfer-form → files.transfer). Necesita el núcleo (app.js, SW.files).
(function () {
  "use strict";

  var files = window.SW && window.SW.files;
  if (!files) return;
  var t = window.SW.t;
  var here = files.here;

  function submitTransfer(action, items, destRoot, destPath) {
    var f = document.getElementById("transfer-form");
    if (!f) return;
    f.querySelector('input[name="action"]').value = action;
    f.querySelector('input[name="dest_root"]').value = destRoot;
    f.querySelector('input[name="dest_path"]').value = destPath;
    f.querySelectorAll('input[name="items"]').forEach(function (i) { i.remove(); });
    items.forEach(function (rel) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = "items"; i.value = rel;
      f.appendChild(i);
    });
    f.submit();
  }

  // ------------------------------------------------------------------ el selector de destino

  var picker = document.getElementById("pick-dest");
  var pick = { action: "move", items: [], root: here.root, path: here.path, roots: null };

  function encodePath(p) { return p.split("/").filter(Boolean).map(encodeURIComponent).join("/"); }

  // Por qué no se pueden poner aquí ("" = sí se puede)
  function pickProblem() {
    var r = (pick.roots || []).find(function (x) { return x.name === pick.root; });
    if (!r) return t("You cannot write in this folder.");
    var perms = r.permissions;
    var inside = pick.root === here.root && pick.items.some(function (rel) {
      return pick.path === rel || pick.path.indexOf(rel + "/") === 0;
    });
    if (inside) return t("A folder cannot go inside itself.");
    if (pick.action === "move" && pick.root === here.root) {
      if (pick.path === here.path) return t("They are already in this folder: choose another one.");
      return perms.indexOf("rename") !== -1 ? "" : t("You cannot write in this folder.");
    }
    return perms.indexOf("upload") !== -1 ? "" : t("You cannot write in this folder.");
  }
  function pickAllowed() { return !pickProblem(); }

  function renderPicker() {
    var list = document.getElementById("pick-list");
    var crumbs = document.getElementById("pick-crumbs");
    var ok = document.getElementById("pick-ok");
    var note = document.getElementById("pick-note");
    document.getElementById("pick-root").value = pick.root;
    crumbs.innerHTML = "";
    var parts = pick.path.split("/").filter(Boolean);
    var top = document.createElement("button");
    top.type = "button";
    top.textContent = "/";
    top.addEventListener("click", function () { pick.path = ""; renderPicker(); });
    crumbs.appendChild(top);
    parts.forEach(function (part, i) {
      var sep = document.createElement("span");
      sep.className = "sep"; sep.textContent = "›";
      var b = document.createElement("button");
      b.type = "button"; b.textContent = part;
      b.addEventListener("click", function () { pick.path = parts.slice(0, i + 1).join("/"); renderPicker(); });
      crumbs.appendChild(sep);
      crumbs.appendChild(b);
    });
    var problem = pickProblem();
    ok.disabled = !!problem;
    note.hidden = !problem;
    note.textContent = problem;
    list.innerHTML = '<li class="muted">' + t("Loading…") + "</li>";
    var url = picker.dataset.browse.replace("ROOTNAME", encodeURIComponent(pick.root)) + encodePath(pick.path);
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        list.innerHTML = "";
        var dirs = (data.entries || []).filter(function (e) { return e.type === "dir"; });
        if (pick.path) {
          var up = document.createElement("li");
          var ub = document.createElement("button");
          ub.type = "button"; ub.textContent = "↑ ..";
          ub.addEventListener("click", function () { pick.path = parts.slice(0, -1).join("/"); renderPicker(); });
          up.appendChild(ub);
          list.appendChild(up);
        }
        dirs.forEach(function (e) {
          var li = document.createElement("li");
          var b = document.createElement("button");
          b.type = "button";
          b.innerHTML = '<svg class="icon icon-sm folder-icon" aria-hidden="true"><use href="#i-folder"></use></svg>';
          b.appendChild(document.createTextNode(e.name));
          b.addEventListener("click", function () { pick.path = e.path; renderPicker(); });
          li.appendChild(b);
          list.appendChild(li);
        });
        if (!dirs.length && !pick.path) list.innerHTML = '<li class="muted">' + t("No subfolders.") + "</li>";
      }, function () {
        list.innerHTML = '<li class="muted">' + t("Could not read this folder.") + "</li>";
      });
  }

  function openPicker(action, sel) {
    if (!picker || !sel.length) return;
    pick.action = action;
    pick.items = sel.map(function (r) { return r.dataset.rel; });
    pick.root = here.root;
    pick.path = here.path;
    var n = sel.length;
    document.getElementById("pick-title").textContent = action === "move"
      ? (n === 1 ? t("Move «%(name)s» to…", { name: sel[0].dataset.name }) : t("Move %(num)s items to…", { num: n }))
      : (n === 1 ? t("Copy «%(name)s» to…", { name: sel[0].dataset.name }) : t("Copy %(num)s items to…", { num: n }));
    document.getElementById("pick-ok").textContent = action === "move" ? t("Move here") : t("Copy here");
    var load = pick.roots ? Promise.resolve(pick.roots)
      : fetch(picker.dataset.roots, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
          .then(function (r) { return r.json(); }).then(function (d) { pick.roots = d.roots || []; return pick.roots; });
    load.then(function (roots) {
      var select = document.getElementById("pick-root");
      select.innerHTML = "";
      roots.forEach(function (r) {
        var o = document.createElement("option");
        o.value = r.name; o.textContent = r.label + (r.read_only ? " (" + t("read-only") + ")" : "");
        select.appendChild(o);
      });
      renderPicker();
      picker.showModal();
    });
  }

  if (picker) {
    document.getElementById("pick-root").addEventListener("change", function (e) {
      pick.root = e.target.value; pick.path = ""; renderPicker();
    });
    document.getElementById("pick-cancel").addEventListener("click", function () { picker.close(); });
    document.getElementById("pick-ok").addEventListener("click", function () {
      if (!pickAllowed()) return;
      picker.close();
      submitTransfer(pick.action, pick.items, pick.root, pick.path);
    });
  }

  files.actions.move = function (sel) { openPicker("move", sel); };
  files.actions.copy = function (sel) { openPicker("copy", sel); };

  // ------------------------------------------------------------------ arrastrar filas a una carpeta (Ctrl: copiar)

  var DRAG_TYPE = "application/x-storageweb-items";
  var dragging = null;

  files.onRow(function (row) {
    if (row.getAttribute("draggable") !== "true") return;
    row.addEventListener("dragstart", function (e) {
      if (!files.checkbox(row).checked) files.selectOnly(row);
      dragging = files.selected().map(function (r) { return r.dataset.rel; });
      e.dataTransfer.effectAllowed = "copyMove";
      e.dataTransfer.setData(DRAG_TYPE, JSON.stringify(dragging));
      e.dataTransfer.setData("text/plain", files.selected().map(function (r) { return r.dataset.name; }).join("\n"));
    });
    row.addEventListener("dragend", function () { dragging = null; });
  });

  function dropTarget(el) {
    var row = el.closest("tr.file-row");
    if (row && files.isDir(row) && !files.checkbox(row).checked) return { el: row, root: here.root, path: row.dataset.rel };
    var item = el.closest(".tree-item[data-drop-root]");
    if (item) return { el: item, root: item.dataset.dropRoot, path: item.dataset.dropPath || "" };
    return null;
  }

  function clearTargets() {
    document.querySelectorAll(".drop-target").forEach(function (x) { x.classList.remove("drop-target"); });
  }

  document.addEventListener("dragover", function (e) {
    if (!dragging) return;
    var target = dropTarget(e.target);
    clearTargets();
    if (!target) return;
    var copy = e.ctrlKey || e.altKey;
    if (!copy && target.root === here.root && target.path === here.path) return;  // ya están aquí
    e.preventDefault();
    e.dataTransfer.dropEffect = copy ? "copy" : "move";
    target.el.classList.add("drop-target");
  });
  document.addEventListener("dragleave", function (e) {
    if (dragging && e.target.classList && e.target.classList.contains("drop-target")) e.target.classList.remove("drop-target");
  });
  document.addEventListener("drop", function (e) {
    if (!dragging) return;
    var target = dropTarget(e.target);
    clearTargets();
    if (!target) return;
    e.preventDefault();
    var items = dragging;
    dragging = null;
    submitTransfer(e.ctrlKey || e.altKey ? "copy" : "move", items, target.root, target.path);
  });
})();
