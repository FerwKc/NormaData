# NORMADATA — Motor de Reglas para Verificar y Validar la Estructura de Bases de Datos SQL

Proyecto de Elder Fernando Chub Cac, 4090-22-16507. Universidad Mariano Gálvez de Guatemala, Campus Cobán.

## Ejecución

Se requiere Python con Tkinter, Microsoft ODBC Driver 18 for SQL Server y las dependencias de requirements.txt.

    python -m pip install -r requirements.txt
    python run.py

También puede utilizar run.bat. La versión verificada utiliza Windows, Python 3.14.8 y SQL Server Express 17.0.1000.7. No se acredita validación equivalente en Linux.

## Funciones verificadas

- Auditoría: catálogos y muestras de hasta 1000 filas por tabla; ejecutor de cambios bloqueado.
- 1FN: patrón de tokens en español, proporción estrictamente superior al 80 % y condición de longitud; grupos numerados como regla separada.
- 2FN: indicios de dependencias parciales en datos, respecto de claves únicas declaradas, no filtradas y no anulables. Búsqueda acotada a cuatro atributos por clave.
- Historial local SQLite, separado de la base evaluada, sin contraseñas ni muestras de filas.
- Exportación PDF con hallazgos, evidencia y planes.
- Remediación activa: vista previa, comprobación de log libre >= 200 % del tamaño de tabla e índices, ensayo inicial con ROLLBACK, aplicación con COMMIT y reversión ante errores.
- Transferencia por lotes de 250 claves dentro de una única transacción y cotejo de la cantidad esperada.

La ausencia de clave primaria es una advertencia de diseño, no una prueba de falta de atomicidad. Un indicio muestral no demuestra una dependencia universal del negocio. Los planes de 2FN son informativos y no ejecutables. Los planes de grupos numerados requieren una clave primaria entera simple e identificadores ASCII admitidos por el generador.

## Seguridad

ApplicationIntent=ReadOnly expresa intención de conexión; no reduce los privilegios de una cuenta SQL. Use permisos de lectura reales para auditoría. La conexión local utiliza Encrypt=no; una instalación remota requiere configurar cifrado y confianza de certificados según su entorno.

Los lotes dentro de una transacción no liberan el log retenido ni garantizan ausencia de bloqueos. La reserva del 200 % es una precondición y no una estimación universal de la demanda de log. Las credenciales se introducen en la interfaz o mediante variables del entorno de pruebas y no se incluyen en el código.

## Reproducción de pruebas

La suite recibe NORMADATA_LAB_PASSWORD y, opcionalmente, NORMADATA_LAB_USER en el entorno. No se incluye una contraseña. Con el entorno configurado:

    python tests/run_live_tests.py

La primera ejecución crea una base exclusiva con prefijo NORMADATA_PG2_LAB y marca de pertenencia. Las repeticiones solo restablecen sus tablas sintéticas marcadas. Conserva contexto.json, resultados_pruebas.json, diagnostico.json, reporte PDF y plan SQL. El directorio de evidencia se crea junto al proyecto, bajo output/normadata_entrega/evidence.

La ejecución registrada obtuvo 16/16 casos satisfactorios. CP11 utiliza contadores simulados para validar el rechazo sin enviar DDL; las pruebas con SQL Server, SQLite, PDF y compilación se identifican en el registro. Ese resultado no representa exactitud del 100 % en otros esquemas ni reemplaza el experimento N=20/M=10.

Las capturas se obtienen con tests/show_live_evidence.py y sus escenas connection, active, selection, results, preview e history. El arnés utiliza conexiones y datos reales del laboratorio y evita guardar credenciales. La escena preview crea únicamente una tabla sintética adicional en la base marcada.
