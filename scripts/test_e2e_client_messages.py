import json
import urllib.request
import time
import pg8000.native

# 1. Connect to PostgreSQL
con = pg8000.native.Connection(
    user="citas_admin",
    password="CitasSuperSecretPassword2026!",
    host="citas_postgres",
    port=5432,
    database="citas_db"
)

cli_phone = "+573009990001"
tec_phone = "+573108880002"
adm_phone = "+573118198511"

print("1. Setting up test users and appointment in PostgreSQL...")
con.run("""
    INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol, activo)
    VALUES ('Cliente Privacy Test', 'privacy_cli@test.com', :p, 'CLIENTE', true)
    ON CONFLICT (email) DO UPDATE SET telefono_whatsapp = :p, activo = true;
""", p=cli_phone)

con.run("""
    INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol, activo)
    VALUES ('Tecnico Privacy Test', 'privacy_tec@test.com', :p, 'TECNICO', true)
    ON CONFLICT (email) DO UPDATE SET telefono_whatsapp = :p, activo = true;
""", p=tec_phone)

cli_id = con.run("SELECT id FROM usuarios WHERE email = 'privacy_cli@test.com'")[0][0]
tec_id = con.run("SELECT id FROM usuarios WHERE email = 'privacy_tec@test.com'")[0][0]
adm_id = con.run("SELECT id FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1")[0][0]

# Delete any existing test appointments
con.run("DELETE FROM citas WHERE cliente_id = :cid OR tecnico_id = :tid", cid=cli_id, tid=tec_id)

# Insert test appointment for tomorrow
cita_res = con.run("""
    INSERT INTO citas (
        cliente_id, tecnico_id, admin_id, titulo, descripcion, direccion_servicio,
        fecha_inicio, fecha_fin, estado, microsoft_event_id,
        confirmacion_cliente, confirmacion_tecnico,
        recordatorio_24h_enviado, recordatorio_cliente_enviado, recordatorio_tecnico_enviado
    ) VALUES (
        :cid, :tid, :aid, 'M.P (Preventivo)', 'Revisión y mantenimiento de prueba', 'Calle 100 # 15-20',
        NOW() + INTERVAL '1 day', NOW() + INTERVAL '1 day 2 hours', 'PENDIENTE', 'test_privacy_event_id',
        'PENDIENTE', 'PENDIENTE', true, true, true
    )
    RETURNING id;
""", cid=cli_id, tid=tec_id, aid=adm_id)
cita_id = cita_res[0][0]
con.close()
print(f"Appointment created with ID: {cita_id}")

def send_waha_webhook(payload):
    req = urllib.request.Request(
        "http://localhost:8000/webhook/waha",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8")

# Step 2: Client votes to CONFIRM
print("\n2. Sending Client confirmation vote...")
client_vote_payload = {
    "event": "poll.vote",
    "payload": {
        "vote": {
            "from": "573009990001@c.us",
            "selectedOptions": ["✅ SÍ, CONFIRMO"]
        }
    }
}
send_waha_webhook(client_vote_payload)
time.sleep(1)

# Step 3: Technician votes to CONFIRM
print("\n3. Sending Technician confirmation vote...")
tec_vote_payload = {
    "event": "poll.vote",
    "payload": {
        "vote": {
            "from": "573108880002@c.us",
            "selectedOptions": ["✅ SÍ, CONFIRMO"]
        }
    }
}
send_waha_webhook(tec_vote_payload)
time.sleep(1)

# Step 4: Technician INICIAR LABOR
print("\n4. Technician starts labor [▶️ INICIAR LABOR]...")
tec_start_payload = {
    "event": "poll.vote",
    "payload": {
        "vote": {
            "from": "573108880002@c.us",
            "selectedOptions": ["▶️ INICIAR LABOR"]
        }
    }
}
send_waha_webhook(tec_start_payload)
time.sleep(1)

# Step 5: Technician FINALIZAR LABOR
print("\n5. Technician finishes labor [⏹️ FINALIZAR LABOR]...")
tec_fin_payload = {
    "event": "poll.vote",
    "payload": {
        "vote": {
            "from": "573108880002@c.us",
            "selectedOptions": ["⏹️ FINALIZAR LABOR"]
        }
    }
}
send_waha_webhook(tec_fin_payload)
time.sleep(1)

# Step 6: Client submits CSAT rating
print("\n6. Client rates service [⭐ 5 - EXCELENTE]...")
cli_csat_payload = {
    "event": "poll.vote",
    "payload": {
        "vote": {
            "from": "573009990001@c.us",
            "selectedOptions": ["⭐ 5 - EXCELENTE"]
        }
    }
}
send_waha_webhook(cli_csat_payload)
time.sleep(1)

# Cleanup database
print("\n7. Cleaning up test data in PostgreSQL...")
con_clean = pg8000.native.Connection(
    user="citas_admin",
    password="CitasSuperSecretPassword2026!",
    host="citas_postgres",
    port=5432,
    database="citas_db"
)
con_clean.run("DELETE FROM citas WHERE cliente_id = :cid OR tecnico_id = :tid", cid=cli_id, tid=tec_id)
con_clean.run("DELETE FROM usuarios WHERE email IN ('privacy_cli@test.com', 'privacy_tec@test.com')")
con_clean.close()

print("\n🎉 Webhook simulation and database cleanup completed!")
