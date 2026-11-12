# Microsoft Entra ID (SSO)

## Implementaciones

| `auth.entra.provider` | Descripción |
|---|---|
| `oauth2` (por defecto) | Authorization Code + PKCE, implementado con la librería estándar de Python. No hace descubrimiento por red: las URLs se calculan a partir del tenant. Solo contacta con Microsoft al canjear el código durante el login. Con `authorize_url`, `token_url` e `issuer` sirve para cualquier proveedor OpenID Connect o nube soberana. |
| `msal` | Librería oficial de Microsoft. Descubre la autoridad por red en cada login. |

Los motivos de esta elección están en el [ADR 0003](../arquitectura/decisiones/0003-oauth2-propio.md). Si el servidor sale a Internet por un proxy, define `HTTPS_PROXY` en el servicio, por ejemplo con `systemctl edit storageweb` y una línea `Environment=HTTPS_PROXY=http://proxy:3128`.

## 1. Registrar la aplicación

1. En **Entra admin center → Identity → Applications → App registrations → New registration**:
   - nombre: `StorageWeb`;
   - tipo de cuenta: *Solo este directorio organizativo*;
   - Redirect URI: plataforma **Web**, `https://files.midominio.com/auth/entra/callback`.
2. En **Certificates & secrets → New client secret**, copia el *Value*. Anota también su fecha de caducidad.
3. En **API permissions**, deja `Microsoft Graph → User.Read`, que viene por defecto.
4. Elige cómo restringir el acceso o asignar roles:
   - **App Roles (recomendado):** en *App roles*, crea `StorageWeb.User` y `StorageWeb.Admin`. Asígnalos en *Enterprise applications → StorageWeb → Users and groups*.
   - **Grupos:** en *Token configuration → Add groups claim → Security groups*, marca la opción *Groups assigned to the application* para no superar el límite de 200 grupos del token.
5. Opcional: en *Enterprise applications → StorageWeb → Properties*, pon *Assignment required* = **Sí**. Así solo pueden entrar los usuarios asignados.

## 2. Configurar StorageWeb

En **Administración → Ajustes → Microsoft Entra ID** o en `config.json`:

```json
"entra": {
  "enabled": true,
  "provider": "oauth2",
  "tenant_id": "<Directory (tenant) ID>",
  "client_id": "<Application (client) ID>",
  "client_secret": "<secreto>",
  "redirect_uri": "https://files.midominio.com/auth/entra/callback",
  "allowed_groups": ["StorageWeb.User", "StorageWeb.Admin"],
  "auto_provision": true,
  "default_role": "user",
  "role_mappings": {"StorageWeb.Admin": "admin"},
  "sync_role_on_login": true
}
```

## 3. Alta de usuarios y roles

| Ajuste | Efecto |
|---|---|
| `auto_provision: true` | El usuario se crea en su primer inicio de sesión. |
| `auto_provision: false` | Solo entran los usuarios que un admin haya dado de alta antes, con origen *Entra ID* y su UPN, desde la web o con `storageweb-admin user-add juan@contoso.com --source entra`. La cuenta se vincula a su identificador de Entra (`oid`) en el primer login. |
| `default_role` | Rol de los usuarios nuevos si no aplica ningún mapeo. |
| `role_mappings` | Grupo (Object ID) o App Role → rol. Si coinciden varios, gana `admin`. |
| `sync_role_on_login` | Con mapeos definidos, el rol se recalcula en cada login: Entra manda. Si está desactivado, el rol solo se asigna al crear el usuario y luego lo gestiona el admin. |
| `allowed_groups` | Si no está vacío, solo entran los miembros de estos grupos o App Roles. |

El nombre de usuario es el UPN (`juan@contoso.com`) y su carpeta personal es `homes/juan@contoso.com`. Los grupos del token se guardan en minúsculas y sirven también para dar acceso a carpetas compartidas.

!!! warning "Cuentas con el mismo nombre"
    Una cuenta de Entra **nunca** se vincula automáticamente con un usuario local o PAM del mismo nombre: el login se rechaza para evitar suplantaciones. Si `strip_domain` está activo, `juan@contoso.com` se convierte en `juan`, lo que facilita estas colisiones.

## Comprobaciones de seguridad del login

- `state` (CSRF), `nonce` y PKCE (S256);
- el flujo caduca a los 10 minutos;
- en el id_token: `aud`, `azp`, `iss`, `exp`, `nbf` (con 5 minutos de tolerancia) y `tid`.

La firma del token no se verifica, como permite OIDC cuando el token se obtiene directamente del endpoint por TLS; ver el [ADR 0004](../arquitectura/decisiones/0004-firma-id-token.md).

## Errores frecuentes

| Mensaje o código | Causa |
|---|---|
| `AADSTS50011` | La Redirect URI no coincide con la registrada (revisa `redirect_uri`, el esquema y la barra final). |
| `AADSTS7000215` / `invalid_client` | `client_secret` incorrecto o caducado. |
| `AADSTS50105` | *Assignment required* activo y el usuario no tiene asignada la aplicación. |
| «Tu cuenta no tiene permiso…» | El usuario no está en `allowed_groups`. Si tiene más de 200 grupos, usa App Roles. |
| «Tu cuenta no está dada de alta…» | `auto_provision` desactivado y el usuario no fue creado antes. |
| `invalid_issuer` en el log | Tenant distinto, o `issuer` mal configurado con endpoints propios. |

En el log del servicio aparece el código exacto (`SSO error: ...`). La auditoría registra `login_failed` con detalle `entra:<código>`.
