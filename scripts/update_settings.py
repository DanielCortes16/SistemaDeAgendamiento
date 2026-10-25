import json
import sqlite3

# 1. Load workflow
with open('/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json', 'r', encoding='utf-8') as f:
    wf = json.load(f)

# Enable execution saving so we can see every execution and node error
wf['settings'] = {
    'executionOrder': 'v1',
    'saveDataSuccessExecution': 'all',
    'saveDataErrorExecution': 'all',
    'saveManualExecutions': True,
    'callerPolicy': 'workflowsFromSameOwner'
}

# Fix ADMIN_WHATSAPP_NUMBER in WA: Notificar Creacion a Admin
for n in wf['nodes']:
    if n['name'] == 'WA: Notificar Creacion a Admin':
        body = n['parameters'].get('jsonBody', '')
        if '$env.ADMIN_WHATSAPP_NUMBER' in body:
            n['parameters']['jsonBody'] = body.replace('{{ $env.ADMIN_WHATSAPP_NUMBER }}', '+573004759860')
    if n['name'] == 'WA: Notificar Estado Completo a Admin':
        body = n['parameters'].get('jsonBody', '')
        if '$env.ADMIN_WHATSAPP_NUMBER' in body:
            n['parameters']['jsonBody'] = body.replace('{{ $env.ADMIN_WHATSAPP_NUMBER }}', '+573004759860')

# Save JSON
with open('/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json', 'w', encoding='utf-8') as f:
    json.dump(wf, f, indent=2, ensure_ascii=False)

# Sync into SQLite
nodes_str = json.dumps(wf['nodes'])
conn_str = json.dumps(wf['connections'])
settings_str = json.dumps(wf['settings'])

conn = sqlite3.connect('/tmp/database4.sqlite')
c = conn.cursor()
c.execute('UPDATE workflow_entity SET nodes = ?, connections = ?, settings = ? WHERE id = ?', 
          (nodes_str, conn_str, settings_str, 'qj1WPHW4zMgtoR8m'))
c.execute('UPDATE workflow_history SET nodes = ?, connections = ? WHERE workflowId = ? AND versionId = ?', 
          (nodes_str, conn_str, 'qj1WPHW4zMgtoR8m', 'c6b94c3b-644c-44e6-8a05-dbdd4c761967'))
conn.commit()
conn.close()
print("Settings enabled and SQLite updated!")
