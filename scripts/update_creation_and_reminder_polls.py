import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 1. Creation Poll for Cliente
creation_cliente_body = """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.cliente_telefono || "").replace("+", "") + "@c.us",
    poll: {
      name: "👋 Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para el *" + $json.fecha_inicio_fmt + "* (hasta " + $json.fecha_fin_fmt + ").\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio + "\\n\\n¿Confirmas tu asistencia para recibir al técnico?",
      options: [
        "✅ Sí, confirmo",
        "❌ Cancelar cita"
      ],
      multipleAnswers: false
    }
  })
}}"""

# 2. Creation Poll for Tecnico
creation_tecnico_body = """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.tecnico_telefono || "").replace("+", "") + "@c.us",
    poll: {
      name: "🛠️ *Nueva Asignación de Servicio Tekvo*\\n\\nHola " + $json.tecnico_nombre + ", se te asignó la siguiente labor:\\n- Servicio: *" + $json.titulo + "*\\n- Fecha: " + $json.fecha_inicio_fmt + " a " + $json.fecha_fin_fmt + "\\n- Cliente: " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n- Ubicación: " + $json.direccion_servicio + "\\n\\n¿Confirmas tu disponibilidad para atender este servicio?",
      options: [
        "✅ Sí, confirmo",
        "❌ Cancelar labor"
      ],
      multipleAnswers: false
    }
  })
}}"""

# 3. 24h Reminder SQL Query
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
    if name == 'WA: Notificar Creacion a Cliente':
        node['parameters']['url'] = 'http://citas_waha:3000/api/sendPoll'
        node['parameters']['sendHeaders'] = True
        node['parameters']['headerParameters'] = {'parameters': waha_headers}
        node['parameters']['sendBody'] = True
        node['parameters']['specifyBody'] = 'json'
        node['parameters']['jsonBody'] = creation_cliente_body
    elif name == 'WA: Notificar Creacion a Tecnico':
        node['parameters']['url'] = 'http://citas_waha:3000/api/sendPoll'
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

subprocess.run(['docker', 'cp', db_path, 'citas_n8n:/home/node/.n8n/database.sqlite'], check=True)
subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted with cleanly synced workflow!")
