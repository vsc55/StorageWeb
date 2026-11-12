# 0003. Proveedor OAuth2/OIDC propio por defecto; MSAL opcional

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

La primera implementación del SSO usaba MSAL, la librería oficial de Microsoft. MSAL descubre por red los metadatos de la autoridad cada vez que se crea la aplicación cliente. Eso añade una dependencia de red, problemática en servidores con salida a Internet restringida, y además arrastra `requests`, `PyJWT` y `cryptography`.

## Decisión

- **`oauth2` por defecto:** proveedor propio que implementa Authorization Code + PKCE (S256) con la librería estándar (`urllib`).
- **Sin descubrimiento:** los endpoints se calculan a partir del tenant, o se configuran (`authorize_url`, `token_url`, `issuer`) para nubes soberanas u otros proveedores OIDC.
- **Única llamada de red:** el canje del código por el token. Respeta `HTTPS_PROXY`.
- **MSAL sigue disponible:** `provider = "msal"`, con la misma interfaz `SSOProvider` (`begin` / `complete`).

## Alternativas consideradas

- **Solo MSAL:** dependencia de red y de librerías nativas (`cryptography`) sin necesidad.
- **Authlib u otra librería OIDC genérica:** sería otra dependencia para un flujo que son unas 150 líneas bien probadas.

## Consecuencias

- Funciona detrás de proxies y en entornos restringidos, y no tiene dependencias nativas.
- La validación del id_token es responsabilidad nuestra. Está cubierta por tests unitarios y de integración, incluidos los casos de `aud`, `iss`, `exp`, `nbf`, `nonce` y `state`.
- Ver también el [ADR 0004](0004-firma-id-token.md).
