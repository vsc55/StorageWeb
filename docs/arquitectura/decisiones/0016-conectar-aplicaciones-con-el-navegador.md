# 0016. Conectar aplicaciones iniciando sesión en el navegador (PKCE)

- **Estado:** Aceptada
- **Fecha:** 2026-11-14

## Contexto

La extensión de VS Code (y en el futuro otros clientes) entra por WebDAV con un **token de API**. Crearlo en *Mi perfil* y pegarlo en el editor funciona, pero es incómodo y no aprovecha el inicio de sesión de la web, que con Entra ID (y `auth.entra.auto_login`) no pide nada en un equipo unido. El cliente no debe ver nunca la contraseña, y la extensión no debe saber nada de Entra ID ni de los demás métodos de inicio de sesión.

## Decisión

El flujo de **OAuth 2.0 con PKCE** (RFC 7636) para aplicaciones nativas, implementado en StorageWeb (`core/connect.py`, `web/views/connect.py`):

1. La aplicación genera un `verifier` secreto y abre en el navegador `/connect/<aplicación>?redirect_uri=…&challenge=SHA256(verifier)&state=…&device=…`.
2. El usuario inicia sesión como siempre (cualquier método, también Entra ID) y la página le pregunta si permite la conexión, con qué alcance y caducidad. Es un formulario con CSRF.
3. Al aceptar, StorageWeb apunta un **código de un solo uso** (5 minutos, en memoria del proceso) y devuelve el navegador a la aplicación (`vscode://storageweb.storageweb-sync/auth?code=…&state=…`).
4. La aplicación canjea el código **con el verifier** en `POST /connect/token` y recibe un token de API normal, con nombre «Visual Studio Code (*equipo*)», que se ve y se revoca en *Mi perfil*.

Las direcciones de vuelta están fijadas por aplicación (`CLIENTS`): nunca una web cualquiera. El token se crea al canjear: si no se canjea, no hay token. Escribir usuario y token a mano sigue disponible; la extensión pregunta cuál usar.

## Alternativas consideradas

- **Solo tokens pegados a mano:** funciona, pero obliga a copiar secretos y no usa el inicio de sesión que ya existe.
- **Devolver el token directamente en la vuelta:** cualquier programa que capture `vscode://…` (otra extensión, un manejador de protocolo registrado) se lo quedaría. Con PKCE, sin el verifier el código no sirve.
- **Que la extensión hable con Entra ID (MSAL / WAM):** ataría el cliente a un método concreto y obligaría al servidor a validar tokens de Entra con su firma. Queda en la hoja de ruta (punto 16) para entrar sin pasar por el navegador.
- **Device code (el usuario escribe un código en la web):** más pasos para el usuario. La vuelta por URI de VS Code ya existe y es directa.

## Consecuencias

- Iniciar sesión desde VS Code es abrir el navegador y pulsar *Permitir*, también con Microsoft.
- Los códigos pendientes viven en memoria: con varios procesos detrás de un balanceador, el canje tiene que llegar al mismo proceso. Hoy StorageWeb es un solo proceso (Waitress).
- `POST /connect/token` no usa la sesión ni CSRF. Un canje fallido gasta el código y cuenta para el bloqueo de IPs (`bad_token`).
- No funciona en VS Code en el navegador (vscode.dev) ni en conexiones remotas, donde la vuelta no es `vscode://`.
