// Seguridad → Vulnerabilidades: la comprobación con su barra de progreso. «Comprobar ahora» la empieza
// en el servidor (un hilo: sigue aunque se cierre la página) y abre un modal con la barra; «Seguir en segundo plano»
// lo cierra y la comprobación sigue; «Ver el progreso» lo vuelve a abrir. Mientras dura, el botón no se puede pulsar
// (tampoco al volver a la página: el servidor dice si hay una en marcha). Al acabar, la página se recarga con el
// resultado. Sin JavaScript, el formulario la empieza igual y se vuelve a la página.
(function () {
  "use strict";

  var form = document.getElementById("advisories-form");
  if (!form) return;
  var t = window.SW.t;
  var startBtn = document.getElementById("advisories-start");
  var showBtn = document.getElementById("advisories-show");
  var running = document.getElementById("advisories-running");
  var statusUrl = form.dataset.status;

  var panel = null;        // el contenido del modal mientras está abierto
  var bar = null;
  var text = null;
  var polling = null;

  var PHASES = {
    versions: "Newest versions: %(done)s of %(total)s",
    vulnerabilities: "Asking the vulnerability database…",
    details: "Severity of each vulnerability: %(done)s of %(total)s"
  };

  function setBusy(busy) {
    startBtn.disabled = busy;
    showBtn.hidden = !busy;
    running.hidden = !busy;
  }

  function paint(job) {
    if (!panel) return;
    bar.value = job.percent || 0;
    bar.textContent = (job.percent || 0) + " %";
    var phase = PHASES[job.phase];
    text.textContent = phase ? t(phase, { done: job.done || 0, total: job.total || 0 }) : t("Starting…");
  }

  function openPanel() {
    if (panel) return;
    panel = document.createElement("div");
    panel.className = "progress-panel";
    bar = document.createElement("progress");
    bar.className = "sw-progress";
    bar.max = 100;
    bar.value = 0;
    text = document.createElement("p");
    text.className = "muted small";
    text.setAttribute("aria-live", "polite");
    var note = document.createElement("p");
    note.className = "muted small";
    note.textContent = t("It goes on in the server even if you close this or leave the page.");
    panel.appendChild(bar);
    panel.appendChild(text);
    panel.appendChild(note);
    window.SW.show(t("Checking the libraries"), panel, { ok: t("Continue in the background") }).then(function () {
      panel = null;        // cerrado: la comprobación sigue
    });
    refresh();
  }

  function finished() {
    clearInterval(polling);
    polling = null;
    if (panel) panel.closest("dialog").close();
    window.location.reload();      // con el resultado (y la tabla) que acaba de guardar el servidor
  }

  function refresh() {
    return window.SW.getJSON(statusUrl)
      .then(function (job) {
        if (!job.running) { finished(); return; }
        setBusy(true);
        paint(job);
      })
      .catch(function () { /* un fallo de red puntual: el siguiente intento lo dirá */ });
  }

  function follow() {
    setBusy(true);
    if (!polling) polling = setInterval(refresh, 1000);
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (startBtn.disabled) return;
    startBtn.disabled = true;
    window.SW.fetch(form.action, { method: "POST" }).then(function (r) {
      // 202: empezada; 409: ya había una en marcha (otra pestaña u otro administrador): se sigue esa
      if (r.status !== 202 && r.status !== 409) throw new Error(r.status);
      follow();
      openPanel();
    }).catch(function () {
      startBtn.disabled = false;
      window.SW.alert(t("The check could not be started."));
    });
  });

  showBtn.addEventListener("click", openPanel);

  // Al llegar a la página con una en marcha (empezada antes, o por otro administrador)
  if (form.hasAttribute("data-running")) follow();
})();
