import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 1. Update Code: Parser de Plantilla Outlook
outlook_parser = """const item = $input.first().json;

// Extrae el cuerpo del evento (HTML o texto plano)
const rawBody = item.body?.content || item.bodyPreview || '';
const cleanBody = rawBody.replace(/<[^>]*>/g, ' ');

// Expresiones regulares para la plantilla
const clienteMatch = cleanBody.match(/Cliente:\\s*([^\\n\\r;]+)/i);
const telMatch = cleanBody.match(/Tel(?:[eé]fono)?(?:\\s*WhatsApp)?:\\s*([+\\d\\s-]{8,})/i);
const tecnicoMatch = cleanBody.match(/T[eé]cnico:\\s*([^\\n\\r;]+)/i);
const dirMatch = cleanBody.match(/Direcci[oó]n:\\s*([^\\n\\r;]+)/i);
const notasMatch = cleanBody.match(/Notas?:\\s*([^\\n\\r]+)/i);

// Formateo de teléfono a estándar E.164
let telefono = telMatch ? telMatch[1].replace(/[\\s-]/g, '') : '';
if (telefono && !telefono.startsWith('+')) {
  telefono = '+' + telefono;
}

// Extracción del técnico (por cuerpo o asistentes)
let tecnicoNombre = tecnicoMatch ? tecnicoMatch[1].trim() : '';
let tecnicoEmail = '';
if (item.attendees && item.attendees.length > 0) {
  if (!tecnicoNombre) tecnicoNombre = item.attendees[0].emailAddress?.name || '';
  tecnicoEmail = item.attendees[0].emailAddress?.address || '';
}

// Extracción dinámica del Administrador organizador
const adminEmail = item.organizer?.emailAddress?.address || '';
const adminNombre = item.organizer?.emailAddress?.name || '';

return [{
  json: {
    microsoft_event_id: item.id,
    titulo: item.subject || 'Servicio Agendado',
    fecha_inicio: item.start?.dateTime,
    fecha_fin: item.end?.dateTime,
    cliente_nombre: clienteMatch ? clienteMatch[1].trim() : (item.subject || 'Cliente'),
    cliente_telefono: telefono || '+573004759860',
    tecnico_nombre: tecnicoNombre || 'Carlos Técnico',
    tecnico_email: tecnicoEmail,
    admin_email: adminEmail,
    admin_nombre: adminNombre,
    direccion_servicio: dirMatch ? dirMatch[1].trim() : (item.location?.displayName || 'Por confirmar'),
    descripcion: notasMatch ? notasMatch[1].trim() : (item.bodyPreview || 'Servicio agendado desde calendario')
  }
}];
"""

# 2. Update Code: Normalizar Entrada Webhook
webhook_norm = """const b = $input.first().json.body;
return [{
  json: {
    microsoft_event_id: b.microsoft_event_id || null,
    titulo: b.titulo,
    fecha_inicio: b.fecha_inicio,
    fecha_fin: b.fecha_fin,
    cliente_nombre: b.cliente_nombre || 'Cliente',
    cliente_telefono: b.cliente_telefono || '+573004759860',
    tecnico_nombre: b.tecnico_nombre || 'Carlos Técnico',
    tecnico_email: b.tecnico_email || '',
    admin_email: b.admin_email || '',
    direccion_servicio: b.direccion_servicio || 'Dirección registrada',
    descripcion: b.descripcion || ''
  }
}];
"""

# 3. Dynamic CTE Query in PG: Registrar Cita y Usuarios
atomic_query_dynamic = (
    "=WITH \n"
    "-- 1. Asegurar o buscar Cliente dinámico\n"
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
    "-- 2. Buscar Técnico dinámico (por email o nombre, fallback al primero activo)\n"
    "tec AS (\n"
    "  SELECT id, nombre, email, telefono_whatsapp \n"
    "  FROM usuarios \n"
    "  WHERE rol = 'TECNICO' AND activo = true\n"
    "  ORDER BY \n"
    "    CASE \n"
    "      WHEN email = '{{ $json.tecnico_email }}' THEN 1\n"
    "      WHEN LOWER(nombre) = LOWER('{{ $json.tecnico_nombre }}') THEN 2\n"
    "      ELSE 3 \n"
    "    END ASC\n"
    "  LIMIT 1\n"
    "),\n"
    "-- 3. Buscar Administrador dinámico (por email del organizador, fallback al principal activo)\n"
    "adm AS (\n"
    "  SELECT id, nombre, email, telefono_whatsapp \n"
    "  FROM usuarios \n"
    "  WHERE rol = 'ADMINISTRADOR' AND activo = true\n"
    "  ORDER BY \n"
    "    CASE \n"
    "      WHEN email = '{{ $json.admin_email }}' THEN 1\n"
    "      ELSE 2 \n"
    "    END ASC\n"
    "  LIMIT 1\n"
    "),\n"
    "-- 4. Insertar la cita vinculando cliente, técnico y administrador organizador\n"
    "nueva_cita AS (\n"
    "  INSERT INTO citas (\n"
    "    cliente_id, \n"
    "    tecnico_id, \n"
    "    admin_id, \n"
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
    "    adm.id, \n"
    "    '{{ $json.titulo }}', \n"
    "    '{{ $json.descripcion }}', \n"
    "    '{{ $json.direccion_servicio }}', \n"
    "    '{{ $json.fecha_inicio }}'::timestamptz, \n"
    "    '{{ $json.fecha_fin }}'::timestamptz, \n"
    "    'PENDIENTE', \n"
    "    '{{ $json.microsoft_event_id }}', \n"
    "    'PENDIENTE', \n"
    "    'PENDIENTE'\n"
    "  FROM cli, tec, adm\n"
    "  RETURNING id, titulo, descripcion, direccion_servicio, fecha_inicio, fecha_fin, cliente_id, tecnico_id, admin_id\n"
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
    "  adm.nombre AS admin_nombre,\n"
    "  adm.telefono_whatsapp AS admin_telefono\n"
    "FROM nueva_cita nc\n"
    "JOIN cli ON nc.cliente_id = cli.id\n"
    "JOIN tec ON nc.tecnico_id = tec.id\n"
    "JOIN adm ON nc.admin_id = adm.id;"
)

