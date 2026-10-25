import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

creation_cliente_url = "={{ $json.es_inminente ? 'http://citas_waha:3000/api/sendPoll' : 'http://citas_waha:3000/api/sendText' }}"
creation_cliente_body = """={{
  (() => {
    let phone = ($json.cliente_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    if ($json.es_inminente) {
      let hora_fin = ($json.fecha_fin_fmt || "").includes(" ") ? $json.fecha_fin_fmt.split(" ")[1] : ($json.fecha_fin_fmt || "");
      let cli = ($json.cliente_nombre || "").slice(0, 20);
      let tit = ($json.titulo || "").slice(0, 30);
      let tec = ($json.tecnico_nombre || "").slice(0, 20);
      let dir = ($json.direccion_servicio || "").slice(0, 40);

      let name = "👋 Hola " + cli + ", tu cita: *" + tit + "*\\n" +
                 "📅 " + $json.fecha_inicio_fmt + " - " + hora_fin + "\\n" +
                 "🔧 Técnico: " + tec + "\\n" +
                 "📍 " + dir + "\\n\\n" +
                 "¿Confirmas tu asistencia?";

      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: name,
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

creation_tecnico_url = "={{ $json.es_inminente ? 'http://citas_waha:3000/api/sendPoll' : 'http://citas_waha:3000/api/sendText' }}"
creation_tecnico_body = """={{
  (() => {
    let phone = ($json.tecnico_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    if ($json.es_inminente) {
      let hora_fin = ($json.fecha_fin_fmt || "").includes(" ") ? $json.fecha_fin_fmt.split(" ")[1] : ($json.fecha_fin_fmt || "");
      let tec = ($json.tecnico_nombre || "").slice(0, 20);
      let tit = ($json.titulo || "").slice(0, 30);
      let cli = ($json.cliente_nombre || "").slice(0, 20);
      let tel = ($json.cliente_telefono || "");
      let dir = ($json.direccion_servicio || "").slice(0, 35);

      let name = "🛠️ *Asignación Tekvo*\\n" +
                 "Hola " + tec + ", labor: *" + tit + "*\\n" +
                 "📅 " + $json.fecha_inicio_fmt + " - " + hora_fin + "\\n" +
                 "👤 " + cli + " (" + tel + ")\\n" +
                 "📍 " + dir + "\\n\\n" +
                 "¿Confirmas disponibilidad?";

      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: name,
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

waha_headers = [
    {"name": "X-Api-Key", "value": "citas-waha-key-2026"},
    {"name": "Content-Type", "value": "application/json"}
]

for node in wf.get('nodes', []):
    name = node.get('name')
    if name == 'WA: Notificar Creacion a Cliente':
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

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Updated workflow JSON saved.")

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

# Clean WAL and SHM to prevent SQLite corruption
subprocess.run([
    'docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine',
    'rm', '-f', '/data/database.sqlite-wal', '/data/database.sqlite-shm'
], check=True)

subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted cleanly with updated technician and client poll templates!")
