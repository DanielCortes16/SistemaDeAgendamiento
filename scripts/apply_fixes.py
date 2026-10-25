import json
import sqlite3
import subprocess

# 1. Load workflow JSON
wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

# 2. Fix Code: Parsear Boton Meta Multi-Rol to return [] on non-button messages
clean_button_parser = """const body = $input.first().json.body;

// 1. Manejo del Handshake inicial de Meta (GET verification)
if ($input.first().json.query && $input.first().json.query['hub.challenge']) {
  return [{
    json: {
      challenge: $input.first().json.query['hub.challenge'],
      is_challenge: true
    }
  }];
}

// 2. Procesamiento de botón presionado (POST)
try {
  const entry = body.entry?.[0];
  const change = entry?.changes?.[0];
  const message = change?.value?.messages?.[0];

  if (message && message.type === 'interactive' && message.interactive.type === 'button_reply') {
    const buttonId = message.interactive.button_reply.id;
    const senderPhone = '+' + message.from;
    
    // buttonId formato: "CONFIRMAR_CLIENTE_<UUID>", "CANCELAR_TECNICO_<UUID>", etc.
    const parts = buttonId.split('_');
    const action = parts[0]; // CONFIRMAR o CANCELAR
    const rol = parts[1];    // CLIENTE o TECNICO
    const citaId = parts.slice(2).join('_');

    return [{
      json: {
        is_challenge: false,
        valid_action: true,
        action: action,
        rol: rol,
        cita_id: citaId,
        sender_phone: senderPhone
      }
    }];
  }
} catch (e) {
  // Mensaje no interactivo o error de parseo
}

// Para recibos de entrega (sent, delivered, read) o mensajes no interactivos, terminar flujo limpiamente
return [];
"""

for n in wf['nodes']:
    if n['name'] == 'Code: Parsear Boton Meta Multi-Rol':
        n['parameters']['jsCode'] = clean_button_parser
    if n['name'] in ['WA: Notificar Creacion a Cliente', 'WA: Notificar Creacion a Tecnico', 'WA: Notificar Creacion a Admin']:
        n['continueOnFail'] = True

# 3. Save JSON
with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully updated.")

# 4. Stop n8n to flush WAL
subprocess.run(['docker', 'stop', 'citas_n8n'], check=True)

# 5. Copy database from container
db_path = '/tmp/database_sync.sqlite'
subprocess.run(['docker', 'cp', 'citas_n8n:/home/node/.n8n/database.sqlite', db_path], check=True)

# 6. Update SQLite
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

# 7. Copy updated DB back to container
subprocess.run(['docker', 'cp', db_path, 'citas_n8n:/home/node/.n8n/database.sqlite'], check=True)

# 8. Restart n8n
subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted with cleanly synced workflow!")
