# 0012. Administración por zonas con Resumen y buscador

- **Estado:** Aceptada
- **Fecha:** 2026-11-14

## Contexto

La administración había crecido por capas: *Usuarios*, *Grupos* y *Auditoría* en la barra lateral, y una página de *Ajustes* con diez secciones. Esto daba tres problemas:

- Lo relacionado estaba repartido. Para dar acceso a una carpeta había que pasar por *Ajustes → Carpetas compartidas* (ruta y usuarios) y por *Grupos → Matriz* (nivel por grupo). Las sesiones estaban en *Ajustes* y los usuarios fuera.
- Las secciones mezclaban formularios que se aplican al guardar con botones que actúan al momento. *Seguridad* tenía las reglas de bloqueo y la lista de IPs bloqueadas; *Mantenimiento* tenía la retención y las copias.
- Nada avisaba de lo que necesitaba atención (un secreto a punto de caducar, una carpeta que no existe) salvo entrando en la sección concreta.

## Decisión

- **Zonas por tarea** en la barra lateral: *Resumen*, *Personas* (usuarios, grupos, sesiones y tokens), *Acceso* (carpetas compartidas, matriz, permisos del rol, carpetas personales), *Seguridad* (inicio de sesión, reglas de bloqueo, IPs bloqueadas, auditoría) y *Sistema* (general y marca, red, mantenimiento, copias, información). Cada zona tiene un submenú.
- **Un único registro** (`web/nav.py`) define zonas y páginas. De él salen la barra lateral, el submenú, las tarjetas del Resumen y el buscador. Cada página declara su tipo: `config` (se aplica al guardar), `op` (se aplica al momento) o `info`, y la página lo muestra.
- Las secciones mixtas se separan: `security` / `ips` y `maintenance` / `backups`.
- **Acceso por carpeta** (`web/views/access.py`): cada carpeta con sus entradas «quién entra» (todos, usuario o grupo) y su nivel. Para que los usuarios también puedan ser de solo lectura se añade `read_only_users`. La regla es la misma para todas las vías: se escribe si **alguna** permite escribir (`core.storage.share_access`).
- **Resumen** como portada, con los avisos de `core/alerts.py` y un contador en la barra lateral.
- **Buscador** (Ctrl+K) sobre páginas, ajustes con ancla al campo, acciones, usuarios, grupos y carpetas. Sin JavaScript es una página de resultados.
- Las URLs de las secciones de ajustes se mantienen. `/admin/settings/shares` redirige a la página de carpetas.

## Alternativas consideradas

- **Mantener *Ajustes* y añadir solo el buscador:** encuentra los campos, pero no arregla que acceso y operación estén mezclados.
- **Un centro de mando con el buscador como entrada principal:** rápido para quien sabe lo que busca, pero esconde la estructura a quien la está aprendiendo. Se toma solo el buscador.
- **Portada por tareas frecuentes:** útil como complemento (son las *tareas frecuentes* del Resumen), pero no sirve como única navegación.

## Consecuencias

- Una página nueva de la administración necesita su entrada en `web/nav.py`. Si no la tiene, no sale en el submenú ni en el buscador.
- Los ajustes del buscador se mantienen a mano en `web/search.py`, con las mismas etiquetas que el formulario para reutilizar sus traducciones.
- La matriz de accesos (por grupo) y la página de carpetas (por carpeta) editan las mismas listas de `storage.shares`.
- Los avisos del Resumen se calculan en cada petición de un administrador: comprueban si existe cada carpeta y miran la copia más reciente. Es barato con pocas carpetas. Si un día hay muchas, habrá que guardarlos en caché.
