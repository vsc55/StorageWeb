# 0004. No verificar la firma del id_token

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Verificar la firma de un JWT obliga a descargar las claves públicas del proveedor (JWKS), cachearlas y rotarlas, y a usar una librería criptográfica. Eso añade llamadas de red y dependencias nativas, justo lo que el [ADR 0003](0003-oauth2-propio.md) quiere evitar.

OpenID Connect Core 1.0, §3.1.3.7, permite usar TLS en lugar de la validación de firma cuando el id_token se recibe **directamente del endpoint de token** en una comunicación con autenticación del cliente.

## Decisión

El proveedor `oauth2` no verifica la firma del id_token. Se valida todo lo demás:

- `iss` (el tenant o el `issuer` configurado);
- `aud` (y `azp` si hay varias audiencias);
- `exp` y `nbf`, con 5 minutos de tolerancia;
- `nonce`, ligado a la sesión, y `tid`.

El token se obtiene siempre por HTTPS del endpoint de token, autenticándose con `client_secret` y `code_verifier`. Nunca se acepta un id_token que llegue desde el navegador.

## Alternativas consideradas

- **Verificar la firma con JWKS:** más defensa en profundidad, pero con red y dependencias adicionales. Si el canal TLS con el endpoint de token estuviera comprometido, el atacante también podría servir un JWKS falso.
- **Usar MSAL**, que sí valida: disponible como `provider = "msal"` para quien lo prefiera.

## Consecuencias

- El modelo depende de la integridad de TLS hacia `login.microsoftonline.com` (o el `token_url`). No se debe desactivar la verificación de certificados ni usar proxies que la rompan.
- Si en el futuro se aceptan id_tokens por otros canales (por ejemplo, el flujo implícito), habrá que verificar la firma.
