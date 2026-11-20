# Flujos

## Inicio de sesión con usuario y contraseña

```mermaid
flowchart TD
    A[POST /login] --> B{¿Bloqueado por IP o usuario?}
    B -- sí --> X[login_blocked]
    B -- no --> C{¿Usuario existe?}
    C -- local --> D[Verificar hash scrypt]
    C -- entra --> F[Rechazar: solo SSO]
    C -- no existe o pam --> E{¿PAM activo?}
    E -- sí --> G[pam.authenticate<br/>grupos del SO]
    G --> H[Crear o actualizar usuario pam<br/>rol según admin_groups]
    D --> OK[Sesión + login]
    H --> OK
    E -- no --> KO[login_failed<br/>tiempo constante]
    F --> KO
```

Cuando el usuario no existe o no tiene contraseña, se calcula igualmente un hash ficticio. Así el tiempo de respuesta no revela qué usuarios existen.

## Inicio de sesión con Entra ID (`oauth2`)

```mermaid
sequenceDiagram
    participant N as Navegador
    participant S as StorageWeb
    participant E as Entra ID
    N->>S: GET /auth/entra/login
    S->>S: state, nonce, code_verifier (PKCE) → sesión
    S-->>N: 302 a /authorize?client_id…&code_challenge…
    N->>E: Usuario se autentica (MFA, etc.)
    E-->>N: 302 a /auth/entra/callback?code&state
    N->>S: GET /auth/entra/callback
    S->>S: Comprobar state y antigüedad (≤ 10 min)
    S->>E: POST /token (code, code_verifier, client_secret)
    E-->>S: id_token
    S->>S: Validar aud, azp, iss, exp, nbf, nonce, tid
    S->>S: allowed_groups → buscar por oid → vincular, crear o rechazar → rol
    S-->>N: 302 a la página pedida, con sesión
```

Reglas del alta (`core.accounts.login_with_claims`):

1. Si existe un usuario con ese `oid`, entra con esa cuenta.
2. Si no, pero existe un usuario de Entra con ese nombre y sin `oid` (dado de alta por un admin), se le vincula ese `oid`.
3. Si existe un usuario local o PAM con ese nombre, se **rechaza** el login.
4. Si no existe ninguno, se crea el usuario cuando `auto_provision` está activo; si no, se rechaza.
5. El rol se calcula con `resolve_role`, a partir de `role_mappings`, `default_role` y `sync_role_on_login`.

## Subida por partes

```mermaid
sequenceDiagram
    participant N as Navegador (app.js)
    participant S as API /api/uploads
    participant D as Disco
    N->>S: POST {root, path, name, size, folders?}
    S->>S: Permiso, nombre, tamaño máx., espacio libre
    S->>D: crear .sw-upload-<id>.part vacío
    S-->>N: 201 {id, chunk_size}
    loop cada parte (≤ 32 MB)
        N->>S: PUT /<id>?offset=N (binario)
        S->>S: ¿offset == tamaño del .part? (si no → 409 {received})
        S->>D: añadir al .part
        S-->>N: {received}
    end
    N->>S: POST /<id>/complete
    S->>D: rename atómico al nombre final (sin sobrescribir)
    S-->>N: {name}
```

- **Reanudación:** el progreso real es el tamaño del `.part` en disco. Tras un corte, el navegador consulta `GET /<id>` y sigue desde `received`. El id se guarda en `localStorage` para continuar incluso tras recargar la página.
- **Reintentos:** ante errores de red o 5xx, el navegador reintenta con espera exponencial, hasta 8 veces.
- **Permisos:** se vuelven a comprobar **en cada parte**. Si un admin quita el permiso a mitad de la subida, se corta.
- **Limpieza:** las subidas sin actividad durante 24 h se eliminan al iniciar otra.

## Ajustes web

```mermaid
flowchart LR
    F[Formulario de una sección<br/>/admin/settings/auth] --> M[merge sobre los<br/>ajustes efectivos]
    M --> V{normalize<br/>predeterminados < borrador<br/>< config.json < entorno}
    V -- error --> R[400 con el borrador y<br/>el error junto al campo]
    V -- ok --> D[diff con los predeterminados<br/>sin los campos bloqueados]
    D --> P[settings.put<br/>revision += 1]
    P --> C[Cada petición:<br/>¿revision cambió? → recalcular]
```

Los campos que fijan `config.json` o el entorno no se guardan: la web los muestra bloqueados. La revisión se lee en cada petición, una consulta trivial. Por eso todos los hilos aplican los cambios al momento, sin reiniciar y sin mensajes entre procesos.
