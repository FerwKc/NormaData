# Seguridad operativa de NORMADATA

El cliente de auditoría rechaza execute_plan antes de enviar SQL de modificación. ApplicationIntent=ReadOnly no sustituye permisos del servidor. Las pruebas registradas utilizaron la cuenta administrativa suministrada; no acreditan mínimos privilegios de una cuenta independiente.

El ejecutor activo admite solo planes generados por la aplicación. Regenera la propuesta con metadatos actuales, coteja el SQL y comprueba la reserva de log. No admite scripts arbitrarios ni planes semánticos informativos. La vista previa presenta el cierre seleccionado, COMMIT o ROLLBACK; el ensayo es la opción inicial.

La precondición compara bytes disponibles del log con dos veces las páginas usadas por tabla e índices. No contabiliza crecimiento futuro ni espacio de disco como reserva ya disponible. Un fallo de visibilidad, permisos o capacidad rechaza el plan. Los lotes retienen una unidad transaccional y pueden conservar bloqueos y log hasta su cierre.

Las consultas identifican objetos mediante parámetros o delimitación de identificadores. El generador DDL admite identificadores ASCII simples y claves enteras simples para la migración de grupos numerados. Otros casos requieren diseño adicional. Las transformaciones se ejecutan solo sobre copias autorizadas, con respaldo y validación de consumidores externos.

El historial local no almacena contraseñas ni muestras de datos. La evidencia distribuida corresponde a datos sintéticos. El laboratorio se reconoce por su prefijo y propiedad NORMADATA_Project antes de restablecer los fixtures. No se elimina ni se modifica otra base de datos mediante la suite.
