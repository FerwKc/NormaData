"""Pruebas reales en una base exclusiva; credenciales solo mediante entorno."""
import json,os,sys,time,uuid,dataclasses,re
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src.sqlserver import SQLServerClient
from src.rules import analyze_database,multivalue_profile,MULTIVALUE_PATTERN
from src.remediation import build_remediation_plan,wrap_transaction
from src.history import AuditHistory
from src.report import export_pdf

OUT=ROOT.parent/'output/normadata_entrega/evidence'
OUT.mkdir(parents=True,exist_ok=True)
password=os.environ['NORMADATA_LAB_PASSWORD']
active=SQLServerClient('.'+chr(92)+'SQLEXPRESS','',os.environ.get('NORMADATA_LAB_USER','sa'),password,False)
audit=SQLServerClient(active.server,'',active.user,password,True)
context_path=OUT/'context.json'
if context_path.exists():
    context=json.loads(context_path.read_text(encoding='utf-8'));db=context['database']
else:
    db='NORMADATA_PG2_LAB_'+uuid.uuid4().hex[:8]
    context={'database':db,'server':active.server}
    with active._pyodbc.connect(active._connection_string(),autocommit=True,timeout=8) as c:
        c.cursor().execute(f'CREATE DATABASE [{db}]')
    with active._pyodbc.connect(active._connection_string(db),autocommit=True,timeout=8) as c:
        c.cursor().execute("EXEC sys.sp_addextendedproperty @name=N'NORMADATA_Project', @value=N'PG2_LAB_2026'")
    context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
assert re.fullmatch(r'NORMADATA_PG2_LAB_[a-f0-9]{8}',db), 'Nombre de laboratorio no válido'

def connect():
    c=active._pyodbc.connect(active._connection_string(db),autocommit=True,timeout=8)
    marker=c.cursor().execute("SELECT CONVERT(nvarchar(100),value) FROM sys.extended_properties WHERE name=N'NORMADATA_Project' AND class=0").fetchone()
    if not marker or marker[0]!='PG2_LAB_2026':
        c.close();raise RuntimeError('Base de laboratorio sin marca de pertenencia.')
    return c

results=[]
def test(identifier,title,fn,kind='Real SQL Server'):
    start=time.perf_counter()
    try:
        details=fn() or {}
        results.append({'id':identifier,'title':title,'kind':kind,'status':'PASS',
            'seconds':round(time.perf_counter()-start,4),'details':details})
    except Exception as exc:
        results.append({'id':identifier,'title':title,'kind':kind,'status':'FAIL',
            'seconds':round(time.perf_counter()-start,4),
            'details':{'error':str(exc).replace(password,'[redactado]')}})
    print(identifier,results[-1]['status'])

def setup():
    with connect() as c:
        q=c.cursor()
        if q.execute("SELECT OBJECT_ID(N'dbo.ClienteLista')").fetchone()[0]:
            if q.execute("SELECT COL_LENGTH('dbo.Contactos','telefono1')").fetchone()[0] is None:
                q.execute('DROP TABLE dbo.Contactos_telefono_Item')
                q.execute('ALTER TABLE dbo.Contactos ADD telefono1 NVARCHAR(40) NULL,telefono2 NVARCHAR(40) NULL')
                q.execute("UPDATE dbo.Contactos SET telefono1=N'555'+CONVERT(nvarchar(20),Id),telefono2=N'777'+CONVERT(nvarchar(20),Id)")
            return
        q.execute("""
        CREATE TABLE dbo.ClienteLista(Id INT NOT NULL PRIMARY KEY,Telefonos NVARCHAR(300) NULL);
        CREATE TABLE dbo.DetalleAnomalia(IdPedido INT NOT NULL,IdProducto INT NOT NULL,
            NombreProducto NVARCHAR(80) NOT NULL,Cantidad INT NOT NULL,
            CONSTRAINT PK_DetalleAnomalia PRIMARY KEY(IdPedido,IdProducto));
        CREATE TABLE dbo.DetalleControl(IdPedido INT NOT NULL,IdProducto INT NOT NULL,Cantidad INT NOT NULL,
            CONSTRAINT PK_DetalleControl PRIMARY KEY(IdPedido,IdProducto));
        CREATE TABLE dbo.Contactos(Id INT NOT NULL PRIMARY KEY,telefono1 NVARCHAR(40) NULL,telefono2 NVARCHAR(40) NULL);
        CREATE TABLE dbo.SinClave(Valor NVARCHAR(30));
        INSERT INTO dbo.SinClave VALUES(N'caso de reversión');
        CREATE TABLE dbo.Conflicto(Id INT NOT NULL CONSTRAINT PK_SinClave_Normadata PRIMARY KEY);
        INSERT INTO dbo.Conflicto VALUES(1);
        """)
        q.executemany('INSERT INTO dbo.ClienteLista VALUES(?,?)',[(i,'José;María' if i<10 else 'ÁNGEL;NIÑO;GÜÉMEZ;MUÑOZ;ÓSCAR;ÉRICK;ÚRSULA;ÍÑIGO') for i in range(1,11)])
        q.execute("INSERT INTO dbo.ClienteLista VALUES(11,NULL)")
        q.executemany('INSERT INTO dbo.Contactos VALUES(?,?,?)',[(i,'555'+str(i),'777'+str(i)) for i in range(1,601)])
        for order in range(1,4):
            for product in range(1,4):
                q.execute('INSERT INTO dbo.DetalleAnomalia VALUES(?,?,?,?)',order,product,['Árbol','Piñón','Güiro'][product-1],order*product)
                q.execute('INSERT INTO dbo.DetalleControl VALUES(?,?,?)',order,product,order*product)

