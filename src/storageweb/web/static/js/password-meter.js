// El medidor de las contraseñas nuevas (macro new_password_fields de _forms.html: Mi perfil → Seguridad y el modal de
// Cambiar contraseña de otra cuenta). Mientras se escribe pregunta al servidor (profile.password_check) la fortaleza
// (0–4) y cada regla del sistema que se aplicará al guardar, y lo pinta: barra, etiqueta y la lista con ✓/✗. «Generar»
// pide una aleatoria que las cumple (profile.password_generate), la pone en los dos campos y la enseña para poder
// copiarla. También dice si la repetida coincide. Sin JavaScript queda el texto de las reglas.
//
// Lo de pintar (SW.paintStrength, SW.paintChecks) lo usa también el probador de Seguridad → Contraseñas.
(function () {
  "use strict";

  var t = window.SW.t;

  // La barra y la etiqueta (macro strength_bar) dentro de ``el`` (que lleva la clase pw-strength): ``data`` con score
  // (0–4) y label; sin data, vacía
  window.SW.paintStrength = function (el, data) {
    var bar = el.querySelector(".pw-meter-bar span");
    var label = el.querySelector(".pw-meter-label");
    for (var i = 0; i <= 4; i++) el.classList.remove("is-s" + i);
    if (!data) { bar.style.width = "0"; label.textContent = ""; return; }
    el.classList.add("is-s" + data.score);
    bar.style.width = ((data.score + 1) * 20) + "%";
    label.textContent = data.label;
  };

  // Cada regla ({label, ok: true/false/null, message}) con ✓, ✗ o el reloj (sin comprobar), y el porqué si no se cumple
  window.SW.paintChecks = function (list, checks) {
    list.innerHTML = "";
    (checks || []).forEach(function (c) {
      var li = window.SW.el("li", c.ok === true ? "is-ok" : c.ok === false ? "is-bad" : "is-unknown");
      li.appendChild(window.SW.icon(c.ok === true ? "check-circle" : c.ok === false ? "x" : "clock", "icon-sm"));
      li.appendChild(window.SW.el("span", "", c.label));
      if (c.ok !== true && c.message) li.appendChild(window.SW.el("small", "muted", c.message));
      list.appendChild(li);
    });
  };

  function wireMeter(meter) {
    if (meter.dataset.wired) return;
    meter.dataset.wired = "1";
    var form = meter.closest("form");
    if (!form) return;
    var input = form.querySelector("[data-password-new]");
    var repeat = form.querySelector("[data-password-repeat]");
    var match = form.querySelector(".pw-match");
    var rulesText = form.querySelector(".js-rules-text");
    var strength = meter.querySelector(".pw-strength");
    var list = meter.querySelector(".pw-meter-rules");
    // El alta de una cuenta: la regla del nombre de usuario, con el que se está escribiendo
    var nameInput = meter.dataset.usernameFrom ? form.querySelector(meter.dataset.usernameFrom) : null;
    var show = meter.querySelector(".js-pw-show");
    var copy = meter.querySelector(".js-pw-copy");
    if (!input || !repeat) return;
    meter.hidden = false;
    if (rulesText) rulesText.hidden = true;            // lo dice la lista, regla por regla

    var timer = null;
    var seq = 0;
    var visible = false;

    function body(fields) {
      var data = new FormData();
      Object.keys(fields).forEach(function (key) { data.append(key, fields[key]); });
      if (meter.dataset.user) data.append("user", meter.dataset.user);
      if (nameInput) data.append("username", nameInput.value);
      return data;
    }

    function paint(data) {
      window.SW.paintStrength(strength, data);
      window.SW.paintChecks(list, data.checks);
    }

    function clear() {
      window.SW.paintStrength(strength, null);
      list.innerHTML = "";
    }

    function check() {
      var value = input.value;
      var mine = ++seq;
      if (!value) { clear(); return; }
      window.SW.fetch(meter.dataset.check, { method: "POST", body: body({ password: value }) })
        .then(window.SW.json)
        .then(function (data) { if (mine === seq) paint(data); })
        .catch(function () { /* sin medidor: al guardar se comprueba igual */ });
    }

    function compare() {
      if (!repeat.value) { match.hidden = true; return; }
      var same = repeat.value === input.value;
      match.hidden = false;
      match.textContent = same ? t("They match.") : t("They do not match yet.");
      match.className = "pw-match " + (same ? "text-ok" : "text-danger");
    }

    function setVisible(on) {
      visible = on;
      input.type = repeat.type = on ? "text" : "password";
      show.textContent = on ? t("Hide") : t("Show");
      show.setAttribute("aria-pressed", on ? "true" : "false");
    }

    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(check, 250);
      compare();
      copy.hidden = !visible || !input.value;
    });
    repeat.addEventListener("input", compare);
    if (nameInput) {
      nameInput.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(check, 400); });
    }
    show.addEventListener("click", function () {
      setVisible(!visible);
      copy.hidden = !visible || !input.value;
    });
    copy.addEventListener("click", function () {
      window.SW.copy(input.value).then(function (ok) { if (ok) window.SW.notify(t("Copied"), "info"); });
    });
    meter.querySelector(".js-pw-generate").addEventListener("click", function () {
      window.SW.fetch(meter.dataset.generate, { method: "POST", body: body({}) })
        .then(window.SW.json)
        .then(function (data) {
          input.value = repeat.value = data.password;
          setVisible(true);                            // para verla y copiarla antes de guardar
          copy.hidden = false;
          check();
          compare();
          input.focus();
          input.select();
        })
        .catch(function () { window.SW.alert(t("No password could be generated with the current rules.")); });
    });
  }

  window.SW.onWire(function (root) {
    root.querySelectorAll(".pw-meter").forEach(wireMeter);
  });
})();
