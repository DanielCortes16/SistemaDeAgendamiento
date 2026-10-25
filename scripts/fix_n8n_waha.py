import json
import sqlite3

workflow_path = "/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json"
with open(workflow_path, "r", encoding="utf-8") as f:
    wf = json.load(f)

waha_headers = [
    {"name": "X-Api-Key", "value": "citas-waha-key-2026"},
    {"name": "Content-Type", "value": "application/json"}
]

bodies = {
    "WA: Notificar Creacion a Cliente": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.cliente_telefono || "").replace("+", "") + "@c.us",
    text: "👋 Hola " + $json.cliente_nombre + ", tu cita para *" + $json.titulo + "* ha sido agendada para el día *" + $json.fecha_inicio_fmt + "*.\\n\\n🔧 Técnico asignado: " + $json.tecnico_nombre + "\\n📍 Ubicación: " + $json.direccion_servicio
  })
}}""",
    "WA: Notificar Creacion a Tecnico": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.tecnico_telefono || "").replace("+", "") + "@c.us",
    text: "🛠️ *Nueva Asignación de Servicio*\\n\\nHola " + $json.tecnico_nombre + ", se te asignó la siguiente labor:\\n- Servicio: " + $json.titulo + "\\n- Fecha: " + $json.fecha_inicio_fmt + "\\n- Cliente: " + $json.cliente_nombre + " (" + $json.cliente_telefono + ")\\n- Ubicación: " + $json.direccion_servicio
  })
}}""",
    "WA: Notificar Creacion a Admin": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.admin_telefono || "+573004759860").replace("+", "") + "@c.us",
    text: "📋 *Cita Agendada Exitosamente*\\n\\n- ID Cita: " + $json.cita_id + "\\n- Cliente: " + $json.cliente_nombre + "\\n- Técnico: " + $json.tecnico_nombre + "\\n- Fecha: " + $json.fecha_inicio_fmt
  })
}}""",
    "WA: 24h Botones a Cliente": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.cliente_telefono || "").replace("+", "") + "@c.us",
    text: "⏰ *Recordatorio de Cita Tekvo*\\n\\nHola " + $json.cliente_nombre + ", tienes una cita programada para mañana a las " + $json.fecha_fmt + " para el servicio de *" + $json.titulo + "*.\\n\\n¿Confirmas tu asistencia para recibir al técnico?\\n\\n👉 Responde *1* o *SI* para Confirmar\\n👉 Responde *2* o *NO* para Cancelar cita"
  })
}}""",
    "WA: 24h Botones a Tecnico": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.tecnico_telefono || "").replace("+", "") + "@c.us",
    text: "🛠️ *Confirmación de Servicio Tekvo*\\n\\nHola " + $json.tecnico_nombre + ", te recordamos que tienes asignado el servicio *" + $json.titulo + "* para mañana " + $json.fecha_fmt + " con el cliente " + $json.cliente_nombre + ".\\n\\n¿Confirmas tu disponibilidad para atender este servicio?\\n\\n👉 Responde *1* o *SI* para Confirmar asistencia\\n👉 Responde *2* o *NO* para Indicar No Disponible"
  })
}}""",
    "WA: Responder a Quien Presiono Boton": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.sender_phone || "").replace("+", "") + "@c.us",
    text: ($json.accion_tomada === "CONFIRMAR" ? "🙌 ¡Muchas gracias! Tu respuesta ha sido registrada exitosamente como CONFIRMADA." : "⚠️ Tu respuesta ha sido registrada como CANCELADA / NO DISPONIBLE. El administrador ha sido notificado.")
  })
}}""",
    "WA: Alertar Tecnico de Cancelacion": """={{
  JSON.stringify({
    session: "default",
    chatId: ($json.tecnico_telefono || "").replace("+", "") + "@c.us",
    text: "⚠️ *Aviso de Cancelación*\\n\\nHola " + $json.tecnico_nombre + ", la cita de *" + $json.titulo + "* programada para mañana " + $json.fecha_fmt + " con el cliente " + $json.cliente_nombre + " ha sido CANCELADA por el cliente.\\n\\nTu agenda queda liberada en esa franja horaria."
  })
}}""",
    "WA: Notificar Estado Completo a Admin": """={{
  (() => {
    let msg = "";
    if ($json.estado === "CONFIRMADA") {
      msg = "🎉 *CITA 100% CONFIRMADA POR AMBOS*\\n\\n" +
            "- Cita: *" + $json.titulo + "* (" + $json.fecha_fmt + ")\\n" +
            "- Cliente: " + $json.cliente_nombre + " (✅)\\n" +
            "- Técnico: " + $json.tecnico_nombre + " (✅)\\n" +
            "Todo listo para la ejecución de mañana.";
    } else if ($json.rol_que_respondio === "CLIENTE" && $json.accion_tomada === "CANCELAR") {
      msg = "🚨 *ALERTA: CITA CANCELADA POR EL CLIENTE*\\n\\n" +
            "- Cita: *" + $json.titulo + "* (" + $json.fecha_fmt + ")\\n" +
            "- Cliente: " + $json.cliente_nombre + "\\n" +
            "- Técnico: " + $json.tecnico_nombre + "\\n" +
            "👉 El técnico ya fue notificado y liberado automáticamente.";
    } else if ($json.rol_que_respondio === "TECNICO" && $json.accion_tomada === "CANCELAR") {
      msg = "🚨 *URGENTE: TÉCNICO NO DISPONIBLE*\\n\\n" +
            "- Cita: *" + $json.titulo + "* (" + $json.fecha_fmt + ")\\n" +
            "- Técnico: " + $json.tecnico_nombre + "\\n" +
            "- Cliente: " + $json.cliente_nombre + " (" + $json.confirmacion_cliente + ")\\n" +
            "👉 ACCIÓN REQUERIDA: Reasignar técnico para este servicio de inmediato.";
    } else {
      msg = "🔔 *Actualización de Cita*\\n\\n" +
            "- Cita: *" + $json.titulo + "* (" + $json.fecha_fmt + ")\\n" +
            "- Quien respondió: " + $json.rol_que_respondio + " (✅ CONFIRMADO)\\n" +
            "• Cliente: " + $json.confirmacion_cliente + "\\n" +
            "• Técnico: " + $json.confirmacion_tecnico + "\\n" +
            "• Estado: " + $json.estado;
    }

    let phone = ($json.admin_telefono || "+573004759860").replace("+", "");
    return JSON.stringify({
      session: "default",
      chatId: phone + "@c.us",
      text: msg
    });
  })()
}}"""
}

for node in wf.get("nodes", []):
    name = node.get("name")
    if name in bodies:
        node["parameters"]["url"] = "http://citas_waha:3000/api/sendText"
        node["parameters"]["sendHeaders"] = True
        node["parameters"]["headerParameters"] = {"parameters": waha_headers}
        node["parameters"]["sendBody"] = True
        node["parameters"]["specifyBody"] = "json"
        node["parameters"]["jsonBody"] = bodies[name]

with open(workflow_path, "w", encoding="utf-8") as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully written to", workflow_path)