# 4. Dynamic query in PG: Consultar Datos Completos para Alertas
alert_query_dynamic = (
    "=SELECT \n"
    "  c.id AS cita_id,\n"
    "  c.titulo,\n"
    "  TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,\n"
    "  c.estado,\n"
    "  c.confirmacion_cliente,\n"
    "  c.confirmacion_tecnico,\n"
    "  c.motivo_cancelacion,\n"
    "  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.rol }}' AS rol_que_respondio,\n"
    "  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.action }}' AS accion_tomada,\n"
    "  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.sender_phone }}' AS sender_phone,\n"
    "  cli.nombre AS cliente_nombre,\n"
    "  cli.telefono_whatsapp AS cliente_telefono,\n"
    "  tec.nombre AS tecnico_nombre,\n"
    "  tec.telefono_whatsapp AS tecnico_telefono,\n"
    "  COALESCE(adm.telefono_whatsapp, default_adm.telefono_whatsapp) AS admin_telefono\n"
    "FROM citas c\n"
    "JOIN usuarios cli ON c.cliente_id = cli.id\n"
    "JOIN usuarios tec ON c.tecnico_id = tec.id\n"
    "LEFT JOIN usuarios adm ON c.admin_id = adm.id\n"
    "CROSS JOIN (SELECT telefono_whatsapp FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1) default_adm\n"
    "WHERE c.id = '{{ $json.id }}';"
)

for n in wf['nodes']:
    if n['name'] == 'Code: Parser de Plantilla Outlook':
        n['parameters']['jsCode'] = outlook_parser
    elif n['name'] == 'Code: Normalizar Entrada Webhook':
        n['parameters']['jsCode'] = webhook_norm
    elif n['name'] == 'PG: Registrar Cita y Usuarios':
        n['parameters']['query'] = atomic_query_dynamic
    elif n['name'] == 'PG: Consultar Datos Completos para Alertas':
        n['parameters']['query'] = alert_query_dynamic
    elif n['name'] == 'WA: Notificar Creacion a Admin':
        n['parameters']['jsonBody'] = (
            '={\n'
            '  "messaging_product": "whatsapp",\n'
            '  "to": "{{ $json.admin_telefono }}",\n'
            '  "type": "text",\n'
            '  "text": {\n'
            '    "body": "📋 *Cita Agendada Exitosamente*\\n\\n'
            '- ID Cita: {{ $json.cita_id }}\\n'
            '- Cliente: {{ $json.cliente_nombre }}\\n'
            '- Técnico: {{ $json.tecnico_nombre }}\\n'
            '- Fecha: {{ $json.fecha_inicio_fmt }}"\n'
            '  }\n'
            '}'
        )

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON upgraded for dynamic multi-admin & multi-tech.")

# Sync into SQLite
subprocess.run(['docker', 'stop', 'citas_n8n'], check=True)
db_path = '/tmp/database_sync_dynamic.sqlite'
subprocess.run(['docker', 'cp', 'citas_n8n:/home/node/.n8n/database.sqlite', db_path], check=True)

nodes_str = json.dumps(wf['nodes'])
conn_str = json.dumps(wf['connections'])
settings_str = json.dumps(wf['settings'])

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute('UPDATE workflow_entity SET nodes = ?, connections = ?, settings = ? WHERE id = ?', 
          (nodes_str, conn_str, settings_str, 'qj1WPHW4zMgtoR8m'))
c.execute('UPDATE workflow_history SET nodes = ?, connections = ? WHERE workflowId = ?', 
          (nodes_str, conn_str, 'qj1WPHW4zMgtoR8m'))
conn.commit()
conn.close()

subprocess.run(['docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine', 'sh', '-c', 'rm -f /data/database.sqlite-wal /data/database.sqlite-shm'], check=True)
subprocess.run(['docker', 'cp', db_path, 'citas_n8n:/home/node/.n8n/database.sqlite'], check=True)
subprocess.run(['docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine', 'sh', '-c', 'chown -R 1000:1000 /data'], check=True)
subprocess.run(['docker', 'start', 'citas_n8n'], check=True)

print("n8n restarted with dynamic multi-admin support!")
