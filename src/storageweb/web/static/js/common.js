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

  // El token CSRF de la página (<meta name="csrf-token">) y fetch a la propia aplicación: con la sesión, el token en
  // la cabecera (el servidor solo contesta a ciertas peticiones del JavaScript de la propia página) y pidiendo JSON.
  // ``options.headers`` se suman a esas (y las cambian: p. ej. otro Accept)
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  window.SW.csrf = csrfMeta ? csrfMeta.getAttribute("content") : "";
  // La sesión se cerró con la página abierta (cuenta desactivada, sesión cerrada por un admin, contraseña cambiada,
  // caducada): el servidor contesta 401 con «signed_out» (guards.needs_sign_in). Se avisa una sola vez y se va a la
  // entrada, volviendo luego a esta página; quien hizo la petición no recibe nada (la promesa se queda sin resolver)
  // para que no enseñe además un «Error de red» ni pegue la página de entrada en la suya.
  var signingOut = false;
  function watchSession(resp) {
    if (resp.status !== 401 || resp.headers.get("X-StorageWeb-Reason") !== "signed_out") return resp;
    if (!signingOut) {
      signingOut = true;
      resp.json().catch(function () { return {}; }).then(function (data) {
        var target = (data.login || "/login") + "?next=" + encodeURIComponent(location.pathname + location.search);
        window.SW.alert(data.error || t("Your session has ended. Sign in again.")).then(function () {
          location.href = target;
        });
      });
    }
    return new Promise(function () {});
  }
  window.SW.fetch = function (url, options) {
    options = options || {};
    var headers = Object.assign({ "Accept": "application/json", "X-CSRF-Token": window.SW.csrf }, options.headers || {});
    return fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers: headers })).then(watchSession);
  };
  // Un trozo de página (HTML) que pide el JavaScript (paneles, cargar más, resultados de importar…): con la sesión y
  // la marca X-Requested-With, para que una sesión cerrada sea el aviso de arriba y no la página de entrada
  window.SW.page = function (url, options) {
    options = options || {};
    var headers = Object.assign({ "Accept": "text/html", "X-Requested-With": "fetch" }, options.headers || {});
    return fetch(url, Object.assign({ credentials: "same-origin" }, options, { headers: headers })).then(watchSession);
  };

  // Un elemento con su clase y su texto: SW.el("li", "muted", t("Nothing"))
  window.SW.el = function (tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };

  // localStorage puede no estar disponible (modo privado, políticas…): SW.store(clave) lee, SW.store(clave, valor)
  // guarda y SW.store(clave, null) borra; nunca lanza
  window.SW.store = function (key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value);
    } catch (e) { return null; }
    return undefined;
  };

  // Copiar al portapapeles → promesa (true si se copió). Sin contexto seguro (http fuera de localhost) no hay
  // portapapeles asíncrono, y con él el navegador puede negarlo (permiso, foco): en los dos casos, la forma antigua
  window.SW.copy = function (text) {
    var fallback = function () {
      var area = document.createElement("textarea");
      area.value = text;
      area.className = "sr-only";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { /* no se pudo */ }
      area.remove();
      return ok;
    };
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(function () { return true; }, fallback);
    }
    return Promise.resolve(fallback());
  };

  // Un <option> nuevo al final de un <select> o un <datalist>
  window.SW.option = function (select, value, text, selected) {
    var o = document.createElement("option");
    o.value = value;
    if (text !== undefined && text !== null) o.textContent = text;
    o.selected = !!selected;
    select.appendChild(o);
    return o;
  };

  // Un campo oculto por valor (``name`` repetido), quitando antes los que hubiera: la selección de varios archivos
  window.SW.setHidden = function (form, name, values) {
    form.querySelectorAll('input[name="' + name + '"]').forEach(function (i) { i.remove(); });
    values.forEach(function (value) {
      var i = document.createElement("input");
      i.type = "hidden"; i.name = name; i.value = value;
      form.appendChild(i);
    });
  };

  // Enviar un formulario pasando por sus «submit» (confirmaciones, validación); en navegadores viejos, directo
  window.SW.submit = function (form, submitter) {
    if (form.requestSubmit) form.requestSubmit(submitter); else form.submit();
  };

  // Avisar al salir de la página si hay cambios sin guardar (``isDirty()`` → true)
  window.SW.guardUnload = function (isDirty) {
    window.addEventListener("beforeunload", function (e) {
      if (!isDirty()) return;
      e.preventDefault();
      e.returnValue = "";   // el navegador muestra su propio aviso
    });
  };

  // La respuesta JSON de una petición, o un error si no fue bien (para .catch): fetch(...).then(SW.json)
  window.SW.json = function (r) {
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  };
  window.SW.getJSON = function (url, options) { return window.SW.fetch(url, options).then(window.SW.json); };

  // Un icono del sprite de la página (_icons.html) como elemento: SW.icon("folder", "icon-sm")
  window.SW.icon = function (name, cls) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "icon" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
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

  // Avisos emergentes: cerrar, y los que no son de error se van solos (no mientras el ratón o el foco estén encima).
  // SW.toast(el): para los que llegan después (admin/panels.js, al cambiar de ficha sin recargar)
  function wireToast(toast) {
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
  }
  window.SW.toast = wireToast;
  document.querySelectorAll(".toast").forEach(wireToast);

  // La caja de los avisos (abajo a la derecha); se crea si la página no trae ninguno
  window.SW.toastBox = function () {
    var box = document.querySelector(".toasts");
    if (!box) {
      box = window.SW.el("div", "toasts");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    return box;
  };
  // Un aviso desde JavaScript, como los del servidor: SW.notify(texto, "info" | "error")
  window.SW.notify = function (text, kind) {
    kind = kind || "info";
    var toast = window.SW.el("div", "toast toast-" + kind);
    toast.setAttribute("role", kind === "error" ? "alert" : "status");
    toast.appendChild(window.SW.el("span", "toast-text", text));
    var close = window.SW.el("button", "toast-close", "\u00d7");
    close.type = "button";
    close.setAttribute("aria-label", t("Close"));
    close.title = t("Close");
    toast.appendChild(close);
    window.SW.toastBox().appendChild(toast);
    wireToast(toast);
  };


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

  // Lo que se engancha a cada elemento de la página: al cargarla y, con SW.wire(raíz), al contenido que llega después
  // sin recargar (admin/panels.js, que además avisa con el evento «sw:content» para los scripts de cada página)
  function wire(root) {
    // Formularios con confirmación
    root.querySelectorAll("form.js-confirm").forEach(confirmForm);
    // Barras de porcentaje (espacio usado…): la anchura no puede ir en un style="" (CSP), se pone aquí
    root.querySelectorAll("[data-percent]").forEach(function (bar) {
      var p = Math.max(0, Math.min(100, parseFloat(bar.getAttribute("data-percent")) || 0));
      bar.style.width = p + "%";
    });
    // Desplegables que envían su formulario al cambiar (p. ej. registros por página)
    root.querySelectorAll("select.js-autosubmit").forEach(function (s) {
      s.addEventListener("change", function () {
        if (s.form) window.SW.submit(s.form);
      });
    });
    // Copiar al portapapeles
    root.querySelectorAll(".js-copy").forEach(function (b) {
      b.addEventListener("click", function () {
        var src = document.querySelector(b.dataset.copy);
        if (!src) return;
        window.SW.copy(src.value).then(function (ok) { if (ok) b.textContent = t("Copied"); });
      });
    });
    wirers.forEach(function (fn) { fn(root); });
  }
  // Lo que un script de una página quiere preparar también en el contenido que llega después (un modal, los
  // paneles): SW.onWire(fn) lo hace ya con la página y luego en cada SW.wire(raíz)
  var wirers = [];
  window.SW.onWire = function (fn) {
    wirers.push(fn);
    fn(document);
  };
  window.SW.wire = wire;
  wire(document);
})();
