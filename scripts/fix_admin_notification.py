import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    wf = json.load(f)

admin_body_expr = (
    "={{\n"
    "  (() => {\n"
    "    let msg = '';\n"
    "    if ($json.estado === 'CONFIRMADA') {\n"
    "      msg = '🎉 *CITA 100% CONFIRMADA POR AMBOS*\\n\\n' +\n"
    "            '- Cita: *' + $json.titulo + '* (' + $json.fecha_fmt + ')\\n' +\n"
    "            '- Cliente: ' + $json.cliente_nombre + ' (✅)\\n' +\n"
    "            '- Técnico: ' + $json.tecnico_nombre + ' (✅)\\n' +\n"
    "            'Todo listo para la ejecución de mañana.';\n"
    "    } else if ($json.rol_que_respondio === 'CLIENTE' && $json.accion_tomada === 'CANCELAR') {\n"
    "      msg = '🚨 *ALERTA: CITA CANCELADA POR EL CLIENTE*\\n\\n' +\n"
    "            '- Cita: *' + $json.titulo + '* (' + $json.fecha_fmt + ')\\n' +\n"
    "            '- Cliente: ' + $json.cliente_nombre + '\\n' +\n"
    "            '- Técnico: ' + $json.tecnico_nombre + '\\n' +\n"
    "            '👉 El técnico ya fue notificado y liberado automáticamente.';\n"
    "    } else if ($json.rol_que_respondio === 'TECNICO' && $json.accion_tomada === 'CANCELAR') {\n"
    "      msg = '🚨 *URGENTE: TÉCNICO NO DISPONIBLE*\\n\\n' +\n"
    "            '- Cita: *' + $json.titulo + '* (' + $json.fecha_fmt + ')\\n' +\n"
    "            '- Técnico: ' + $json.tecnico_nombre + '\\n' +\n"
    "            '- Cliente: ' + $json.cliente_nombre + ' (' + $json.confirmacion_cliente + ')\\n' +\n"
    "            '👉 ACCIÓN REQUERIDA: Reasignar técnico para este servicio de inmediato.';\n"
    "    } else {\n"
    "      msg = '🔔 *Actualización de Cita*\\n\\n' +\n"
    "            '- Cita: *' + $json.titulo + '* (' + $json.fecha_fmt + ')\\n' +\n"
    "            '- Quien respondió: ' + $json.rol_que_respondio + ' (✅ CONFIRMADO)\\n' +\n"
    "            '• Cliente: ' + $json.confirmacion_cliente + '\\n' +\n"
    "            '• Técnico: ' + $json.confirmacion_tecnico + '\\n' +\n"
    "            '• Estado: ' + $json.estado;\n"
    "    }\n"
    "\n"
    "    return JSON.stringify({\n"
    "      messaging_product: 'whatsapp',\n"
    "      to: ($json.admin_telefono || '+573004759860'),\n"
    "      type: 'text',\n"
    "      text: {\n"
    "        body: msg\n"
    "      }\n"
    "    });\n"
    "  })()\n"
    "}}"
)

for n in wf['nodes']:
    if n['name'] == 'WA: Notificar Estado Completo a Admin':
        n['parameters']['jsonBody'] = admin_body_expr
        n['continueOnFail'] = True
    if n['name'] in [
        'WA: Responder a Quien Presiono Boton',
        'WA: Alertar Tecnico de Cancelacion',
        'WA: 24h Botones a Cliente',
        'WA: 24h Botones a Tecnico'
    ]:
        n['continueOnFail'] = True

with open(wf_path, 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

print("Workflow JSON successfully updated.")

# Stop n8n to safely flush WAL
subprocess.run(['docker', 'stop', 'citas_n8n'], check=True)

# Copy DB out
db_path = '/tmp/database_sync_admin.sqlite'
subprocess.run(['docker', 'cp', 'citas_n8n:/home/node/.n8n/database.sqlite', db_path], check=True)

# Update SQLite
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

# Remove WAL/SHM from container volume before copying DB back
subprocess.run(['docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine', 'sh', '-c', 'rm -f /data/database.sqlite-wal /data/database.sqlite-shm'], check=True)

# Copy back
subprocess.run(['docker', 'cp', db_path, 'citas_n8n:/home/node/.n8n/database.sqlite'], check=True)
subprocess.run(['docker', 'run', '--rm', '-v', 'citas_n8n_data:/data', 'alpine', 'sh', '-c', 'chown -R 1000:1000 /data'], check=True)

# Start n8n
subprocess.run(['docker', 'start', 'citas_n8n'], check=True)
print("n8n restarted with clean Admin Notification fix!")
