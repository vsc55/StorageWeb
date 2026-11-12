# Gentoo

Cada release incluye `storageweb-gentoo-overlay-X.Y.Z.tar.gz`, un overlay de Portage con:

| Paquete | Contenido |
|---|---|
| `www-apps/storageweb` | La aplicación (distutils-r1, PEP 517), unidades systemd, script OpenRC y CLI |
| `acct-user/storageweb`, `acct-group/storageweb` | Usuario y grupo del servicio |

## Instalación

```bash
sudo tar -xzf storageweb-gentoo-overlay-X.Y.Z.tar.gz -C /var/db/repos
printf '[storageweb]\nlocation = /var/db/repos/storageweb-overlay\n' \
  | sudo tee /etc/portage/repos.conf/storageweb.conf
echo 'www-apps/storageweb ~amd64' | sudo tee /etc/portage/package.accept_keywords/storageweb
echo 'www-apps/storageweb all-rights-reserved' | sudo tee /etc/portage/package.license/storageweb
sudo emerge -av www-apps/storageweb
```

El ebuild descarga `storageweb-X.Y.Z.tar.gz` de la release de GitHub y comprueba su `Manifest` (BLAKE2B y SHA512).

## USE flags

| Flag | Efecto |
|---|---|
| `msal` | Instala `dev-python/msal` para `auth.entra.provider = "msal"`. El proveedor `oauth2` por defecto no lo necesita. |
| `pam` | Instala `dev-python/python-pam` para el login con usuarios del sistema. |

## Puesta en marcha

```bash
sudo storageweb-admin user-add admin --role admin
```

=== "OpenRC"

    ```bash
    sudo rc-update add storageweb default
    sudo rc-service storageweb start
    ```

    Opciones en `/etc/conf.d/storageweb` (`STORAGEWEB_CONFIG`, `STORAGEWEB_USER`, `STORAGEWEB_OPTS`). El log va a `/var/log/storageweb/storageweb.log`. Las copias diarias se programan con cron; ver [Copias de seguridad](copias-seguridad.md#programar-las-copias).

=== "systemd"

    ```bash
    sudo systemctl enable --now storageweb
    sudo systemctl enable --now storageweb-backup.timer    # copias diarias (opcional)
    ```

Rutas: `/etc/storageweb/config.json`, `/var/lib/storageweb` (datos) y `/srv/storageweb` (archivos). La plantilla de nginx está en `/usr/share/storageweb/nginx-storageweb.conf`.

## Versiones

Las versiones previas se convierten al formato de Gentoo: `1.2.0-rc1` → `storageweb-1.2.0_rc1.ebuild`.
