import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 1. New PG: Registrar Cita y Usuarios Query with es_inminente calculation
pg_registrar_query = """=WITH 
-- 1. Asegurar o buscar Cliente dinámico
cli AS (
  INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol)
  VALUES (
    '{{ $json.cliente_nombre }}',
    'cli_' || REGEXP_REPLACE('{{ $json.cliente_telefono }}', '[^0-9]', '', 'g') || '@cliente.com',
    '{{ $json.cliente_telefono }}',
    'CLIENTE'
  )
  ON CONFLICT (email) DO UPDATE SET 
    nombre = EXCLUDED.nombre, 
    telefono_whatsapp = EXCLUDED.telefono_whatsapp
  RETURNING id, nombre, email, telefono_whatsapp
),
-- 2. Buscar Técnico dinámico (por email o nombre, fallback al primero activo)
tec AS (
  SELECT id, nombre, email, telefono_whatsapp 
  FROM usuarios 
  WHERE rol = 'TECNICO' AND activo = true
  ORDER BY 
    CASE 
      WHEN email = '{{ $json.tecnico_email }}' THEN 1
      WHEN LOWER(nombre) = LOWER('{{ $json.tecnico_nombre }}') THEN 2
      ELSE 3 
    END ASC
  LIMIT 1
),
-- 3. Buscar Administrador dinámico (por email del organizador, fallback al principal activo)
adm AS (
  SELECT id, nombre, email, telefono_whatsapp 
  FROM usuarios 
  WHERE rol = 'ADMINISTRADOR' AND activo = true
  ORDER BY 
    CASE 
      WHEN email = '{{ $json.admin_email }}' THEN 1
      ELSE 2 
    END ASC
  LIMIT 1
),
-- 4. Insertar la cita vinculando cliente, técnico y administrador organizador
nueva_cita AS (
  INSERT INTO citas (
    cliente_id, 
    tecnico_id, 
    admin_id, 
    titulo, 
    descripcion, 
    direccion_servicio, 
    fecha_inicio, 
    fecha_fin, 
    estado, 
    microsoft_event_id, 
    confirmacion_cliente, 
    confirmacion_tecnico,
    recordatorio_24h_enviado,
    recordatorio_cliente_enviado,
    recordatorio_tecnico_enviado,
    recordatorio_enviado_at
  )
  SELECT 
    cli.id, 
    tec.id, 
    adm.id, 
    '{{ $json.titulo }}', 
    '{{ $json.descripcion }}', 
    '{{ $json.direccion_servicio }}', 
    '{{ $json.fecha_inicio }}'::timestamptz, 
    '{{ $json.fecha_fin }}'::timestamptz, 
    'PENDIENTE', 
    '{{ $json.microsoft_event_id }}', 
    'PENDIENTE', 
    'PENDIENTE',
    CASE WHEN '{{ $json.fecha_inicio }}'::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END,
    CASE WHEN '{{ $json.fecha_inicio }}'::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END,
    CASE WHEN '{{ $json.fecha_inicio }}'::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END,
    CASE WHEN '{{ $json.fecha_inicio }}'::timestamptz <= (NOW() + INTERVAL '24 hours') THEN NOW() ELSE NULL END
  FROM cli, tec, adm
  RETURNING id, titulo, descripcion, direccion_servicio, fecha_inicio, fecha_fin, cliente_id, tecnico_id, admin_id, recordatorio_24h_enviado
)
SELECT 
  nc.id AS cita_id,
  nc.titulo,
  nc.descripcion,
  nc.direccion_servicio,
  TO_CHAR(nc.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_inicio_fmt,
  TO_CHAR(nc.fecha_fin AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fin_fmt,
  nc.recordatorio_24h_enviado AS es_inminente,
  cli.nombre AS cliente_nombre,
  cli.telefono_whatsapp AS cliente_telefono,
  tec.nombre AS tecnico_nombre,
  tec.telefono_whatsapp AS tecnico_telefono,
  adm.nombre AS admin_nombre,
  adm.telefono_whatsapp AS admin_telefono
FROM nueva_cita nc
JOIN cli ON nc.cliente_id = cli.id
JOIN tec ON nc.tecnico_id = tec.id
JOIN adm ON nc.admin_id = adm.id;"""

# 2. Dynamic creation node for Cliente (<24h -> Poll, >24h -> Text)
creation_cliente_url = "={{ $json.es_inminente ? 'http://citas_waha:3000/api/sendPoll' : 'http://citas_waha:3000/api/sendText' }}"
creation_cliente_body = """={{
  (() => {
    let phone = ($json.cliente_telefono || "").replace("+", "") + "@c.us";
    if ($json.es_inminente) {
      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: "👋 Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para *" + $json.fecha_inicio_fmt + "* (hasta " + $json.fecha_fin_fmt + ").\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio + "\\n\\n¿Confirmas tu asistencia para recibir al técnico?",
          options: [
            "✅ Sí, confirmo",
            "❌ Cancelar cita"
          ],
          multipleAnswers: false
        }
      });
    } else {
      return JSON.stringify({
        session: "default",
        chatId: phone,
        text: "👋 Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para el día *" + $json.fecha_inicio_fmt + "* (hasta " + $json.fecha_fin_fmt + ").\\n\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio + "\\n\\n⏰ Te enviaremos un recordatorio 24 horas antes de la cita con las opciones para confirmar tu asistencia."
      });
    }
  })()
}}"""

