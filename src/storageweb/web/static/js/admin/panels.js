// Vista Paneles (usuarios, grupos, roles): la lista a la izquierda y la ficha del elegido a la derecha.
//
// * Al abrir la página, la lista (que en pantallas grandes se desplaza por su cuenta, admin.css) enseña el elegido
//   aunque esté abajo.
// * Con data-partial en .master-detail (los tres), elegir otro, cambiar de pestaña y los formularios de la ficha y de
//   la lista (guardar, la estrella, borrar) no recargan la página: se piden por detrás y se cambia solo .page,
//   con la dirección al día (Atrás y Adelante también van por aquí), la lista donde estaba y los avisos de siempre.
//   Si la respuesta no es este mismo panel (un error al guardar, otra página), se enseña tal cual, como al navegar.
(function () {
  "use strict";

  function reveal(list) {
    var item = list && list.querySelector(".md-item.active");
    if (!item || list.scrollHeight <= list.clientHeight) return;     // en móvil la lista no se desplaza
    var box = list.getBoundingClientRect();
    var at = item.getBoundingClientRect();
    if (at.top < box.top || at.bottom > box.bottom) {
      list.scrollTop += at.top - box.top - (list.clientHeight - at.height) / 2;
    }
  }

  document.querySelectorAll(".md-list").forEach(reveal);

  var panel = document.querySelector(".page > .master-detail[data-partial]");
  if (!panel || !window.fetch || !window.DOMParser || !history.pushState) return;
  var here = location.pathname;          // la ruta del panel: solo esta se carga sin recargar
  var busy = null;

  function samePanel(url) {
    return url.origin === location.origin && url.pathname === here;
  }

  // La página entera, como si se hubiera navegado (errores al guardar, otra página)
  function showWhole(html, url) {
    if (url) history.replaceState(null, "", url);
    document.open();
    document.write(html);
    document.close();
  }

  function swap(doc, focusDetail) {
    var page = document.querySelector(".page");
    var fresh = doc.querySelector(".page");
    if (!page || !fresh || !fresh.querySelector(".master-detail[data-partial]")) return false;
    var oldList = page.querySelector(".md-list");
    var scroll = oldList ? oldList.scrollTop : 0;
    page.replaceWith(fresh);
    document.title = doc.title;
    var list = fresh.querySelector(".md-list");
    if (list) {
      list.scrollTop = scroll;
      reveal(list);
    }
    window.SW.wire(fresh);                                      // confirmaciones, barras de cuota… (common.js)
    document.dispatchEvent(new CustomEvent("sw:content", { detail: fresh }));   // el selector de rutas y demás
    // Los avisos que trae la respuesta («Cambios guardados»…), abajo a la derecha como siempre
    var toasts = doc.querySelector(".toasts");
    if (toasts) {
      var box = window.SW.toastBox();
      Array.prototype.slice.call(toasts.children).forEach(function (toast) {
        box.appendChild(toast);
        window.SW.toast(toast);
      });
    }
    if (focusDetail) {
      var title = fresh.querySelector(".md-detail .md-title");
      if (title) {
        title.setAttribute("tabindex", "-1");
        title.focus({ preventScroll: true });
      }
    }
    return true;
  }

  function load(url, options, push, focusDetail) {
    if (busy) busy.abort();
    busy = new AbortController();
    var detail = document.querySelector(".md-detail");
    if (detail) detail.classList.add("is-loading");
    var request = Object.assign({ signal: busy.signal }, options || {});
    return window.SW.page(url, request).then(function (response) {
      return response.text().then(function (html) {
        busy = null;
        var final = new URL(response.url);
        var doc = new DOMParser().parseFromString(html, "text/html");
        if (response.ok && samePanel(final) && swap(doc, focusDetail)) {
          if (push) history.pushState(null, "", final.href);
          else history.replaceState(null, "", final.href);
        } else {
          showWhole(html, final.href);
        }
      });
    }).catch(function (error) {
      if (error && error.name === "AbortError") return;
      // Sin conexión o un fallo de red: como antes, navegando
      if (!options || !options.method || options.method === "GET") location.href = url;
      else window.SW.alert(window.SW.t("Could not connect to the server."));
    }).finally(function () {
      var now = document.querySelector(".md-detail");
      if (now) now.classList.remove("is-loading");
    });
  }

  // Enlaces de la lista y de las pestañas (y cualquier otro a este mismo panel dentro de él)
  document.addEventListener("click", function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest && e.target.closest(".master-detail[data-partial] a[href]");
    if (!link || link.target || link.hasAttribute("download")) return;
    var url = new URL(link.href, location.href);
    if (!samePanel(url)) return;
    e.preventDefault();
    load(url.href, null, true, !!link.closest(".md-list"));
  });

  // Formularios POST del panel (guardar, la estrella, borrar…): después de su confirmación (common.js la pide antes
  // y vuelve a enviar el formulario con requestSubmit, que vuelve a pasar por aquí)
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var form = e.target;
    var submitter = e.submitter;
    var inPanel = form.closest(".master-detail[data-partial]") ||
                  (submitter && submitter.closest(".master-detail[data-partial]"));
    if (!inPanel || (form.method || "").toLowerCase() !== "post") return;
    var action = new URL(form.action, location.href);
    if (action.origin !== location.origin) return;
    e.preventDefault();
    var data = new FormData(form);
    if (submitter && submitter.name) data.append(submitter.name, submitter.value);
    load(action.href, { method: "POST", body: data }, true, false);
  });

  window.addEventListener("popstate", function () {
    if (location.pathname === here) load(location.href, null, false, false);
  });
})();
