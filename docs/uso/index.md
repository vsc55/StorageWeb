# Guía de uso

Esta guía es para las personas que usan StorageWeb para subir y descargar archivos. Lo que puedes hacer depende de los permisos que haya configurado el administrador.

## Iniciar sesión

Abre la dirección que te haya dado tu organización (por ejemplo `https://files.midominio.com`). Hay dos formas de entrar:

- **Usuario y contraseña:** para cuentas locales o del sistema.
- **Iniciar sesión con Microsoft:** con tu cuenta del trabajo (Entra ID / Microsoft 365).

Si fallas la contraseña varias veces seguidas, el acceso se bloquea unos minutos. Es una protección contra ataques; espera y vuelve a intentarlo.

## Tu cuenta: idioma, tema y perfil

Pulsa tus iniciales, abajo en la barra de la izquierda, para abrir el menú de tu cuenta:

- **Mi perfil:** nombre visible, email, idioma, tema y **cambio de contraseña** (te pide la actual). Si entras con Microsoft o con un usuario del sistema, tu nombre y tu contraseña se gestionan en ese sistema.
- **Idioma:** **EN** / **ES**. Si no eliges ninguno, se usa el de tu navegador, o el que haya configurado el administrador (por defecto, inglés).
- **Tema:** **Sistema** (sigue la configuración de tu equipo), **Claro** u **Oscuro**.
- **Salir.**

Tus preferencias se guardan en tu cuenta. En la página de inicio de sesión también puedes elegir el idioma y el tema.

## La pantalla

```
┌────┬──────────────┬───────────────────────────────┬──────────────┐
│ ▣  │ Ubicaciones  │ Mi carpeta / Proyectos   [⌕] [+ Nueva carpeta] [⤒ Subir] │
│Arch│ ▾ Mi carpeta │ ☐ Nombre ↑      Tamaño  Modificado │ Detalle      │
│    │    Proyectos │ ☐ Contratos                       │  informe.pdf │
│Usu │      Contr…  │ ☑ informe.pdf   2,4 MB  11/11/26  │  Tipo · PDF  │
│Aju │ ▸ Compartido │ ☐ fotos.zip     18 MB   07/11/26  │  [Descargar] │
│ AD │              │ Suelta archivos aquí…             │              │
└────┴──────────────┴───────────────────────────────┴──────────────┘
```

- **Barra de la izquierda:** *Archivos* y, si eres administrador, el *Resumen* y las zonas *Personas*, *Acceso*, *Seguridad* y *Sistema* (Ctrl+K busca en todas). Abajo, tus iniciales abren el menú de tu cuenta.
- **Ubicaciones:** *Mi carpeta*, solo tuya, y las carpetas compartidas que te haya asignado el administrador. Las marcadas *(lectura)* solo permiten descargar. Bajo la ubicación abierta se ven la ruta actual y sus subcarpetas.
- **Lista:** pulsa el nombre de una carpeta para entrar en ella, o el de un archivo para descargarlo. Pulsa los títulos *Nombre*, *Tamaño* o *Modificado* para ordenar; la segunda pulsación invierte el orden. El cuadro *Filtrar en esta carpeta* oculta lo que no coincide.
- **Detalle (derecha):** al pulsar una fila (fuera del nombre) se selecciona y se muestran su tipo, tamaño, fecha y acciones. En pantallas estrechas el detalle aparece debajo de la lista, y en el móvil los paneles se apilan.

## Seleccionar varios

Marca las casillas de la izquierda, o la de la cabecera para seleccionar todo lo visible. Aparece una barra con **Descargar** (un solo archivo), **Renombrar** (un elemento) y **Eliminar** (uno o varios). Pulsa **Esc** o *Quitar selección* para deseleccionar.

## Subir archivos

- Pulsa **Subir archivos** y elige uno o varios, o **arrástralos** sobre la página.
- La barra muestra el progreso total. Puedes **Cancelar** en cualquier momento.
- Los archivos grandes se envían por partes. Si se corta la conexión, la subida se reintenta sola y continúa donde iba. Si cierras la página, vuelve a soltar el **mismo archivo en la misma carpeta** y continuará desde el último punto.
- Si ya existe un archivo con el mismo nombre, no se sobrescribe: el nuevo se guarda como `nombre (1).ext`.
- El texto de la zona de subida indica si hay un tamaño máximo por archivo.

## Descargar, crear carpetas, renombrar y eliminar

- **Descargar:** pulsa el nombre del archivo, o selecciónalo y usa **Descargar**. Las descargas grandes se pueden reanudar con el navegador o con un gestor de descargas.
- **Nueva carpeta:** el botón de la barra superior abre un pequeño formulario.
- **Renombrar y Eliminar:** desde la barra de selección o el panel de detalle. Eliminar una carpeta borra todo su contenido y no se puede deshacer.

Si no ves alguna de estas opciones, tu rol no tiene ese permiso o la carpeta es de solo lectura.

## Sesiones y tokens de API

En *Mi perfil* ves los dispositivos en los que tienes la sesión abierta y puedes cerrar los demás. Si cambias la contraseña, las otras sesiones se cierran solas.

Si necesitas usar tus archivos desde un script, crea un **token de API** en *Mi perfil*: elige si solo puede leer o también escribir, y cuándo caduca. Se muestra una sola vez; guárdalo como una contraseña. Ejemplos de uso en la [guía de seguridad](../administracion/seguridad.md#sesiones-y-tokens-de-api).

## Cerrar sesión

Pulsa **Salir** arriba a la derecha. Si tu organización lo ha configurado, también se cierra tu sesión de Microsoft.

## Preguntas frecuentes

¿Quién ve mis archivos?
:   En *Mi carpeta*, solo tú desde la web. Los administradores del servidor tienen acceso al disco.

¿Hay papelera?
:   No. Lo eliminado se borra del servidor; pregunta al administrador por las copias de seguridad de los archivos.

¿Por qué no puedo subir a una carpeta compartida?
:   Es de solo lectura o tu rol no tiene permiso de subida.
