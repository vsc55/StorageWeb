# Almacenamiento: disco, montajes y ubicaciones externas

Cada carpeta (las personales y cada carpeta compartida) guarda sus archivos en un sitio:

| Dónde | Cómo se configura | Cuándo usarlo |
|---|---|---|
| **Disco del servidor** | Una ruta (`/srv/storageweb/shared/contabilidad`) | Lo normal |
| **Montaje** (NFS, SMB/CIFS, rclone, SSHFS…) | El sistema monta el recurso y StorageWeb usa su ruta, como si fuera el disco | Cuando ya hay un NAS o un servidor de ficheros y se puede montar en el servidor |
| **S3** (Amazon S3, MinIO, Wasabi, Backblaze B2, Cloudflare R2…) | Una **ubicación** de tipo S3 | Almacenamiento de objetos, sin montar nada |
| **SMB** (Windows, Samba, NAS) | Una **ubicación** de tipo SMB | Un recurso compartido de red sin montarlo (contenedores sin privilegios, Windows) |
| **SFTP** (SSH) | Una **ubicación** de tipo SFTP | Un servidor Linux, un NAS o un hosting con acceso SSH |
| **WebDAV** (Nextcloud, ownCloud, SharePoint, NAS) | Una **ubicación** de tipo WebDAV | Una nube privada o un NAS que ya publica WebDAV |
| **FTP / FTPS** | Una **ubicación** de tipo FTP | Equipos y hostings que solo ofrecen FTP (mejor con TLS) |
| **Azure Blob Storage** | Una **ubicación** de tipo Azure | Organizaciones en Azure (encaja con Entra ID) |

Se pueden mezclar: unas carpetas en el disco, otras en un bucket y las personales en el NAS.

