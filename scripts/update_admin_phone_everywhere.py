import json
import sqlite3
import subprocess

wf_path = '/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json'
with open(wf_path, 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('3004759860', '3118198511')

with open(wf_path, 'w', encoding='utf-8') as f:
    f.write(text)

wf = json.loads(text)
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
print("n8n restarted with cleanly synced admin phone!")
