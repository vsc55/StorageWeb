// Listas como etiquetas (data-list, p. ej. las extensiones del visor en Sistema → Vista previa). Solo en las
// páginas que las tienen ({% block page_scripts %}), detrás de admin/forms.js.
//
// Cada elemento es una etiqueta. Se escribe y con Intro (o coma) se añade; la × la quita; con el campo vacío,
// Retroceso quita la última; lo escrito filtra. El campo de texto real sigue en el formulario (oculto): es lo que
// se envía y lo que ven los borradores, Descartar y Restablecer de forms.js. Con forms.js se habla por dos
// propiedades del campo: swRenderTags() (repintar tras recuperar un borrador o Descartar) y swConfirmReset(valor)
// (antes de Restablecer, un modal con qué se añade y qué se quita).
(function () {
  "use strict";
  var t = window.SW.t;

  var LIST_ITEM = /^[a-z0-9_+-]{1,16}$/;
  // Los elementos de una lista escrita (separados por comas o espacios), en minúsculas y sin repetir; ``keepDot``:
  // sin quitar el punto del principio (las extensiones se guardan sin él; la comparación del diálogo, tal cual)
  function listItems(text, keepDot) {
    return String(text || "").split(/[\s,]+/).map(function (x) {
      x = x.trim().toLowerCase();
      return keepDot ? x : x.replace(/^\./, "");
    }).filter(function (x, i, all) { return x && all.indexOf(x) === i; });
  }

  function fieldName(source) {
    var label = source.closest("label");
    var row = label && label.querySelector(".label-row");
    return row && row.firstChild ? row.firstChild.textContent.trim() : "";
  }

  // ------------------------------------------------------------------ las etiquetas

  document.querySelectorAll("[data-list]").forEach(function (source) {
    var locked = source.disabled;
    var box = document.createElement("div");
    box.className = "tags" + (locked ? " is-locked" : "");
    var list = document.createElement("div");
    list.className = "tags-list";
    list.setAttribute("role", "list");
    box.appendChild(list);
    var input = null;
    if (!locked) {
      input = document.createElement("input");
      input.type = "text";
      input.className = "tags-input mono";
      input.setAttribute("autocomplete", "off");
      input.setAttribute("spellcheck", "false");
      input.placeholder = source.getAttribute("placeholder") || t("Type to filter, Enter to add");
      var name = fieldName(source);
      if (name) input.setAttribute("aria-label", name);
      box.appendChild(input);
    }
    source.classList.add("tags-source");
    source.parentNode.insertBefore(box, source.nextSibling);

    var setItems = function (items) {
      source.value = items.join(", ");
      source.dispatchEvent(new Event("input", { bubbles: true }));  // «sin guardar», borradores
      render();
    };
    var render = function () {
      var items = listItems(source.value);
      list.textContent = "";
      items.forEach(function (item) {
        var tag = document.createElement("span");
        tag.className = "tag";
        tag.setAttribute("role", "listitem");
        var text = document.createElement("span");
        text.textContent = item;
        tag.appendChild(text);
        if (!locked) {
          var remove = document.createElement("button");
          remove.type = "button";
          remove.className = "tag-remove";
          remove.textContent = "×";
          remove.setAttribute("aria-label", t("Remove %(name)s", { name: item }));
          remove.addEventListener("click", function () {
            setItems(listItems(source.value).filter(function (x) { return x !== item; }));
            if (input) input.focus();
          });
          tag.appendChild(remove);
        }
        list.appendChild(tag);
      });
      box.classList.toggle("is-empty", !items.length);
      filter();
    };
    // Lo que se escribe filtra las etiquetas: se ve al momento si ya está (y Intro la añade si no)
    var hint = document.createElement("span");
    hint.className = "tags-hint muted small";
    hint.setAttribute("aria-live", "polite");
    hint.hidden = true;
    box.appendChild(hint);
    var filter = function () {
      var q = input ? input.value.trim().toLowerCase().replace(/^\./, "") : "";
      var shown = 0;
      var exact = false;
      Array.prototype.forEach.call(list.children, function (tag) {
        var text = tag.firstChild.textContent;
        tag.hidden = Boolean(q) && text.indexOf(q) < 0;
        tag.classList.toggle("is-match", Boolean(q) && text === q);
        if (!tag.hidden) shown++;
        if (q && text === q) exact = true;
      });
      hint.hidden = !q || (shown > 0 && !exact);
      hint.textContent = exact ? t("It is already in the list.") : t("None matches: press Enter to add it.");
    };
    source.swRenderTags = render;
    source.swConfirmReset = function (value) { return confirmReset(source, value); };
    render();
    if (!input) return;

    var add = function () {
      var typed = listItems(input.value);
      if (!typed.length) { input.value = ""; return; }
      var bad = typed.filter(function (x) { return !LIST_ITEM.test(x); });
      if (bad.length) {
        input.setCustomValidity(t("%(value)s is not a file extension", { value: bad[0] }));
        input.reportValidity();
        return;
      }
      input.setCustomValidity("");
      var items = listItems(source.value);
      typed.forEach(function (x) { if (items.indexOf(x) < 0) items.push(x); });
      input.value = "";
      setItems(items);
    };
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }  // Intro no envía el formulario
      else if (e.key === "Escape" && input.value) { e.preventDefault(); input.value = ""; filter(); }  // borra el filtro
      else if (e.key === "Backspace" && !input.value) {
        var items = listItems(source.value);
        if (items.length) { items.pop(); setItems(items); }
      }
    });
    input.addEventListener("input", function () {
      input.setCustomValidity("");
      if (/[\s,]/.test(input.value)) add();   // pegar «md, txt log» o escribir un espacio: se añaden
      else filter();
    });
    box.addEventListener("click", function (e) { if (e.target === box || e.target === list) input.focus(); });
  });

  // ------------------------------------------------------------------ Restablecer: qué cambia

  // Antes de volver a la lista predeterminada, qué se añade y qué se quita. Promesa: true = restablecer
  function confirmReset(source, value) {
    var listOf = function (text) { return listItems(text, true); };
    var now = listOf(source.value);
    var wanted = listOf(value);
    var added = wanted.filter(function (x) { return now.indexOf(x) < 0; });
    var removed = now.filter(function (x) { return wanted.indexOf(x) < 0; });
    return window.SW.confirm(t("Back to the default list?"), {
      ok: t("Back to the default"), wide: true, content: listDiff(fieldName(source), added, removed)
    });
  }

  // Qué cambia al volver a una lista predeterminada: cifras, lo que se quita y lo que se añade (en una zona con
  // desplazamiento y buscador, para que el diálogo quepa aunque sean cientos)
  function listDiff(name, added, removed) {
    var make = window.SW.el;
    var box = make("div", "list-diff");
    box.appendChild(make("p", "muted small list-diff-note",
      (name ? name + ". " : "") + t("The change is applied when you save the page.")));
    if (!added.length && !removed.length) {
      box.appendChild(make("p", "", t("Nothing changes: it already has the default values.")));
      return box;
    }
    var counts = make("div", "list-diff-counts");
    if (added.length) counts.appendChild(make("span", "list-diff-count is-added", "+" + added.length));
    if (removed.length) counts.appendChild(make("span", "list-diff-count is-removed", "−" + removed.length));
    box.appendChild(counts);
    var section = function (title, items, cls, searchable) {
      var part = make("section", "list-diff-part");
      var head = make("div", "list-diff-head");
      head.appendChild(make("h3", "list-diff-title " + cls, title + " (" + items.length + ")"));
      var chips = make("div", "list-diff-chips" + (items.length > 24 ? " is-long" : ""));
      items.forEach(function (x) { chips.appendChild(make("span", "list-diff-chip " + cls, x)); });
      if (searchable && items.length > 24) {
        var search = make("input", "list-diff-search");
        search.type = "search";
        search.placeholder = t("Search");
        search.setAttribute("aria-label", t("Search"));
        search.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });  // no acepta
        search.addEventListener("input", function () {
          var q = search.value.trim().toLowerCase();
          Array.prototype.forEach.call(chips.children, function (c) { c.hidden = q && c.textContent.indexOf(q) < 0; });
        });
        head.appendChild(search);
      }
      part.appendChild(head);
      part.appendChild(chips);
      return part;
    };
    if (removed.length) box.appendChild(section(t("It removes"), removed, "is-removed", true));
    if (added.length) box.appendChild(section(t("It adds"), added, "is-added", true));
    return box;
  }
})();
