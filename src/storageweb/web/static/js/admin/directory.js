// Alta de grupo: buscar grupos por nombre en el directorio del origen elegido (Entra ID u otro método
// con directorio) y rellenar su identificador. Cada origen con directorio lleva data-directory-search.
(function () {
  "use strict";
  var extInput = document.querySelector("input[data-directory-input]");
  if (!extInput || !window.fetch) return;
  var list = document.getElementById(extInput.getAttribute("list"));
  var labelInput = document.querySelector("input[name=label]");
  var timer = null;
  var lastGroups = [];
  var searchUrl = function () {
    var checked = document.querySelector("input[name=source]:checked");
    return checked ? checked.getAttribute("data-directory-search") : null;
  };
  extInput.addEventListener("input", function () {
    clearTimeout(timer);
    var found = lastGroups.find(function (g) { return g.id === extInput.value; });
    if (found) {
      if (labelInput && !labelInput.value) labelInput.value = found.name;
      return;
    }
    var url = searchUrl();
    // Sin directorio, menos de 2 letras o ya es un identificador (GUID): no se busca
    if (!url || extInput.value.length < 2 || /^[0-9a-f-]{36}$/i.test(extInput.value)) return;
    timer = setTimeout(function () {
      fetch(url + "?q=" + encodeURIComponent(extInput.value), {
        headers: { "Accept": "application/json" }, credentials: "same-origin"
      }).then(function (r) { return r.json(); }).then(function (data) {
        lastGroups = data.groups || [];
        list.innerHTML = "";
        lastGroups.forEach(function (g) {
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
