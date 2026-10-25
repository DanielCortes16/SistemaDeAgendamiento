import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 1. New 24h Reminder Poll for Tecnico (with client name, client phone, address, and date)
reminder_24h_tecnico_body = """={{
  (() => {
    let phone = ($json.tecnico_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    const TARGET_MAX = 245;
    let fecha = ($json.fecha_fmt || "").trim();
    let tel = ($json.cliente_telefono || "").trim();
    let titulo = ($json.titulo || "Servicio").trim();
    let cliente = ($json.cliente_nombre || "Cliente").trim();
    let direccion = ($json.direccion_servicio || "Por confirmar").trim();

    let base = "🛠️ *Recordatorio Labor UT TEKVO:* \\n👤  (" + tel + ")\\n📅 " + fecha + "\\n📍 \\n\\n¿Confirmas disponibilidad?";
    let available = TARGET_MAX - base.length;

    while ((titulo.length + cliente.length + direccion.length) > available) {
      if (direccion.length > 35) {
        direccion = direccion.slice(0, -1);
      } else if (titulo.length > 35) {
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

    let pollName = "🛠️ *Recordatorio Labor UT TEKVO:* " + titulo + "\\n" +
                   "👤 " + cliente + " (" + tel + ")\\n" +
                   "📅 " + fecha + "\\n" +
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
  })()
}}"""

# 2. New 24h Reminder Poll for Cliente (with technician name, address, and date)
reminder_24h_cliente_body = """={{
  (() => {
    let phone = ($json.cliente_telefono || "").replace("+", "").replace(/[^0-9]/g, "") + "@c.us";
    const TARGET_MAX = 245;
    let fecha = ($json.fecha_fmt || "").trim();
    let titulo = ($json.titulo || "Servicio").trim();
    let tecnico = ($json.tecnico_nombre || "Técnico").trim();
    let direccion = ($json.direccion_servicio || "Por confirmar").trim();

    let base = "⏰ *Recordatorio Cita UT TEKVO:* \\n🔧 Técnico: \\n📅 " + fecha + "\\n📍 \\n\\n¿Confirmas tu asistencia?";
    let available = TARGET_MAX - base.length;

    while ((titulo.length + tecnico.length + direccion.length) > available) {
      if (direccion.length > 35) {
        direccion = direccion.slice(0, -1);
      } else if (titulo.length > 35) {
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

    let pollName = "⏰ *Recordatorio Cita UT TEKVO:* " + titulo + "\\n" +
                   "🔧 Técnico: " + tecnico + "\\n" +
                   "📅 " + fecha + "\\n" +
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
  })()
}}"""

# 3. New Query for PG: Consultar Datos Completos para Alertas (including direccion_servicio & descripcion)
sql_consultar_datos_alertas = """=SELECT 
  c.id AS cita_id,
  c.titulo,
  c.direccion_servicio,
  c.descripcion,
  TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
  c.estado,
  c.confirmacion_cliente,
  c.confirmacion_tecnico,
  c.motivo_cancelacion,
  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.rol }}' AS rol_que_respondio,
  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.action }}' AS accion_tomada,
  '{{ $('Code: Parsear Boton Meta Multi-Rol').item.json.sender_phone }}' AS sender_phone,
  cli.nombre AS cliente_nombre,
  cli.telefono_whatsapp AS cliente_telefono,
  tec.nombre AS tecnico_nombre,
  tec.telefono_whatsapp AS tecnico_telefono,
  COALESCE(adm.telefono_whatsapp, default_adm.telefono_whatsapp) AS admin_telefono
FROM citas c
JOIN usuarios cli ON c.cliente_id = cli.id
JOIN usuarios tec ON c.tecnico_id = tec.id
LEFT JOIN usuarios adm ON c.admin_id = adm.id
CROSS JOIN (SELECT telefono_whatsapp FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1) default_adm
WHERE c.id = '{{ $json.id }}';"""