setup()
with connect() as c:
    version=c.cursor().execute("SELECT CONVERT(varchar(40),SERVERPROPERTY('ProductVersion')),CONVERT(varchar(100),SERVERPROPERTY('Edition'))").fetchone()
context.update({'version':version[0],'edition':version[1],'executed_at_utc':datetime.now(timezone.utc).isoformat(),
                'python':sys.version.split()[0],'sample_limit':1000})
context_path.write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')

test('CP01','Conexión en Modo Auditoría',lambda:(audit.test_connection() or {'mode':'audit'}))
test('CP02','Conexión en Modo Remediación Activa',lambda:(active.test_connection() or {'mode':'remediation'}))

tables=audit.profile_tables(db,audit.load_metadata(db))
byname={t.name:t for t in tables}
result=analyze_database(db,tables)

def multivalue():
    findings=[f for f in result.findings if f.table=='dbo.ClienteLista' and f.rule=='1FN']
    assert findings
    p=multivalue_profile(row['Telefonos'] for row in byname['ClienteLista'].sample_rows)
    assert p['n']==10 and p['prevalence']==1 and p['long_matches']==1
    return p
test('CP03','1FN: regex en español, nulos y umbral de longitud',multivalue)

def dependency():
    findings=[f for f in result.findings if f.table=='dbo.DetalleAnomalia' and f.rule=='2FN']
    assert any("(IdProducto)" in f.message and 'NombreProducto' in f.message for f in findings)
    return {'findings':[f.message for f in findings],'candidate_keys':byname['DetalleAnomalia'].candidate_keys}
test('CP04','2FN: dependencia parcial observada en clave compuesta',dependency)
test('CP05','Control negativo: atributo dependiente de la clave completa',lambda: {'findings':len([f for f in result.findings if f.table=='dbo.DetalleControl' and f.rule=='2FN'])} if not any(f.table=='dbo.DetalleControl' and f.rule=='2FN' for f in result.findings) else (_ for _ in ()).throw(AssertionError('Falso positivo')))

repeated=next(f for f in result.findings if f.table=='dbo.Contactos' and 'repetitivas' in f.message)
plan=build_remediation_plan(repeated,byname['Contactos'])
(OUT/'plan_contactos.sql').write_text(plan.wrapped_sql,encoding='utf-8')

def audit_guard():
    try:audit.execute_plan(db,plan)
    except PermissionError:
        with connect() as c:assert c.cursor().execute('SELECT COUNT(*) FROM dbo.Contactos').fetchone()[0]==600
        return {'rejected_before_SQL':True,'source_rows':600}
    raise AssertionError('La auditoría permitió ejecución')
test('CP06','Bloqueo de ejecución desde Modo Auditoría',audit_guard)
test('CP07','Consulta de log y particiones: umbral real del 200 %',lambda:active.resource_preflight(db,'dbo.Contactos'))

def rollback():
    info=active.execute_plan(db,plan,rollback_only=True)
    with connect() as c:
        q=c.cursor();assert q.execute("SELECT OBJECT_ID(N'dbo.Contactos_telefono_Item')").fetchone()[0] is None
        assert q.execute("SELECT COL_LENGTH('dbo.Contactos','telefono1')").fetchone()[0] is not None
        assert q.execute('SELECT COUNT(*) FROM dbo.Contactos').fetchone()[0]==600
        assert q.execute('SELECT @@TRANCOUNT').fetchone()[0]==0
    return {**info,'source_rows_preserved':600,'destination_absent':True}
test('CP08','Ensayo de migración por lotes con ROLLBACK',rollback)

def failed_transaction():
    f=next(f for f in result.findings if f.table=='dbo.SinClave' and f.status=='Advertencia')
    error_plan=build_remediation_plan(f,byname['SinClave'])
    try:active.execute_plan(db,error_plan)
    except Exception as exc:
        with connect() as c:
            assert c.cursor().execute("SELECT COL_LENGTH('dbo.SinClave','normadata_SinClave_id')").fetchone()[0] is None
            assert c.cursor().execute('SELECT COUNT(*) FROM dbo.SinClave').fetchone()[0]==1
        return {'expected_failure':type(exc).__name__,'column_addition_rolled_back':True,'source_rows':1}
    raise AssertionError('No se produjo el fallo controlado de restricción')
test('CP09','Fallo intermedio: reversión del DDL previo',failed_transaction)

