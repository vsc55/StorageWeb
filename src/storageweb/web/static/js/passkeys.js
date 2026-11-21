/* Passkeys (WebAuthn): la mitad del navegador de las ceremonias. Basado en el de ServiceSentry.

   Todo lo que DECIDE algo está en el servidor (core/mfa/webauthn.py, con sus tests): aquí solo se traduce entre el
   base64url con el que el servidor pone los bytes en JSON y los ArrayBuffer que pide navigator.credentials, y se
   averigua lo único que sabe el navegador: si puede usar passkeys. El challenge nunca se compone aquí: llega del
   servidor, se usa una vez y no se le devuelve para que se fíe de él.

   Formularios (templates/_passkeys.html): <form data-passkey="create|get" data-for="…" data-options="url"
   data-verify="url" hidden>. Nacen ocultos y se enseñan si el navegador puede; si no, el aviso
   [data-passkey-unsupported] de al lado. El servidor contesta {redirect} (y deja el aviso para la página siguiente) o
   {error} (texto ya traducido). */
(function () {
  "use strict";

  var forms = document.querySelectorAll("form[data-passkey]");
  if (!forms.length) return;

  var t = window.SW && SW.t ? SW.t : function (s) { return s; };
  var meta = document.querySelector('meta[name="csrf-token"]');
  var csrf = meta ? meta.getAttribute("content") : "";

  // Tres «no» distintos: navegador antiguo (sin navigator.credentials), página sin contexto seguro (http fuera de
  // localhost: sin PublicKeyCredential) o API a medias. En los tres, el botón no se pinta en vez de fallar luego.
  var supported = !!(window.PublicKeyCredential && navigator.credentials &&
                     typeof navigator.credentials.create === "function" &&
                     typeof navigator.credentials.get === "function");

  function toBytes(text) {
    var s = String(text || "").replace(/-/g, "+").replace(/_/g, "/");
    var raw = atob(s + "===".slice((s.length + 3) % 4));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function toB64u(buffer) {
    var bytes = new Uint8Array(buffer);
    var raw = "";
    for (var i = 0; i < bytes.length; i++) raw += String.fromCharCode(bytes[i]);
    return btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(body || {})
    }).then(function (res) {
      return res.json().catch(function () { return { error: t("Network error.") }; });
    });
  }

  function say(message) {
    if (window.SW && SW.alert) SW.alert(message);
  }

  // {redirect} o {error}: true si hay que seguir (llegaron las opciones de la ceremonia)
  function answered(data) {
    if (data && data.redirect) { window.location.assign(data.redirect); return false; }
    if (!data || data.error || !data.challenge) { say((data && data.error) || t("Network error.")); return false; }
    return true;
  }

  function browserFailed(err) {
    // Cancelar y dejar pasar el tiempo llegan igual, y ninguno es un error: la persona pulsó Esc o se fue
    if (err && (err.name === "NotAllowedError" || err.name === "AbortError")) return;
    if (err && err.name === "InvalidStateError") { say(t("This passkey is already on your account.")); return; }
    say(t("The browser could not use the passkey."));
  }

  function create(form, o) {
    var name = form.querySelector('[name="passkey_name"]');
    return navigator.credentials.create({ publicKey: {
      challenge: toBytes(o.challenge),
      rp: o.rp,
      user: { id: toBytes(o.user.id), name: o.user.name, displayName: o.user.displayName },
      pubKeyCredParams: (o.algorithms || []).map(function (alg) { return { type: "public-key", alg: alg }; }),
      timeout: o.timeout,
      excludeCredentials: (o.exclude || []).map(function (id) { return { type: "public-key", id: toBytes(id) }; }),
      // La attestation no se comprueba (dice de qué fabricante es la llave, y aquí no se pregunta): no se pide
      attestation: "none",
      // Guardada en el dispositivo solo con «entrar sin contraseña» encendido (lo dice el servidor): las llaves de
      // seguridad tienen pocos huecos para eso
      authenticatorSelection: { residentKey: o.residentKey || "discouraged",
                                requireResidentKey: o.residentKey === "required", userVerification: "preferred" }
    } }).then(function (cred) {
      return post(form.dataset.verify, {
        attestation_object: toB64u(cred.response.attestationObject),
        client_data_json: toB64u(cred.response.clientDataJSON),
        name: name ? name.value : ""
      }).then(answered);
    }, browserFailed);
  }

  function get(form, o) {
    return navigator.credentials.get({ publicKey: {
      challenge: toBytes(o.challenge),
      rpId: o.rpId,
      timeout: o.timeout,
      // Lista vacía (entrar sin contraseña): el navegador ofrece las passkeys guardadas para este sitio
      allowCredentials: (o.allow || []).map(function (id) { return { type: "public-key", id: toBytes(id) }; }),
      userVerification: o.userVerification || "preferred"
    } }).then(function (cred) {
      return post(form.dataset.verify, {
        id: toB64u(cred.rawId),
        authenticator_data: toB64u(cred.response.authenticatorData),
        client_data_json: toB64u(cred.response.clientDataJSON),
        signature: toB64u(cred.response.signature),
        // De quién es (solo lo trae una passkey guardada en el dispositivo): el servidor lo compara con la cuenta
        user_handle: cred.response.userHandle ? toB64u(cred.response.userHandle) : ""
      }).then(answered);
    }, browserFailed);
  }

  Array.prototype.forEach.call(forms, function (form) {
    var note = form.nextElementSibling;
    if (!supported) {
      if (note && note.hasAttribute("data-passkey-unsupported")) note.hidden = false;
      return;
    }
    form.hidden = false;
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = form.querySelector('[type="submit"]');
      if (button) button.disabled = true;
      var ceremony = form.dataset.passkey === "create" ? create : get;
      post(form.dataset.options, { "for": form.dataset.for || "" })
        .then(function (o) { return answered(o) ? ceremony(form, o) : null; })
        .catch(function () { say(t("Network error.")); })
        .then(function () { if (button) button.disabled = false; });
    });
  });
})();
