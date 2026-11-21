// Común a todas las páginas: marca que hay JavaScript, traducciones (SW.t), modal propio
// (SW.confirm, SW.prompt, SW.alert), confirmaciones de formularios y copiar al portapapeles.
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // Traducciones: el servidor entrega {texto_fuente: traducción} en <script id="i18n-messages">
  var MESSAGES = {};
  try { MESSAGES = JSON.parse(document.getElementById("i18n-messages").textContent); } catch (e) { MESSAGES = {}; }
  function t(message, params) {
    var text = MESSAGES[message] || message;
    return text.replace(/%\((\w+)\)s/g, function (m, key) {
      return params && params[key] !== undefined ? params[key] : m;
    });
  }

  // Modal propio en lugar de confirm/prompt/alert del navegador. Devuelve una promesa:
  //   SW.confirm(texto, {ok, danger, content, wide}) → true/false     SW.prompt(texto, valor) → texto o null
  //   SW.alert(texto) → cuando se cierra                                     SW.show(título, elemento) → al cerrar
  // ``content``: un elemento que va debajo del texto (el texto pasa a ser el título); ``wide``: más ancho.
  // Usa <dialog>: el foco queda dentro, Esc cancela y el fondo no se puede tocar.
  function modal(opts) {
    return new Promise(function (resolve) {
      var dialog = document.createElement("dialog");
      dialog.className = "sw-modal" + (opts.danger ? " is-danger" : "") + (opts.wide ? " is-wide" : "");
      dialog.setAttribute("role", opts.cancel === false ? "alertdialog" : "dialog");
      var form = document.createElement("form");
      form.method = "dialog";
      var message = document.createElement("p");
      message.className = "sw-modal-message" + (opts.content ? " sw-modal-title" : "");
      message.id = "sw-modal-message";
      message.textContent = opts.message;
      dialog.setAttribute("aria-describedby", message.id);
      form.appendChild(message);
      if (opts.content) form.appendChild(opts.content);
      var input = null;
      if (opts.input !== undefined) {
        input = document.createElement("input");
        input.type = "text";
        input.className = "sw-modal-input";
        input.value = opts.input || "";
        input.setAttribute("aria-label", opts.message);
        form.appendChild(input);
      }
      var actions = document.createElement("div");
      actions.className = "sw-modal-actions";
      if (opts.cancel !== false) {
        var cancel = document.createElement("button");
        cancel.value = "cancel";
        cancel.className = "btn btn-ghost";
        cancel.textContent = opts.cancel || t("Cancel");
        actions.appendChild(cancel);
      }
      var ok = document.createElement("button");
      ok.value = "ok";
      ok.className = "btn " + (opts.danger ? "btn-danger-solid" : "btn-primary");
      ok.textContent = opts.ok || t("Accept");
      actions.appendChild(ok);
      form.appendChild(actions);
      dialog.appendChild(form);
      document.body.appendChild(dialog);

      // Se resuelve al pulsar un botón, Enter o Esc (sin depender del evento «close»); una sola vez
      var done = false;
      var finish = function (accepted) {
        if (done) return;
        done = true;
        if (dialog.open) dialog.close();
        dialog.remove();
        if (input) resolve(accepted ? input.value : null);
        else resolve(accepted);
      };
      form.addEventListener("submit", function (e) {
        e.preventDefault();
        finish(e.submitter ? e.submitter.value === "ok" : true);  // Enter en el campo = aceptar
      });
      dialog.addEventListener("cancel", function (e) { e.preventDefault(); finish(false); });  // Esc
      dialog.addEventListener("close", function () { finish(dialog.returnValue === "ok"); });
      dialog.showModal();
      if (input) { input.focus(); input.select(); }
      else if (opts.danger && opts.cancel !== false) { actions.firstChild.focus(); }  // lo destructivo no por defecto
      else ok.focus();
    });
  }

  window.SW = {
    t: t,
    confirm: function (message, opts) {
      return modal({ message: message, ok: opts && opts.ok, danger: opts && opts.danger,
                     content: opts && opts.content, wide: opts && opts.wide });
    },
    prompt: function (message, value) { return modal({ message: message, input: value || "" }); },
    alert: function (message) { return modal({ message: message, cancel: false, ok: t("OK") }); },
    // Un modal solo para mirar: ``title`` arriba, el elemento ``content`` debajo y un botón de cerrar (``opts.ok``:
    // otro texto para él). Para cerrarlo desde fuera: ``content.closest("dialog").close()``
    show: function (title, content, opts) {
      return modal({ message: title, content: content, cancel: false, ok: (opts && opts.ok) || t("Close"), wide: true });
    }
  };

  // Formularios con confirmación (class="js-confirm" data-confirm="…"): el botón de aceptar lleva el
  // texto del botón pulsado («Eliminar», «Revocar»…)
  // (SW.confirmForm, para los que llegan después: las filas que carga el explorador)
  function confirmForm(f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.confirmed === "1") { delete f.dataset.confirmed; return; }
      e.preventDefault();
      var submitter = e.submitter;
      var label = submitter && submitter.textContent.trim();
      if (!label || label.length < 3) label = undefined;  // botones de icono («×»): «Aceptar»
      window.SW.confirm(f.dataset.confirm || t("Are you sure?"), { ok: label, danger: true }).then(function (ok) {
        if (!ok) return;
        f.dataset.confirmed = "1";
        if (f.requestSubmit) f.requestSubmit(submitter && submitter.form === f ? submitter : undefined);
        else f.submit();
      });
    });
  }
  window.SW.confirmForm = confirmForm;
  document.querySelectorAll("form.js-confirm").forEach(confirmForm);

  // Avisos emergentes: cerrar, y los que no son de error se van solos (no mientras el ratón o el foco estén encima)
  document.querySelectorAll(".toast").forEach(function (toast) {
    var timer = null;
    function close() {
      toast.classList.add("is-leaving");
      setTimeout(function () { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 220);
    }
    function schedule() {
      if (toast.classList.contains("toast-error")) return;
      clearTimeout(timer);
      timer = setTimeout(close, 6000);
    }
    var button = toast.querySelector(".toast-close");
    if (button) button.addEventListener("click", close);
    toast.addEventListener("mouseenter", function () { clearTimeout(timer); });
    toast.addEventListener("focusin", function () { clearTimeout(timer); });
    toast.addEventListener("mouseleave", schedule);
    schedule();
  });

  // Barras de porcentaje (espacio usado…): la anchura no puede ir en un style="" (CSP), se pone aquí
  document.querySelectorAll("[data-percent]").forEach(function (bar) {
    var p = Math.max(0, Math.min(100, parseFloat(bar.getAttribute("data-percent")) || 0));
    bar.style.width = p + "%";
  });

  // Menús emergentes (<details class="popover">): se abren hacia el lado donde caben (sin salirse de la pantalla
  // ni crear barras de desplazamiento) y se cierran al pulsar fuera o con Esc
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!(d instanceof HTMLDetailsElement) || !d.classList.contains("popover") || !d.open) return;
    var body = d.querySelector(".popover-body");
    if (!body) return;
    body.classList.add("popover-start");                  // primero, hacia la derecha desde el botón
    if (body.getBoundingClientRect().right > document.documentElement.clientWidth - 8) {
      body.classList.remove("popover-start");             // no cabe: hacia la izquierda
      if (body.getBoundingClientRect().left < 8) body.classList.add("popover-start");
    }
  }, true);                                                // «toggle» no sube: se escucha en la captura
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.popover[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll("details.popover[open]").forEach(function (d) {
      d.removeAttribute("open");
      var summary = d.querySelector("summary");
      if (summary && d.contains(document.activeElement)) summary.focus();
    });
  });

  // Desplegables que envían su formulario al cambiar (p. ej. registros por página)
  document.querySelectorAll("select.js-autosubmit").forEach(function (s) {
    s.addEventListener("change", function () { if (s.form) s.form.submit(); });
  });

  // Copiar al portapapeles
  document.querySelectorAll(".js-copy").forEach(function (b) {
    b.addEventListener("click", function () {
      var src = document.querySelector(b.dataset.copy);
      if (!src || !navigator.clipboard) return;
      navigator.clipboard.writeText(src.value).then(function () { b.textContent = t("Copied"); });
    });
  });
})();
