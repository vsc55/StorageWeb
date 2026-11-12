# Usuarios, roles y permisos

## Orígenes de usuario

| Origen | Cómo entra | Quién lo crea |
|---|---|---|
| **Local** | Usuario y contraseña (hash scrypt en SQLite; mínimo 10 caracteres) | Un admin, desde la web o la CLI |
| **Sistema (PAM)** | Usuario y contraseña del sistema operativo | Automático en su primer login (`auth.pam.enabled`) |
| **Entra ID** | Botón *Iniciar sesión con Microsoft* | Automático (`auto_provision`) o un admin por adelantado |

## Roles

| Rol | Puede |
|---|---|
| `admin` | Todo sobre archivos, y además *Administración*: usuarios, ajustes y auditoría |
| `user` | Los permisos de `permissions.user`. Por defecto: subir, descargar y crear carpetas |

Hay tres protecciones: un admin no puede quitarse el rol, ni desactivarse, ni borrarse a sí mismo, y siempre debe quedar **al menos un admin activo**.

## Permisos sobre archivos

| Permiso | `admin` | `user` (por defecto) | Carpeta de solo lectura |
|---|---|---|---|
| Descargar | ✔ | ✔ | ✔ |
| Subir | ✔ | ✔ | ✘ |
| Crear carpetas | ✔ | ✔ | ✘ |
| Renombrar | ✔ | ✘ | ✘ |
| Eliminar | ✔ | ✘ | ✘ |

Los permisos del rol `user` se cambian en *Administración → Ajustes → Permisos*. El servidor los comprueba en cada acción, también en la API: la interfaz solo oculta los botones.

## Carpetas

- **Personal:** sale de `storage.home_template`, o de la ruta personalizada del usuario (campo *Carpeta personal*). Se crea en el primer acceso si `create_home` está activo.
- **Compartidas:** se asignan por usuario o por grupo. Los grupos se obtienen así:
  - locales: los que asigne el admin (`--groups` o el formulario);
  - PAM: los grupos del sistema, actualizados en cada login;
  - Entra ID: Object IDs de grupo y nombres de App Role del token, actualizados en cada login.

  Todos se comparan en minúsculas.

## Gestión

=== "Web"

    *Administración → Usuarios*: crear, editar (rol, grupos, carpeta, estado, contraseña) y eliminar.

=== "CLI"

    ```bash
    sudo storageweb-admin user-add ana --role user --groups rrhh,it
    sudo storageweb-admin user-set ana --role admin
    sudo storageweb-admin user-set ana --disable
    sudo storageweb-admin user-set ana --locale en      # idioma preferido de la interfaz
    sudo storageweb-admin user-passwd ana
    sudo storageweb-admin user-add juan@contoso.com --source entra     # alta previa de Entra
    sudo storageweb-admin user-list
    ```

Al desactivar un usuario se cierra su sesión en la siguiente petición. Al eliminarlo, **sus archivos se conservan** en el disco.

## Usuarios del sistema (PAM)

1. Activa `auth.pam.enabled`. Con `allowed_groups` limitas quién entra; con `admin_groups` decides quién recibe el rol admin.
2. `pam_unix` necesita leer `/etc/shadow`, y el servicio no puede usar `unix_chkpwd` porque corre con `NoNewPrivileges`. En Debian/Ubuntu añade el usuario del servicio al grupo `shadow`: `usermod -aG shadow storageweb` (lo hace `install.sh --pam`).
3. Para usar el home real (`/home/<usuario>`):
   - activa `use_system_home` o pon `home_template = "/home/{username}"`;
   - da acceso al servicio: `setfacl -R -m u:storageweb:rwx -m d:u:storageweb:rwx /home/ana`;
   - en la unidad systemd, cambia `ProtectHome=true` a `false` y añade `/home` a `ReadWritePaths` (`systemctl edit storageweb`).

Todos los archivos se escriben con el usuario del servicio, no con el del usuario que inicia sesión; ver el [ADR 0009](../arquitectura/decisiones/0009-usuario-de-servicio.md).