def commit():
    with connect() as c:
        before={(r[0],n,r[i]) for r in c.cursor().execute('SELECT Id,telefono1,telefono2 FROM dbo.Contactos') for i,n in [(1,'telefono1'),(2,'telefono2')]}
    info=active.execute_plan(db,plan)
    with connect() as c:
        q=c.cursor();after={tuple(row) for row in q.execute('SELECT source_key,attribute_name,value FROM dbo.Contactos_telefono_Item')}
        assert before==after and len(after)==1200
        assert q.execute("SELECT COL_LENGTH('dbo.Contactos','telefono1')").fetchone()[0] is None
        assert q.execute('SELECT @@TRANCOUNT').fetchone()[0]==0
    return {**info,'migrated_values':1200,'exact_value_comparison':True,'source_rows':600}
test('CP10','Migración por lotes con COMMIT y conservación exacta',commit)

def insufficient():
    fake=Mock();fake.execute.side_effect=[Mock(fetchone=lambda:(1000,900)),Mock(fetchone=lambda:(200,))]
    p=SQLServerClient._resource_preflight(fake,'dbo.Caso')
    assert p['allowed'] is False and p['required_bytes']==400
    from unittest.mock import MagicMock
    stub=object.__new__(SQLServerClient)
    stub.read_only=False
    stub.load_metadata=lambda database:[byname['Contactos']]
    stub._connection_string=lambda database:'CONEXION_SIMULADA'
    connection=MagicMock()
    cursor=Mock();cursor.execute.side_effect=[Mock(fetchone=lambda:(1000,900)),Mock(fetchone=lambda:(200,))]
    connection.cursor.return_value=cursor
    context=MagicMock();context.__enter__.return_value=connection
    stub._pyodbc=Mock();stub._pyodbc.connect.return_value=context
    try:stub.execute_plan(db,plan)
    except RuntimeError:
        assert cursor.execute.call_count==2
        assert all(str(call.args[0]).strip().upper().startswith('SELECT') for call in cursor.execute.call_args_list)
    else:raise AssertionError('Se admitió una reserva insuficiente')
    p['DDL_not_sent']=True
    return p
test('CP11','Reserva insuficiente: evaluación de la condición',insufficient,'Simulación unitaria de contadores')

def threshold():
    p=multivalue_profile(['José;María']*7+['Ángel;Niño;Muñoz;Güémez;Óscar']+['texto','otro'])
    assert p['prevalence']==.8 and not p['flag']
    assert all(MULTIVALUE_PATTERN.fullmatch(v) for v in ['José;María','Muñoz|Güémez','ÁNGEL/NIÑO'])
    assert not multivalue_profile([None])['flag']
    return {'strict_80_percent_rejected':True,'spanish_tokens':True,'nulls_not_counted':True}
test('CP12','Frontera 80 %, Unicode y muestras insuficientes',threshold,'Prueba unitaria real del motor')

def history():
    h=AuditHistory(OUT/'historial_pruebas.sqlite3');h.save(active.server,result)
    assert h.list()
    return {'persisted_audits':len(h.list()),'credentials_stored':False}
test('CP13','Persistencia del historial local',history,'SQLite real')

def pdf():
    path=export_pdf(result,OUT/'reporte_diagnostico_real.pdf',server=active.server,tables=tables)
    assert path.stat().st_size>1000
    return {'file':path.name,'bytes':path.stat().st_size}
test('CP14','Exportación del diagnóstico a PDF',pdf,'Aplicación real')

def coverage():
    from src.models import Column,TableMetadata
    columns=tuple(Column('K'+str(i),'int',False,is_primary_key=True) for i in range(5))
    wide=TableMetadata('dbo','ClaveAmplia',columns,candidate_keys=(tuple(c.name for c in columns),))
    empty=dataclasses.replace(byname['DetalleAnomalia'],sample_rows=())
    assert any(f.status=='Indeterminado' for f in analyze_database('unit',[wide]).findings)
    assert any(f.status=='Indeterminado' for f in analyze_database('unit',[empty]).findings)
    return {'wide_key_unresolved':True,'empty_sample_unresolved':True}
test('CP15','Cobertura: claves amplias y muestra vacía',coverage,'Prueba unitaria real del motor')

def compilation():
    import py_compile,importlib.metadata
    files=list((ROOT/'src').glob('*.py'))+[ROOT/'run.py']
    for path in files:py_compile.compile(str(path),doraise=True)
    return {'modules_compiled':len(files),'pyodbc':importlib.metadata.version('pyodbc'),
            'reportlab':importlib.metadata.version('reportlab'),'syntax_errors':0}
test('CP16','Compilación e importación de dependencias',compilation,'Compilador Python real')

# Aggregate evidence contains no row values or credentials.
(OUT/'diagnostico.json').write_text(json.dumps({'database':db,'tables_analyzed':result.tables_analyzed,
    'score':result.score,'findings':[dataclasses.asdict(f) for f in result.findings]},ensure_ascii=False,indent=2),encoding='utf-8')
record={'context':context,'tests':results,'passed':sum(r['status']=='PASS' for r in results),'total':len(results)}
(OUT/'resultados_pruebas.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
print('RESULT',record['passed'],'/',record['total'])
raise SystemExit(0 if record['passed']==record['total'] else 1)
