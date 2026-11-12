# 0009. Un solo usuario de servicio para todos los archivos

- **Estado:** Aceptada
- **Fecha:** 2026-11-11

## Contexto

Con usuarios del sistema (PAM) sería natural escribir los archivos con el uid de cada usuario. Pero eso exige que el servicio corra como root, o con `CAP_SETUID`, para cambiar de identidad en cada petición. Y no aplica a los usuarios locales ni a los de Entra ID, que no existen en el sistema.

## Decisión

- **Usuario único:** el servicio corre con un único usuario sin privilegios (`storageweb`) y todos los archivos se escriben con él.
- **Aislamiento en la aplicación:** el aislamiento entre usuarios lo garantiza la aplicación, con raíces por usuario, permisos por rol y saneado de rutas.
- **Homes del sistema:** para escribir en `/home/<usuario>` se dan permisos explícitos al servicio con ACL. Está documentado como opción, no como modo por defecto.

## Alternativas consideradas

- **Servicio como root con cambio de uid por petición:** un fallo en la aplicación comprometería todo el sistema.
- **Un proceso por usuario:** complejo y caro.

## Consecuencias

- Superficie de ataque mínima y un servicio endurecido con systemd.
- Los permisos POSIX de los archivos no reflejan al usuario de la web. La auditoría registra quién subió qué.
- Quien tenga acceso al usuario `storageweb` o a root ve todos los archivos.
