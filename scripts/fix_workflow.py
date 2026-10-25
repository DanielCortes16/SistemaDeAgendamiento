import json
import sqlite3

# 1. Load workflow
with open('/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json', 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 2. Fix the query in PG: Registrar Cita y Usuarios
atomic_query = (
    "=WITH \n"
    "-- 1. Asegurar o buscar Cliente\n"
    "cli AS (\n"
    "  INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol)\n"
    "  VALUES (\n"
    "    '{{ $json.cliente_nombre }}',\n"
    "    'cli_' || REGEXP_REPLACE('{{ $json.cliente_telefono }}', '[^0-9]', '', 'g') || '@cliente.com',\n"
    "    '{{ $json.cliente_telefono }}',\n"
    "    'CLIENTE'\n"
    "  )\n"
    "  ON CONFLICT (email) DO UPDATE SET \n"
    "    nombre = EXCLUDED.nombre, \n"
    "    telefono_whatsapp = EXCLUDED.telefono_whatsapp\n"
    "  RETURNING id, nombre, email, telefono_whatsapp\n"
    "),\n"
    "-- 2. Asegurar o buscar Técnico\n"
    "tec AS (\n"
    "  SELECT id, nombre, email, telefono_whatsapp FROM usuarios WHERE rol = 'TECNICO' AND activo = true LIMIT 1\n"
    "),\n"
    "-- 3. Insertar la cita\n"
    "nueva_cita AS (\n"
    "  INSERT INTO citas (\n"
    "    cliente_id, \n"
    "    tecnico_id, \n"
    "    titulo, \n"
    "    descripcion, \n"
    "    direccion_servicio, \n"
    "    fecha_inicio, \n"
    "    fecha_fin, \n"
    "    estado, \n"
    "    microsoft_event_id, \n"
    "    confirmacion_cliente, \n"
    "    confirmacion_tecnico\n"
    "  )\n"
    "  SELECT \n"
    "    cli.id, \n"
    "    tec.id, \n"
    "    '{{ $json.titulo }}', \n"
    "    '{{ $json.descripcion }}', \n"
    "    '{{ $json.direccion_servicio }}', \n"
    "    '{{ $json.fecha_inicio }}'::timestamptz, \n"
    "    '{{ $json.fecha_fin }}'::timestamptz, \n"
    "    'PENDIENTE', \n"
    "    '{{ $json.microsoft_event_id }}', \n"
    "    'PENDIENTE', \n"
    "    'PENDIENTE'\n"
    "  FROM cli, tec\n"
    "  RETURNING id, titulo, descripcion, direccion_servicio, fecha_inicio, fecha_fin, cliente_id, tecnico_id\n"
    ")\n"
    "SELECT \n"
    "  nc.id AS cita_id,\n"
    "  nc.titulo,\n"
    "  nc.descripcion,\n"
    "  nc.direccion_servicio,\n"
    "  TO_CHAR(nc.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_inicio_fmt,\n"
    "  TO_CHAR(nc.fecha_fin AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fin_fmt,\n"
    "  cli.nombre AS cliente_nombre,\n"
    "  cli.telefono_whatsapp AS cliente_telefono,\n"
    "  tec.nombre AS tecnico_nombre,\n"
    "  tec.telefono_whatsapp AS tecnico_telefono,\n"
    "  adm.telefono_whatsapp AS admin_telefono\n"
    "FROM nueva_cita nc\n"
    "JOIN cli ON nc.cliente_id = cli.id\n"
    "JOIN tec ON nc.tecnico_id = tec.id\n"
    "CROSS JOIN (SELECT telefono_whatsapp FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1) adm;"
)

for n in wf['nodes']:
    if n['name'] == 'PG: Registrar Cita y Usuarios':
        n['parameters']['query'] = atomic_query

wf['connections']['PG: Registrar Cita y Usuarios'] = {
    'main': [
        [
            {'node': 'WA: Notificar Creacion a Cliente', 'type': 'main', 'index': 0},
            {'node': 'WA: Notificar Creacion a Tecnico', 'type': 'main', 'index': 0},
            {'node': 'WA: Notificar Creacion a Admin', 'type': 'main', 'index': 0}
        ]
    ]
}

# 3. Save JSON
with open('/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

# 4. Sync into SQLite
nodes_str = json.dumps(wf['nodes'])
conn_str = json.dumps(wf['connections'])
conn = sqlite3.connect('/tmp/database4.sqlite')
c = conn.cursor()
c.execute('UPDATE workflow_entity SET nodes = ?, connections = ? WHERE id = ?', (nodes_str, conn_str, 'qj1WPHW4zMgtoR8m'))
c.execute('UPDATE workflow_history SET nodes = ?, connections = ? WHERE workflowId = ? AND versionId = ?', 
          (nodes_str, conn_str, 'qj1WPHW4zMgtoR8m', 'c6b94c3b-644c-44e6-8a05-dbdd4c761967'))
conn.commit()
conn.close()
print("Workflow fixed and SQLite synced successfully!")