!!! tip "¿Y Google Drive, OneDrive o Dropbox?"
    Móntalos con [rclone](https://rclone.org/) (ver más abajo). Google Cloud Storage funciona como **S3** en su modo compatible (claves HMAC, `endpoint_url` `https://storage.googleapis.com`).

## Carpetas del servidor permitidas

![Sistema → Carpetas del servidor: la lista y las carpetas del disco en uso, cada una con si queda dentro](../img/admin/carpetas-servidor.webp)

En *Sistema → Carpetas del servidor* (`storage.allowed_folders`) se dice en qué carpetas del disco del servidor puede
haber carpetas compartidas y personales, una ruta absoluta por línea (por ejemplo `/srv/storageweb`). Vacío, como
viene de serie, vale cualquiera. Con una lista:

- No se puede guardar una carpeta compartida en el disco, la plantilla de las carpetas personales ni la carpeta
  personal propia de una persona (web y `storageweb-admin user-add/user-set --home`) fuera de ellas.
- Una que ya estaba fuera deja de abrirse («no disponible») hasta que se mueva o se añada su carpeta. La página
  enseña antes de guardar cuáles quedarían fuera.
- El botón *Examinar* solo lista lo que hay dentro de ellas.
- Se compara la ruta real: `..` y los enlaces simbólicos que salen de ellas cuentan como fuera.
- El fichero de la auditoría (`audit.file`, *Seguridad → Auditoría*) también tiene que estar dentro de ellas: el
  servidor añade líneas a ese fichero. Aunque no haya lista, nunca puede estar en la carpeta de datos ni ser el
  `config.json`, y una ruta de red (`\\equipo\recurso`) solo vale si está dentro de una carpeta permitida.

**Rutas de red**: una carpeta compartida o personal en el disco con una ruta de red (`\\nas\datos`, `//nas/datos`)
solo se acepta si está dentro de una carpeta permitida, **aunque no haya lista**: usarla es que el servidor se
conecte a ese equipo con la cuenta del servicio (en Windows, entregándole su hash NTLM). Para un NAS, mejor una
[ubicación SMB](#smb); si de verdad hay que usar la ruta, añádela a la lista.

Las ubicaciones (S3, SMB…) no son el disco del servidor y no se miran. Para que la lista no se pueda ampliar desde
la web, ponla en el `config.json` o en la variable `STORAGEWEB_STORAGE__ALLOWED_FOLDERS` (en JSON si alguna ruta tiene espacios:
`["/srv/storageweb", "/mnt/nas datos"]`): la página la muestra bloqueada.

## Montajes

Es la opción más sencilla y la que mejor rinde: StorageWeb no sabe que la carpeta es remota. El usuario del servicio (`storageweb`) debe poder leer y escribir en el punto de montaje.

=== "NFS"

    ```bash
    # /etc/fstab
    nas.empresa.local:/export/ficheros  /srv/storageweb/shared/nas  nfs  defaults,_netdev  0 0
    ```

=== "SMB / CIFS"

    ```bash
    # /etc/fstab (credenciales en un fichero con permisos 600)
    //nas.empresa.local/ficheros  /srv/storageweb/shared/nas  cifs  credentials=/etc/storageweb/nas.cred,uid=storageweb,gid=storageweb,file_mode=0660,dir_mode=0770,_netdev  0 0
    ```

=== "rclone"

    ```bash
    rclone mount drive:StorageWeb /srv/storageweb/shared/drive \
      --vfs-cache-mode writes --uid $(id -u storageweb) --gid $(id -g storageweb) --allow-other --daemon
    ```

=== "Docker"

    ```yaml
    # compose.yaml: un volumen NFS como carpeta compartida
    services:
      storageweb:
        volumes:
          - storageweb-data:/data
          - nas:/data/files/shared/nas
    volumes:
      nas:
        driver: local
        driver_opts: {type: nfs, o: "addr=nas.empresa.local,rw,nfsvers=4", device: ":/export/ficheros"}
    ```

Después, en *Acceso → Carpetas compartidas*, crea la carpeta con la ruta del montaje. Si el montaje falla, la carpeta aparece como que no existe (aviso en el Resumen) o, con `storage.create_shares`, se crearía vacía en el disco local: **monta antes de arrancar el servicio** (`_netdev`, `x-systemd.automount` o `After=remote-fs.target`).

## Ubicaciones externas

Una **ubicación** es una conexión con nombre (`storage.locations`). Se gestionan en *Sistema → Almacenamiento externo*:

```mermaid
flowchart LR
    subgraph SW [StorageWeb]
        H["Carpetas personales<br/>homes/{username}"]
        P[Proyectos]
        C[Contabilidad]
        M[Marketing]
    end
    H --> NAS[("Ubicación «nas»<br/>SMB")]
    P --> DISCO[("Disco del servidor<br/>o un montaje")]
    C --> S3[("Ubicación «s3»<br/>S3, MinIO…")]
    M --> DISCO
```

1. **Nueva ubicación** del tipo que sea (S3, SMB, SFTP, WebDAV, FTP, Azure), con sus datos y credenciales.
2. **Guardar y probar la conexión**: comprueba que se puede listar la raíz.
3. En *Acceso → Carpetas compartidas*, elige la ubicación en **Dónde están los archivos** y pon la **ruta dentro de ella** (`contabilidad`, `proyectos/2026`; vacía = su raíz).
4. Para las carpetas personales: *Acceso → Carpetas personales → Dónde están las carpetas personales*, con una plantilla relativa como `homes/{username}`.

![Sistema → Almacenamiento externo con una ubicación SMB](../img/admin/ubicaciones.webp)

Requisitos: las bibliotecas no se instalan por defecto con `pip`.

```bash
pip install 'storageweb[s3]'        # boto3
pip install 'storageweb[smb]'       # smbprotocol
pip install 'storageweb[sftp]'      # paramiko
pip install 'storageweb[azure]'     # azure-storage-blob
pip install 'storageweb[s3,smb,sftp,azure]'
```

FTP/FTPS y WebDAV no necesitan nada: usan la biblioteca estándar de Python. La imagen Docker ya incluye todas. Sin la que haga falta, la carpeta muestra el error con el comando que falta y las demás siguen funcionando.

La lista completa de opciones de cada tipo, con sus valores por defecto, está en la [referencia de configuración](../referencia/configuracion.md#tipos-de-ubicacion-storagelocationstype).

### S3

| Campo | |
|---|---|
| `bucket` | Bucket (obligatorio) |
| `prefix` | Carpeta dentro del bucket donde va todo (vacía = el bucket entero) |
| `region` | Región (`eu-west-1`); vacía = la del entorno |
| `endpoint_url` | Solo para servicios que no son Amazon S3: `https://minio.empresa.local:9000` |
| `path_style` | Direcciones `endpoint/bucket` en vez de `bucket.endpoint` (MinIO suele necesitarlo) |
| `access_key`, `secret_key` | Credenciales. Vacías = las del entorno del servidor (`AWS_ACCESS_KEY_ID`, `~/.aws/credentials`, rol IAM) |

- Las carpetas son prefijos de clave. Al crear una carpeta vacía se guarda un objeto marcador `carpeta/`.
- **Renombrar o borrar una carpeta** copia o borra sus objetos uno a uno: con muchos archivos tarda.
- Permisos mínimos de la clave sobre el bucket: `s3:ListBucket`, `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` (y `s3:AbortMultipartUpload` para las subidas grandes).

```json
{"storage": {"locations": [
  {"name": "minio", "label": "MinIO", "type": "s3", "bucket": "ficheros", "prefix": "storageweb",
   "endpoint_url": "https://minio.empresa.local:9000", "path_style": true,
   "access_key": "storageweb", "secret_key": "…"}
]}}
```

### SMB

| Campo | |
|---|---|
| `server`, `port` | Servidor y puerto (445) |
| `share` | Recurso compartido (`ficheros` en `\\nas\ficheros`) |
| `path` | Carpeta dentro del recurso (vacía = el recurso entero) |
| `username`, `password` | Cuenta con permiso de lectura y escritura (`EMPRESA\storageweb`) |
| `encrypt` | Cifrar el tráfico (SMB 3); actívalo salvo que el servidor no lo admita |

```json
{"storage": {"locations": [
  {"name": "nas", "label": "NAS de la oficina", "type": "smb", "server": "nas.empresa.local",
   "share": "ficheros", "path": "storageweb", "username": "EMPRESA\\storageweb", "password": "…"}
]}}
```

### SFTP

| Campo | |
|---|---|
| `host`, `port` | Servidor y puerto SSH (22) |
| `path` | Carpeta del servidor: absoluta (`/srv/datos`) o relativa a la del usuario (vacía = esa carpeta) |
| `host_key` | Clave del servidor: la línea de `ssh-keyscan servidor` o la huella `SHA256:…` (`ssh-keygen -lf`). **Vacía = se acepta cualquiera**: cómodo para probar, pero no protege de un servidor suplantado |
| `username` | Usuario |
| `password` | Contraseña o, con clave privada, su frase de paso (si tiene) |
| `private_key` | Clave privada (OpenSSH o PEM; Ed25519, ECDSA o RSA). Se pega en el campo de varias líneas |

```bash
ssh-keyscan -t ed25519 files.empresa.local     # el valor de host_key
```

```json
{"storage": {"locations": [
  {"name": "srv", "label": "Servidor de ficheros", "type": "sftp", "host": "files.empresa.local",
   "path": "/srv/storageweb", "host_key": "ssh-ed25519 AAAAC3Nza…", "username": "storageweb",
   "private_key": "-----BEGIN OPENSSH PRIVATE KEY-----\n…\n-----END OPENSSH PRIVATE KEY-----"}
]}}
```

Una conexión SSH por ubicación, con un canal por hilo; si se cae, se reabre sola en la siguiente operación.

### WebDAV

| Campo | |
|---|---|
| `url` | Dirección WebDAV. Nextcloud y ownCloud: `https://servidor/remote.php/dav/files/USUARIO/`; Synology: `https://nas:5006/`; SharePoint: la de la biblioteca |
| `path` | Carpeta dentro de esa dirección (vacía = su raíz) |
| `verify_tls` | Comprobar el certificado (desactívalo solo con un certificado propio del NAS) |
| `username`, `password` | Usuario y contraseña. En Nextcloud y ownCloud, mejor una **contraseña de aplicación** (*Configuración → Seguridad*) |

Las descargas piden por rangos (`Range`); si el servidor no los admite, funcionan igual pero reanudar descarga desde el principio.

### FTP / FTPS

| Campo | |
|---|---|
| `host`, `port` | Servidor y puerto (21) |
| `path` | Carpeta del servidor: absoluta (`/datos`) o relativa a la del usuario |
| `tls` | FTPS explícito (`AUTH TLS`): **activado por defecto**. Sin él, la contraseña y los archivos viajan sin cifrar |
| `verify_tls` | Comprobar el certificado (desactívalo solo con un certificado propio) |
| `username`, `password` | Usuario y contraseña (usuario vacío = anónimo) |

- Modo pasivo. Cada operación abre su conexión (FTP no admite varias a la vez), así que es más lento que los demás tipos.
- Lista con `MLSD`; con servidores antiguos sin `MLSD`, usa `NLST` y pregunta por cada nombre (más lento todavía).
- Las descargas empiezan donde haga falta con `REST` (reanudar, vídeo).

### Azure Blob Storage

| Campo | |
|---|---|
| `account`, `container` | Cuenta de almacenamiento y contenedor |
| `prefix` | Carpeta dentro del contenedor (vacía = el contenedor entero) |
| `endpoint` | Solo para Azurite o nubes soberanas (vacío = `https://CUENTA.blob.core.windows.net`) |
| `account_key` o `sas_token` | Clave de la cuenta, o un token SAS del contenedor con lectura, escritura, borrado y lista |

Como en S3, las carpetas son prefijos (una carpeta vacía es un blob `carpeta/`) y **renombrar copia y borra** blob a blob, pasando por el servidor de StorageWeb.

### Cómo funcionan las subidas y descargas

- **Subidas por partes:** las partes se reciben en `<data_dir>/uploads/` y, al completarse, el archivo se envía a la ubicación. Esa carpeta necesita espacio para los archivos que se estén subiendo a la vez; el límite de espacio se comprueba ahí.
- **Descargas:** se leen de la ubicación mientras se envían, con soporte de `Range` (reanudar descargas, vídeo).
- **Fallos:** si la ubicación no responde o rechaza las credenciales, solo fallan sus carpetas, con el motivo. *Sistema → Almacenamiento externo → Probar la conexión* da el detalle.

### Secretos y bloqueo

- Los secretos (`secret_key`, `password`, `private_key`, `account_key`, `sas_token`) se guardan en la base de datos de StorageWeb (o en `config.json` si los pones ahí) y nunca se vuelven a mostrar. Si dejas el campo vacío al editar, se conserva el guardado. `check-config` y *Sistema → Información* los ocultan.
- Las ubicaciones de `config.json` o de `STORAGEWEB_STORAGE__LOCATIONS` (JSON) se ven en la página con su origen y de solo lectura; junto a ellas se pueden crear otras desde la web, que se guardan en la base de datos. Si un nombre está en los dos sitios, manda el de `config.json`. Lo mismo con las carpetas compartidas (`storage.shares`) y la cuota de cada grupo (`storage.group_quotas`).
- El nombre de una ubicación no cambia una vez creada (las carpetas lo usan), y no se puede quitar mientras alguna carpeta la use. Quitarla no borra ningún archivo.

## Ocultar archivos para todos

En *Sistema → Archivos y explorador*, **Ocultos para todos** (`storage.hidden`, se aplica a **todas** las carpetas, también a las compartidas): patrones, uno por línea, como los de `.gitignore`. Lo que coincide **no existe para nadie**: no se lista, no se puede abrir ni descargar, y no se puede crear, subir ni renombrar con ese nombre. Vale para la web, la unidad de red (WebDAV) y la API. Los archivos que ya estaban **siguen en el disco**: se ven en cuanto se quita el patrón.

```text
Thumbs.db          # ese nombre en cualquier carpeta (sin distinguir mayúsculas)
desktop.ini
.DS_Store
*.tmp              # por extensión
.git/              # solo carpetas con ese nombre, con todo lo de dentro
/privado           # solo en la raíz de cada carpeta (personal o compartida)
docs/borradores/*.bak
```

Se aplican a la ruta dentro de cada carpeta de StorageWeb (la personal o cada compartida). No se admiten excepciones (`!`), ni patrones que lo ocultarían todo (`*`).

!!! warning "No es un control de acceso"
    Sirve para **no mostrar** lo que estorba (basura del sistema, carpetas técnicas), no para proteger datos: para que alguien no vea algo, usa los permisos de las carpetas. La lista de patrones no se envía nunca a los clientes. Pero, si alguien pide una ruta concreta que está oculta, la respuesta de WebDAV lo indica (`X-StorageWeb-Hidden: 1`), para que la extensión de VS Code no borre ese archivo del equipo creyendo que se borró en el servidor.

`storage.show_hidden` es otra cosa: solo decide si **la web** muestra los archivos que empiezan por punto. La unidad de red los muestra siempre.

## Cuotas

Las cuotas **impiden escribir lo que no quepa** (`storage.quota_enforce`, activado por defecto): no se puede subir, copiar ni mover a una carpeta lo que la deje por encima de su cuota. La web lo explica en cada archivo rechazado, la unidad de red y la API responden `507 Insufficient Storage` con el motivo, y la extensión de VS Code para y lo avisa. Desactivado, las cuotas solo avisan. En los dos casos se ven en el explorador (barra en el panel de la carpeta y un aviso encima de la lista a partir del 90 %, `storage.quota_warn_percent`, y al superarla), en *Mi perfil* y en la administración.

```mermaid
flowchart TD
    W["Subir, copiar o mover a una carpeta<br/>(web, API o unidad de red)"] --> Q{"¿Tiene cuota y<br/>quota_enforce está activo?"}
    Q -- No --> OK[Se escribe]
    Q -- Sí --> C{"¿Usado + lo que entra − lo que se libera<br/>cabe en la cuota?"}
    C -- Sí --> OK
    C -- No --> X["Se rechaza: aviso en la web,<br/>507 en la unidad de red y la API"]
    OK --> R[Se suma al uso guardado]
```

- **Carpetas personales:** cuota por defecto en *Acceso → Cuotas* (`storage.home_quota_mb`, en MB; `0` = sin cuota).
    - **Por grupo:** en la ficha de cada grupo (*Personas → Grupos*), la cuota de la carpeta personal de sus miembros (`storage.group_quotas`). Si alguien está en varios grupos con cuota se aplica la mayor (`0` = sin cuota gana).
    - **Por usuario:** en su ficha (*Personas → Usuarios*), y manda sobre la de sus grupos: vacío = la de sus grupos o la de por defecto, `0` = sin cuota. La ficha muestra también cuánto ocupa su carpeta.
- **Carpetas compartidas:** cuota de cada una en su ficha (*Acceso → Carpetas compartidas*; `storage.shares[].quota_mb`). La ficha muestra cuánto ocupa.

Qué cuenta en cada operación:

- **Subir** (web, por partes y unidad de red): el tamaño del archivo. Con la subida por partes se comprueba al empezar, así que varias subidas a la vez pueden pasarse un poco de la cuota. Por WebDAV, sobrescribir un archivo descuenta lo que ocupaba el anterior.
- **Copiar** y **mover a otra carpeta**: lo que ocupa lo copiado en la carpeta de destino. Mover dentro de la misma carpeta no ocupa más y nunca se rechaza.
- Borrar nunca se rechaza, aunque la carpeta esté por encima de la cuota.

La unidad de red publica la cuota (propiedades `quota-used-bytes` y `quota-available-bytes` de WebDAV, RFC 4331), así que el Explorador de Windows muestra el espacio usado y libre de la unidad: lo que deja la cuota o, sin cuota, el espacio libre del disco del servidor.

### Cómo se mide el uso

Recorrer una carpeta remota grande (S3, SMB, SFTP…) es caro, y otro programa puede estar cambiando los mismos archivos sin pasar por StorageWeb. Por eso, como Nextcloud u ownCloud:

1. **Se lleva la cuenta** de lo que hace StorageWeb: lo que se sube, copia, mueve o edita desde la web, la API o la unidad de red suma o resta al momento.
2. **Se reconcilia en segundo plano** con lo que hay de verdad: cuando la medida tiene más de `storage.quota_refresh_minutes` (60 por defecto, en *Acceso → Cuotas*), o algo la deja dudosa (borrar una carpeta, cuyo tamaño no se sabe), se vuelve a recorrer la carpeta en un hilo aparte (hasta 10 minutos o 10 millones de elementos, dos carpetas a la vez como mucho) mientras se sigue usando la medida anterior. Así aparece lo que otros cambien directamente en el disco o el bucket.
3. **Nunca se recorre una carpeta mientras alguien espera**, salvo la primera vez desde que arranca el servicio (sin una medida no se podría aplicar la cuota; acotada a 10 segundos o 500.000 elementos). Las carpetas compartidas ya se miden al arrancar, en la tarea de monitorización.

Junto a la barra de la cuota pone **«Medido hace X»** (o «Midiendo el uso otra vez…»). Si una carpeta es tan grande que no da tiempo a recorrerla, se muestra como «≥» lo contado.

Si una ubicación SFTP, FTP o WebDAV apunta a un **servidor Windows**, marca **El servidor es Windows** (`windows_server`). Así se rechazan los nombres que Windows no toma tal cual (acabados en punto o espacio, con `:` o dispositivos como `CON`): allí `secreto.md.` o `secreto.md::$DATA` abrirían `secreto.md` saltándose los *ocultos para todos*, y `CON` colgaría la petición. En un servidor Linux déjala sin marcar: allí esos nombres son válidos (`Reunión 10:30.txt`). SMB lo hace siempre, y el disco local cuando StorageWeb corre en Windows.

Si una ubicación ya tiene sus propios límites (un bucket con cuota del proveedor, un NAS con cuotas), márcala como **No cuenta para la cuota** (`quota_exempt` en `storage.locations`): sus carpetas no tienen cuota y su uso no se mide.

El **espacio libre** del almacenamiento se muestra junto a la cuota cuando se sabe: en el disco del servidor (total y libre); S3 y Azure no tienen un tamaño fijo y se indican así; en SMB, SFTP, FTP y WebDAV remotos no se muestra.

## Limitaciones

- Los archivos no se mueven al cambiar una carpeta de sitio: cópialos antes (por ejemplo con `rclone copy` o `aws s3 sync`).
- Las copias de seguridad de StorageWeb (*Sistema → Copias*) son de la base de datos y la configuración, no de los archivos, estén donde estén.
