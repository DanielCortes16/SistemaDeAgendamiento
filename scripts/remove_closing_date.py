import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

cliente_json_body = """={{
  (() => {
    let phone = ($json.cliente_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    if ($json.es_inminente) {
      const TARGET_MAX = 245;
      let fecha_ini = ($json.fecha_inicio_fmt || "");
      let titulo = ($json.titulo || "Servicio").trim();
      let tecnico = ($json.tecnico_nombre || "Técnico").trim();
      let direccion = ($json.direccion_servicio || "Por confirmar").trim();

      let base = "👋 *Cita Tekvo:* \\n🔧 Técnico: \\n📅 " + fecha_ini + "\\n📍 \\n\\n¿Confirmas tu asistencia?";
      let available = TARGET_MAX - base.length;

      while ((titulo.length + tecnico.length + direccion.length) > available) {
        if (direccion.length > 35) {
          direccion = direccion.slice(0, -1);
        } else if (titulo.length > 45) {
          titulo = titulo.slice(0, -1);
        } else if (tecnico.length > 25) {
          tecnico = tecnico.slice(0, -1);
        } else if (direccion.length > 20) {
          direccion = direccion.slice(0, -1);
        } else if (titulo.length > 20) {
          titulo = titulo.slice(0, -1);
        } else {
          direccion = direccion.slice(0, -1);
        }
      }

      let pollName = "👋 *Cita Tekvo:* " + titulo + "\\n" +
                     "🔧 Técnico: " + tecnico + "\\n" +
                     "📅 " + fecha_ini + "\\n" +
                     "📍 " + direccion + "\\n\\n" +
                     "¿Confirmas tu asistencia?";

      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: pollName,
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
        text: "👋 Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para el día *" + $json.fecha_inicio_fmt + "*.\\n\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio + "\\n\\n⏰ Te enviaremos un recordatorio 24 horas antes de la cita con las opciones para confirmar tu asistencia."
      });
    }
  })()
}}"""

tecnico_json_body = """={{
  (() => {
    let phone = ($json.tecnico_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    if ($json.es_inminente) {
      const TARGET_MAX = 245;
      let fecha_ini = ($json.fecha_inicio_fmt || "");
      let tel = ($json.cliente_telefono || "").trim();
      let titulo = ($json.titulo || "Servicio").trim();
      let cliente = ($json.cliente_nombre || "Cliente").trim();
      let direccion = ($json.direccion_servicio || "Por confirmar").trim();

      let base = "🛠️ *Labor:* \\n👤  (" + tel + ")\\n📅 " + fecha_ini + "\\n📍 \\n\\n¿Confirmas disponibilidad?";
      let available = TARGET_MAX - base.length;

      while ((titulo.length + cliente.length + direccion.length) > available) {
        if (direccion.length > 35) {
          direccion = direccion.slice(0, -1);
        } else if (titulo.length > 40) {
          titulo = titulo.slice(0, -1);
        } else if (cliente.length > 25) {
          cliente = cliente.slice(0, -1);
        } else if (direccion.length > 20) {
          direccion = direccion.slice(0, -1);
        } else if (titulo.length > 20) {
          titulo = titulo.slice(0, -1);
        } else {
          direccion = direccion.slice(0, -1);
        }
      }

      let pollName = "🛠️ *Labor:* " + titulo + "\\n" +
                     "👤 " + cliente + " (" + tel + ")\\n" +
                     "📅 " + fecha_ini + "\\n" +
                     "📍 " + direccion + "\\n\\n" +
                     "¿Confirmas disponibilidad?";

      return JSON.stringify({
        session: "default",
        chatId: phone,
        poll: {
          name: pollName,
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
        text: "🛠️ *Nueva Asignación de Servicio Tekvo*\\n\\nHola " + $json.tecnico_nombre + ", se te asignó la siguiente labor:\\n- Servicio: *" + $json.titulo + "*\\n- Fecha: " + $json.fecha_inicio_fmt + "\\n- Cliente: " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n- Ubicación: " + $json.direccion_servicio + "\\n\\n⏰ Te enviaremos un recordatorio 24 horas antes de la cita para confirmar tu disponibilidad."
      });
    }
  })()
}}"""

for node in wf.get('nodes', []):
    name = node.get('name')
    if name == 'WA: Notificar Creacion a Cliente':
        node['parameters']['jsonBody'] = cliente_json_body
    elif name == 'WA: Notificar Creacion a Tecnico':
        node['parameters']['jsonBody'] = tecnico_json_body

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

# Clean WAL and SHM to prevent SQLite corruption
subprocess.run([
    'docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine',
    'rm', '-f', '/data/database.sqlite-wal', '/data/database.sqlite-shm'
], check=True)

subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted cleanly with closing dates completely removed!")