# 3. Dynamic creation node for Tecnico (<24h -> Poll, >24h -> Text)
creation_tecnico_url = "={{ $json.es_inminente ? 'http://citas_waha:3000/api/sendPoll' : 'http://citas_waha:3000/api/sendText' }}"
creation_tecnico_body = """={{
  (() => {
    let phone = ($json.tecnico_telefono || "").replace("+", "") + "@c.us";
    if ($json.es_inminente) {
      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: "🛠️ *Nueva Asignación de Servicio Tekvo*\\n\\nHola " + $json.tecnico_nombre + ", se te asignó la siguiente labor:\\n- Servicio: *" + $json.titulo + "*\\n- Fecha: " + $json.fecha_inicio_fmt + " a " + $json.fecha_fin_fmt + "\\n- Cliente: " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n- Ubicación: " + $json.direccion_servicio + "\\n\\n¿Confirmas tu disponibilidad para atender este servicio?",
          options: [
            "✅ Sí, confirmo",
            "❌ Cancelar labor"
          ],
          multipleAnswers: false
        }
      });
    } else {
      return JSON.stringify({
        session: "default",
        chatId: phone,
        text: "🛠️ *Nueva Asignación de Servicio Tekvo*\\n\\nHola " + $json.tecnico_nombre + ", se te asignó la siguiente labor:\\n- Servicio: *" + $json.titulo + "*\\n- Fecha: " + $json.fecha_inicio_fmt + " a " + $json.fecha_fin_fmt + "\\n- Cliente: " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n- Ubicación: " + $json.direccion_servicio + "\\n\\n⏰ Te enviaremos un recordatorio 24 horas antes de la cita para confirmar tu disponibilidad."
      });
    }
  })()
}}"""

# 4. 24h Reminder Cron SQL Query
sql_24h_query = """SELECT 
  c.id AS cita_id,
  c.titulo,
  c.direccion_servicio,
  TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
  cli.nombre AS cliente_nombre,
  cli.telefono_whatsapp AS cliente_telefono,
  tec.nombre AS tecnico_nombre,
  tec.telefono_whatsapp AS tecnico_telefono
FROM citas c
JOIN usuarios cli ON c.cliente_id = cli.id
JOIN usuarios tec ON c.tecnico_id = tec.id
WHERE c.estado = 'PENDIENTE'
  AND c.fecha_inicio BETWEEN NOW() AND (NOW() + INTERVAL '24 hours')
  AND c.created_at < (NOW() - INTERVAL '4 hours')
  AND c.recordatorio_24h_enviado = FALSE
  AND (c.recordatorio_cliente_enviado = FALSE OR c.recordatorio_tecnico_enviado = FALSE);"""

waha_headers = [
    {"name": "X-Api-Key", "value": "citas-waha-key-2026"},
    {"name": "Content-Type", "value": "application/json"}
]

for node in wf.get('nodes', []):
    name = node.get('name')
    if name == 'PG: Registrar Cita y Usuarios':
        node['parameters']['query'] = pg_registrar_query
    elif name == 'WA: Notificar Creacion a Cliente':
        node['parameters']['url'] = creation_cliente_url
        node['parameters']['sendHeaders'] = True
        node['parameters']['headerParameters'] = {'parameters': waha_headers}
        node['parameters']['sendBody'] = True
        node['parameters']['specifyBody'] = 'json'
        node['parameters']['jsonBody'] = creation_cliente_body
    elif name == 'WA: Notificar Creacion a Tecnico':
        node['parameters']['url'] = creation_tecnico_url
        node['parameters']['sendHeaders'] = True
        node['parameters']['headerParameters'] = {'parameters': waha_headers}
        node['parameters']['sendBody'] = True
        node['parameters']['specifyBody'] = 'json'
        node['parameters']['jsonBody'] = creation_tecnico_body
    elif name == 'PG: Buscar Citas 24h Antes':
        node['parameters']['query'] = sql_24h_query

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully updated.")

# Stop n8n to sync database safely
subprocess.run(['docker', 'stop', 'citas_n8n'], check=True)

# Copy current sqlite db out
db_path = '/tmp/database_sync.sqlite'
subprocess.run(['docker', 'cp', 'citas_n8n:/home/node/.n8n/database.sqlite', db_path], check=True)

nodes_str = json.dumps(wf['nodes'])
conn_str = json.dumps(wf['connections'])
settings_str = json.dumps(wf.get('settings', {}))

conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute('UPDATE workflow_entity SET nodes = ?, connections = ?, settings = ? WHERE id = ?', 
          (nodes_str, conn_str, settings_str, 'qj1WPHW4zMgtoR8m'))
c.execute('UPDATE workflow_history SET nodes = ?, connections = ? WHERE workflowId = ?', 
          (nodes_str, conn_str, 'qj1WPHW4zMgtoR8m'))
conn.commit()
conn.close()

# Copy updated db back
subprocess.run(['docker', 'cp', db_path, 'citas_n8n:/home/node/.n8n/database.sqlite'], check=True)

# Clean WAL and SHM to prevent SQLite corruption
subprocess.run([
    'docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine',
    'rm', '-f', '/data/database.sqlite-wal', '/data/database.sqlite-shm'
], check=True)

subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted with cleanly synced smart scheduling workflow!")
