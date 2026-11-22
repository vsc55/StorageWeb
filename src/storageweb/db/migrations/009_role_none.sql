-- 009: rol de serie «none» (Sin permisos, core/permissions.NONE), el de las cuentas nuevas de serie.
-- Un rol propio con esa clave (alguien pudo crear uno «None» a mano) se retira: sus personas y grupos se quedan con
-- la clave «none», que ahora es el de serie y significa lo mismo (ningún permiso). El cambio de la tabla de roles se
-- nota al arrancar (los ajustes efectivos se vuelven a leer en cada proceso nuevo).
DELETE FROM roles WHERE key = 'none';
