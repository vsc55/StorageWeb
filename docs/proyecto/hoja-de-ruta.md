# Hoja de ruta

Funcionalidades pendientes, por orden aproximado de prioridad. Las ideas salen en parte de la administración de ServiceSentry.

| # | Qué | Para qué | Notas |
|---|---|---|---|
| 8 | **Notificaciones** por email, Microsoft Teams o webhook | Avisar de eventos sin entrar en la web: secreto de Entra ID a punto de caducar, carpeta compartida que no existe, IP bloqueada, usuario desactivado, copia automática fallida | Configuración por canal y por tipo de evento; plantillas traducidas |
| 9 | **MFA (TOTP)** para usuarios locales | Segundo factor con una app de autenticación | Los usuarios de Entra ID ya tienen el MFA de Microsoft; códigos de recuperación y reinicio por un admin |
| 10 | **LDAP / Active Directory, SAML y SCIM** | LDAP para directorios locales; SAML para otros proveedores; SCIM para que Entra ID cree y desactive usuarios y grupos automáticamente | SCIM complementa la desactivación de usuarios: la baja en Entra ID desactivaría la cuenta sin esperar a un inicio de sesión |
| 12 | **Diagnóstico de dependencias** | Avisar de vulnerabilidades conocidas (CVE) en las bibliotecas instaladas | Consulta a una base de vulnerabilidades (OSV) desde *Sistema → Información* |

Si quieres trabajar en alguna, abre antes un issue (ver [Contribuir](contribuir.md)).