# 4. New Rich Admin Notification in n8n
admin_notification_body = """={{
  (() => {
    let quienNom = ($json.rol_que_respondio === "CLIENTE") ? $json.cliente_nombre : $json.tecnico_nombre;
    let quienTel = ($json.rol_que_respondio === "CLIENTE") ? $json.cliente_telefono : $json.tecnico_telefono;
    let estCli = ($json.confirmacion_cliente === "CONFIRMADA") ? "✅ CONFIRMADA" : (($json.confirmacion_cliente === "CANCELADA") ? "❌ CANCELADA" : "⏳ PENDIENTE");
    let estTec = ($json.confirmacion_tecnico === "CONFIRMADA") ? "✅ CONFIRMADA" : (($json.confirmacion_tecnico === "CANCELADA") ? "❌ CANCELADA" : "⏳ PENDIENTE");

    let header = "";
    let guia = "";
    if ($json.estado === "CONFIRMADA") {
      header = "🎉 *CITA 100% CONFIRMADA POR AMBOS - UT TEKVO*";
      guia = "👉 *Ambos confirmaron:* La cita está lista para ejecución. Se envió automáticamente la opción interactiva [▶️ Iniciar Labor] al técnico.";
    } else if ($json.rol_que_respondio === "CLIENTE" && $json.accion_tomada === "CANCELAR") {
      header = "🚨 *ALERTA: CITA CANCELADA POR EL CLIENTE - UT TEKVO*";
      guia = "👉 El cliente canceló la cita. La agenda del técnico " + $json.tecnico_nombre + " ha sido liberada automáticamente.";
    } else if ($json.rol_que_respondio === "TECNICO" && $json.accion_tomada === "CANCELAR") {
      header = "🚨 *URGENTE: TÉCNICO NO DISPONIBLE - UT TEKVO*";
      guia = "👉 *ACCIÓN REQUERIDA:* El técnico " + $json.tecnico_nombre + " indicó no estar disponible. Reasignar técnico para este servicio de inmediato.";
    } else {
      header = "🔔 *Confirmación Parcial de Cita - UT TEKVO*";
      if ($json.confirmacion_cliente === "CONFIRMADA") {
        guia = "👉 *Pendiente:* Falta confirmación del técnico " + $json.tecnico_nombre + " (" + $json.tecnico_telefono + ").";
      } else {
        guia = "👉 *Pendiente:* Falta confirmación del cliente " + $json.cliente_nombre + " (" + $json.cliente_telefono + ").";
      }
    }

    let idCorto = ($json.cita_id || "").slice(0, 8);
    let msg = header + "\\n\\n" +
              "📋 *Datos de la Cita:*\\n" +
              "• *ID:* `" + idCorto + "`\\n" +
              "• *Servicio:* *" + $json.titulo + "*\\n" +
              "• *Fecha y Hora:* *" + $json.fecha_fmt + "*\\n" +
              "• *Dirección:* " + ($json.direccion_servicio || "Dirección registrada") + "\\n\\n" +
              "👤 *Quien Respondió Ahora:*\\n" +
              "• *Persona:* *" + quienNom + "* (" + $json.rol_que_respondio + ")\\n" +
              "• *Teléfono:* " + quienTel + "\\n" +
              "• *Respuesta:* " + ($json.accion_tomada === "CONFIRMAR" ? "✅ CONFIRMADO" : "❌ CANCELADO") + "\\n\\n" +
              "📊 *Estado en Vivo de Ambas Partes:*\\n" +
              "• *Cliente:* " + $json.cliente_nombre + " (" + $json.cliente_telefono + ") ➔ " + estCli + "\\n" +
              "• *Técnico:* " + $json.tecnico_nombre + " (" + $json.tecnico_telefono + ") ➔ " + estTec + "\\n" +
              "• *Estado General:* *" + $json.estado + "*\\n\\n" +
              guia;

    let phone = ($json.admin_telefono || "+573118198511").replace("+", "");
    return JSON.stringify({
      session: "default",
      chatId: phone + "@c.us",
      text: msg
    });
  })()
}}"""

for node in wf.get('nodes', []):
    name = node.get('name')
    if name == 'WA: 24h Botones a Tecnico':
        node['parameters']['jsonBody'] = reminder_24h_tecnico_body
        print("Updated node: WA: 24h Botones a Tecnico")
    elif name == 'WA: 24h Botones a Cliente':
        node['parameters']['jsonBody'] = reminder_24h_cliente_body
        print("Updated node: WA: 24h Botones a Cliente")
    elif name == 'PG: Consultar Datos Completos para Alertas':
        node['parameters']['query'] = sql_consultar_datos_alertas
        print("Updated node: PG: Consultar Datos Completos para Alertas")
    elif name == 'WA: Notificar Estado Completo a Admin':
        node['parameters']['jsonBody'] = admin_notification_body
        print("Updated node: WA: Notificar Estado Completo a Admin")

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully updated.")

# Stop n8n to safely sync database
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

print("✅ ¡Sincronización completada con éxito!")
