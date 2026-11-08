"""Escenas de la interfaz con consultas reales a la base exclusiva de pruebas.

Uso: python tests/show_live_evidence.py connection|active|selection|results|preview|history
La contraseña se recibe por entorno y no se guarda en el historial.
"""
import json,os,sys
from pathlib import Path
if sys.platform=='win32':
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.app import NormadataApp
from src.sqlserver import SQLServerClient
from src.rules import analyze_database

context=json.loads((ROOT.parent/'output/normadata_entrega/evidence/context.json').read_text(encoding='utf-8'))
scenario=sys.argv[1] if len(sys.argv)>1 else 'results'
password=os.environ['NORMADATA_LAB_PASSWORD']
mode='remediation' if scenario in ('active','preview') else 'audit'
client=SQLServerClient(context['server'],'',os.environ.get('NORMADATA_LAB_USER','sa'),password,mode=='audit')
client.test_connection()
if scenario=='preview':
    # Only an owned synthetic fixture is added; never touches another database.
    with client._pyodbc.connect(client._connection_string(context['database']),autocommit=True) as c:
        marker=c.cursor().execute("SELECT CONVERT(nvarchar(100),value) FROM sys.extended_properties WHERE name=N'NORMADATA_Project' AND class=0").fetchone()
        assert marker and marker[0]=='PG2_LAB_2026'
        q=c.cursor()
        if not q.execute("SELECT OBJECT_ID('dbo.ContactosVista')").fetchone()[0]:
            q.execute('CREATE TABLE dbo.ContactosVista(Id INT PRIMARY KEY,telefono1 NVARCHAR(40),telefono2 NVARCHAR(40))')
            q.execute("INSERT INTO dbo.ContactosVista VALUES(1,N'555123',N'777123'),(2,N'555456',N'777456')")
tables=client.profile_tables(context['database'],client.load_metadata(context['database']))
if scenario=='preview':tables=[t for t in tables if t.name=='ContactosVista']
if scenario=='results':tables=[t for t in tables if t.name in ('ClienteLista','DetalleAnomalia','DetalleControl')]
result=analyze_database(context['database'],tables)
app=NormadataApp()
app.geometry('1400x850+0+0')
app.title('NORMADATA | Evidencia '+scenario)
def stage():
    app.client=client
    app.operation_mode.set(mode)
    app.server_var.set(context['server']);app.user_var.set(client.user)
    app.password_var.set(password)
    app.database_var.set(context['database'])
    app.connection_verified=True
    app.available_databases={context['database']:()}
    app.loaded_tables=tables
    app.current_result=result
    app.status_var.set('Conexión real verificada · '+context['edition']+' · '+context['version'])
    app.mode_badge.configure(text='REMEDIACIÓN ACTIVA' if mode=='remediation' else 'AUDITORÍA · SOLO LECTURA')
    if scenario in ('connection','active'):app._show_connection()
    elif scenario=='selection':app._show_selection()
    elif scenario=='history':
        app.history.save(context['server'],result);app._show_history()
    else:
        app._show_results()
        if scenario=='preview':app.after(250,app._open_remediation_modal)
app.after(600,stage)
app.mainloop()
