// Personas → Usuarios: «Cambiar contraseña» de otra cuenta en un modal, sin salir de la lista o de los paneles.
// Los enlaces llevan data-password-modal: el formulario se pide al servidor (?modal=1, el mismo que la página) y se
// envía pidiendo JSON; si la contraseña no vale, el error sale dentro y el modal sigue abierto. Sin JavaScript (o si
// no se puede pedir el formulario), el enlace lleva a la página de siempre.
(function () {
  "use strict";

  var t = window.SW.t;

  // En la fase de captura: antes que admin/panels.js, que cargaría el enlace en el panel
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest && e.target.closest("a[data-password-modal]");
    if (!link) return;
    e.preventDefault();
    e.stopPropagation();
    var url = new URL(link.href, location.href);
    url.searchParams.set("modal", "1");
    window.SW.page(url.href)
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) { open(html, link); })
      .catch(function () { location.href = link.href; });
  }, true);

  function open(html, link) {
    var dialog = window.SW.el("dialog", "sw-modal is-wide password-modal");
    var tpl = document.createElement("template");
    tpl.innerHTML = html;
    dialog.appendChild(tpl.content);
    var form = dialog.querySelector("form");
    if (!form) { location.href = link.href; return; }
    var error = dialog.querySelector(".js-password-error");
    var submit = form.querySelector("[type=submit]");
    var title = dialog.querySelector(".sw-modal-title");
    if (title) { title.id = "password-modal-title"; dialog.setAttribute("aria-labelledby", title.id); }
    document.body.appendChild(dialog);
    window.SW.wire(dialog);

    function close() {
      if (dialog.open) dialog.close();
      dialog.remove();
      link.focus();
    }
    function fail(message) {
      error.textContent = message;
      error.hidden = false;
      submit.disabled = false;
      form.querySelector("input[type=password]").focus();
    }
    dialog.addEventListener("cancel", function (e) { e.preventDefault(); close(); });   // Esc
    dialog.querySelector("[data-close]").addEventListener("click", close);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      submit.disabled = true;
      error.hidden = true;
      window.SW.fetch(form.action, { method: "POST", body: new FormData(form) })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (res) {
          if (!res.ok) { fail(res.data.error || t("Network error.")); return; }
          close();
          window.SW.notify(res.data.message, "info");
        })
        .catch(function () { fail(t("Network error.")); });
    });
    dialog.showModal();
    form.querySelector("input[type=password]").focus();
  }
})();
