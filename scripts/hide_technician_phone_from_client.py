import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 1. Update 'WA: Notificar Creacion a Cliente' to include admin line and ensure technician phone is never included
cliente_json_body = """={{
  (() => {
    let phone = ($json.cliente_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    if ($json.es_inminente) {
      const TARGET_MAX = 245;
      let fecha_ini = ($json.fecha_inicio_fmt || "");
      let titulo = ($json.titulo || "Servicio").trim();
      let tecnico = ($json.tecnico_nombre || "Técnico").trim();
      let direccion = ($json.direccion_servicio || "Por confirmar").trim();

      let base = "🛠️ *Cita UT TEKVO:* \\n🔧 Técnico: \\n📅 " + fecha_ini + "\\n📍 \\n\\n¿Confirmas tu asistencia?";
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

      let pollName = "🛠️ *Cita UT TEKVO:* " + titulo + "\\n" +
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
        text: "🛠️ *Nueva Asignación de Servicio UT TEKVO*\\n\\nHola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para el día *" + $json.fecha_inicio_fmt + "*.\\n\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio + "\\n📞 Línea de atención: " + ($json.admin_telefono || "+573118198511") + "\\n\\n⏰ Te enviaremos un recordatorio 24 horas antes de la cita con las opciones para confirmar tu asistencia."
      });
    }
  })()
}}"""

# 2. Update 'WA: Responder a Quien Presiono Boton' so client never sees technician phone, and gets admin line
responder_boton_body = """={{
  (() => {
    let adm = ($json.admin_telefono || "+573118198511");
    if ($json.rol_que_respondio === "CLIENTE") {
      if ($json.accion_tomada === "CONFIRMAR") {
        return JSON.stringify({
          session: "default",
          chatId: ($json.sender_phone || "").replace("+", "") + "@c.us",
          text: "🙌 ¡Muchas gracias, " + $json.cliente_nombre + "! Tu asistencia ha sido registrada exitosamente como *CONFIRMADA*.\\n\\n📋 *Detalles de tu Cita:*\\n• *Servicio:* " + $json.titulo + "\\n• *Fecha y Hora:* " + $json.fecha_fmt + "\\n• *Técnico Asignado:* " + $json.tecnico_nombre + "\\n• *Dirección:* " + ($json.direccion_servicio || "Dirección registrada") + "\\n\\n📞 *Atención y Soporte:* Toda comunicación, cambio o solicitud sobre tu servicio debe realizarse directamente a través de la administración: " + adm + ".\\n\\n¡Gracias por confiar en UT TEKVO!"
        });
      } else {
        return JSON.stringify({
          session: "default",
          chatId: ($json.sender_phone || "").replace("+", "") + "@c.us",
          text: "⚠️ Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* programada para el " + $json.fecha_fmt + " ha sido registrada como *CANCELADA*.\\n\\n📞 Si deseas reprogramar el servicio o tienes alguna inquietud, comunícate directamente con la administración al " + adm + "."
        });
      }
    } else {
      if ($json.accion_tomada === "CONFIRMAR") {
        return JSON.stringify({
          session: "default",
          chatId: ($json.sender_phone || "").replace("+", "") + "@c.us",
          text: "🙌 ¡Muchas gracias, " + $json.tecnico_nombre + "! Tu disponibilidad ha sido registrada exitosamente como *CONFIRMADA*.\\n\\n📋 *Detalles de la Labor:*\\n• *Servicio:* " + $json.titulo + "\\n• *Fecha y Hora:* " + $json.fecha_fmt + "\\n• *Cliente:* " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n• *Dirección:* " + ($json.direccion_servicio || "Dirección registrada") + "\\n\\n¡Muchos éxitos en la labor!"
        });
      } else {
        return JSON.stringify({
          session: "default",
          chatId: ($json.sender_phone || "").replace("+", "") + "@c.us",
          text: "⚠️ Hola " + $json.tecnico_nombre + ", tu respuesta ha sido registrada como *CANCELADA / NO DISPONIBLE*. El administrador ha sido notificado para reasignar la labor."
        });
      }
    }
  })()
}}"""

for node in wf.get('nodes', []):
    name = node.get('name')
    if name == 'WA: Notificar Creacion a Cliente':
        node['parameters']['jsonBody'] = cliente_json_body
        print("Updated node: WA: Notificar Creacion a Cliente")
    elif name == 'WA: Responder a Quien Presiono Boton':
        node['parameters']['jsonBody'] = responder_boton_body
        print("Updated node: WA: Responder a Quien Presiono Boton")

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully updated.")

# Stop n8n to sync database safely
print("Stopping citas_n8n...")
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
    'sh', '-c', 'rm -f /data/database.sqlite-wal /data/database.sqlite-shm'
], check=True)

print("Starting citas_n8n...")
subprocess.run(['docker', 'start', 'citas_n8n'], check=True)

print("Restarting citas_meta_bridge...")
subprocess.run(['docker', 'restart', 'citas_meta_bridge'], check=True)

print("✅ Flujo n8n y meta_bridge actualizados y sincronizados con éxito.")
