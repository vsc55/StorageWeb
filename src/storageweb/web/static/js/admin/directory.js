// Buscar grupos por nombre en el directorio de un método de inicio de sesión (Entra ID u otro con directorio)
// y rellenar su identificador (Object ID…). Sirve en:
// - el alta de grupo: input[data-directory-input]; la URL de búsqueda es la del origen elegido
//   (input[name=source]:checked[data-directory-search]) y el grupo elegido rellena lo que esté vacío: nombre,
//   descripción e identificador (el que propone el servidor a partir del nombre);
// - los ajustes (asociaciones de roles, grupos permitidos…): input[data-group-search="<url>"]. Con
//   data-group-append="<campo>", el grupo elegido se añade a ese campo (lista separada por comas) y la casilla
//   se vacía. Funciona también en las filas que se añaden después (escucha en todo el documento).
// El nombre del grupo se escribe en el <small class="group-name"> que sigue a la casilla.
(function () {
  "use strict";
  if (!window.fetch) return;
  var t = window.SW && window.SW.t ? window.SW.t : function (s) { return s; };
  var GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  var known = {};   // id (en minúsculas) → grupo ({name, description, suggested_name}) de las búsquedas hechas
  var timer = null;

  function isLookup(el) {
    return el instanceof HTMLInputElement &&
      (el.hasAttribute("data-directory-input") || el.hasAttribute("data-group-search"));
  }

  function searchUrl(input) {
    if (input.hasAttribute("data-group-search")) return input.getAttribute("data-group-search");
    var checked = document.querySelector("input[name=source]:checked");
    return checked ? checked.getAttribute("data-directory-search") : null;
  }

  function nameSlot(input) {
    var next = input.nextElementSibling;
    return next && next.classList.contains("group-name") ? next : null;
  }

  // El valor es un grupo encontrado: rellenar nombre o añadirlo a la lista. true si lo era.
  function fill(field, value) {
    var el = document.querySelector("input[name=" + field + "]");
    if (el && !el.value && value) el.value = value;
  }

  function picked(input) {
    var id = input.value.trim().toLowerCase();
    var group = known[id];
    if (!group) return false;
    var name = group.name;
    var slot = nameSlot(input);
    var appendTo = input.getAttribute("data-group-append");
    if (appendTo && input.form) {
      var target = input.form.querySelector("[name='" + appendTo + "']");
      if (target) {
        var items = target.value.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
        if (items.map(function (s) { return s.toLowerCase(); }).indexOf(id) < 0) items.push(id);
        target.value = items.join(", ");
        target.dispatchEvent(new Event("input", { bubbles: true }));  // para la barra de guardar
      }
      input.value = "";
      if (slot) slot.textContent = t("Added: %(name)s").replace("%(name)s", name);
      return true;
    }
    if (input.hasAttribute("data-directory-input")) {
      fill("label", name);
      fill("description", group.description);
      fill("name", group.suggested_name);
    }
    if (slot) slot.textContent = name;
    return true;
  }

  document.addEventListener("input", function (e) {
    var input = e.target;
    if (!isLookup(input)) return;
    if (picked(input)) return;
    var slot = nameSlot(input);
    if (slot && !input.hasAttribute("data-group-append")) slot.textContent = "";  // ya no es el grupo de antes
    clearTimeout(timer);
    var url = searchUrl(input);
    var text = input.value.trim();
    // Sin directorio, menos de 2 letras o ya es un identificador (GUID): no se busca
    if (!url || text.length < 2 || GUID.test(text)) return;
    timer = setTimeout(function () {
      fetch(url + "?q=" + encodeURIComponent(text), {
        headers: { "Accept": "application/json" }, credentials: "same-origin"
      }).then(function (r) { return r.json(); }).then(function (data) {
        var list = document.getElementById(input.getAttribute("list"));
        if (!list) return;
        list.innerHTML = "";
        (data.groups || []).forEach(function (g) {
          known[String(g.id).toLowerCase()] = g;
          var opt = document.createElement("option");
          opt.value = g.id;
          opt.label = g.name;
          opt.textContent = g.name;
          list.appendChild(opt);
        });
      }).catch(function () {});
    }, 300);
  });
})();
