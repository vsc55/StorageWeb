// Explorador: «Compartir enlace» (barra de acciones y panel de detalle, un elemento). Abre una ventana para elegir qué
// se puede hacer con el enlace (ver y descargar, o buzón para subir si es una carpeta), cuánto dura, una contraseña
// opcional, un límite de descargas y un mensaje; lo crea (links.create, JSON) y enseña la dirección para copiarla.
// Lo que se puede elegir lo dice el servidor en #share-config (files._share_config).
(function () {
  "use strict";

  var files = window.SW && window.SW.files;
  var node = document.getElementById("share-config");
  if (!files || !node) return;
  var config = JSON.parse(node.textContent);
  var t = window.SW.t;

  function field(labelText, control, hint) {
    var label = document.createElement("label");
    label.textContent = labelText;
    label.appendChild(control);
    if (hint) {
      var small = document.createElement("small");
      small.className = "muted";
      small.textContent = hint;
      label.appendChild(small);
    }
    return label;
  }

  function option(select, value, text, selected) {
    var o = document.createElement("option");
    o.value = value;
    o.textContent = text;
    o.selected = !!selected;
    select.appendChild(o);
  }

  function daysText(d) {
    if (!d) return t("Never");
    return d === 1 ? t("After 1 day") : t("After %(num)s days", { num: d });
  }

  function open(row) {
    var dir = files.isDir(row);
    var panel = document.createElement("div");
    panel.className = "share-form form-grid";

    var mode = document.createElement("select");
    mode.name = "mode";
    if (config.download) option(mode, "download", t("View and download"), true);
    if (dir && config.upload) option(mode, "upload", t("Upload only (drop box)"), !config.download);
    if (!mode.options.length) return;

    var days = document.createElement("select");
    days.name = "days";
    config.days.forEach(function (d) { option(days, String(d), daysText(d), d === config.default_days); });

    // Un campo de texto que se ve con puntos: con type=password el navegador ofrecería guardarla como suya
    var password = document.createElement("input");
    password.type = "text";
    password.name = "password";
    password.className = "is-masked";
    password.autocomplete = "off";
    password.spellcheck = false;
    password.minLength = config.password_min;
    password.setAttribute("data-lpignore", "true");
    password.setAttribute("data-1p-ignore", "");
    password.setAttribute("data-bwignore", "");

    var limit = document.createElement("input");
    limit.type = "number";
    limit.name = "max_downloads";
    limit.min = "1";
    limit.placeholder = t("No limit");

    var note = document.createElement("input");
    note.type = "text";
    note.name = "note";
    note.maxLength = 200;

    var limitField = field(t("At most this many downloads (optional)"), limit);
    panel.appendChild(field(t("What they can do"), mode));
    panel.appendChild(field(t("Expires"), days));
    panel.appendChild(field(config.require_password ? t("Password") : t("Password (optional)"), password,
                            t("At least %(num)s characters. Give it to them by another way.", { num: config.password_min })));
    panel.appendChild(limitField);
    var noteField = field(t("Message for whoever opens it (optional)"), note);
    noteField.className = "span2";
    panel.appendChild(noteField);
    mode.addEventListener("change", function () { limitField.hidden = mode.value === "upload"; });
    limitField.hidden = mode.value === "upload";

    var error = document.createElement("p");
    error.className = "span2 text-danger small";
    error.hidden = true;
    var create = document.createElement("button");
    create.type = "button";
    create.className = "btn btn-primary span2-start";
    create.textContent = t("Create link");
    panel.appendChild(error);
    panel.appendChild(create);

    create.addEventListener("click", function () {
      error.hidden = true;
      create.disabled = true;
      var body = new URLSearchParams({ root: config.root, path: row.dataset.rel, mode: mode.value, days: days.value,
                                       password: password.value, max_downloads: mode.value === "upload" ? "" : limit.value,
                                       note: note.value });
      fetch(config.url, {
        method: "POST", body: body, credentials: "same-origin",
        headers: { "X-CSRF-Token": files.csrf, "Accept": "application/json" }
      }).then(function (r) {
        return r.json().then(function (data) { return { ok: r.ok, data: data }; });
      }).then(function (res) {
        if (!res.ok) throw new Error(res.data.error || t("Network error."));
        done(panel, res.data);
      }).catch(function (e) {
        error.textContent = e.message || t("Network error.");
        error.hidden = false;
        create.disabled = false;
      });
    });

    window.SW.show(t("Share «%(name)s»", { name: row.dataset.name }), panel);
  }

  function done(panel, data) {
    panel.innerHTML = "";
    panel.className = "share-done stack";
    var p = document.createElement("p");
    p.textContent = t("Anyone with this link can open it:");
    var row = document.createElement("div");
    row.className = "copy-row";
    var input = document.createElement("input");
    input.type = "text";
    input.readOnly = true;
    input.className = "mono";
    input.value = data.url;
    var copy = document.createElement("button");
    copy.type = "button";
    copy.className = "btn btn-primary";
    copy.textContent = t("Copy");
    copy.addEventListener("click", function () {
      input.select();
      var ok = function () { copy.textContent = t("Copied"); };
      if (navigator.clipboard) navigator.clipboard.writeText(input.value).then(ok, function () {});
      else if (document.execCommand("copy")) ok();
    });
    row.appendChild(input);
    row.appendChild(copy);
    var more = document.createElement("p");
    more.className = "muted small";
    more.textContent = data.expires ? t("It expires %(when)s.", { when: data.expires }) + " " : "";
    var mine = document.createElement("a");
    mine.href = data.mine;
    mine.textContent = t("My share links");
    more.appendChild(mine);
    panel.appendChild(p);
    panel.appendChild(row);
    panel.appendChild(more);
    input.focus();
    input.select();
  }

  files.actions.share = function (sel) { if (sel.length === 1) open(sel[0]); };
})();
