import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
import hashlib
import json
import html
import uuid
import io
import zipfile
import xml.sax.saxutils
import time
from datetime import datetime, timedelta
import pg8000.native


def generate_excel_xml(rows):
    escape = xml.sax.saxutils.escape
    sheet_data = ['<sheetData>']
    for r_idx, row in enumerate(rows, start=1):
        sheet_data.append(f'<row r="{r_idx}">')
        for c_idx, val in enumerate(row, start=1):
            col_letter = chr(64 + c_idx) if c_idx <= 26 else f'A{chr(64 + c_idx - 26)}'
            cell_ref = f'{col_letter}{r_idx}'
            clean_str = escape(str(val if val is not None else ''))
            sheet_data.append(f'<c r="{cell_ref}" t="inlineStr"><is><t>{clean_str}</t></is></c>')
        sheet_data.append('</row>')
    sheet_data.append('</sheetData>')
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  {''.join(sheet_data)}
</worksheet>'''

    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>'''

    rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>'''

    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Citas Tekvo" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>'''

    wb_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>'''

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', rels)
        z.writestr('xl/workbook.xml', workbook_xml)
        z.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    return buf.getvalue()

TARGET_HOST = "http://citas_n8n:5678"
VERIFY_TOKEN = "token_secreto_para_validar_webhook_n8n_2026"

# Credenciales del Login Disuasivo
AUTH_USER = "servicio@tekvo.co"
AUTH_PASS = "3118198511"
SESSION_COOKIE_NAME = "tekvo_auth_session"
SESSION_TOKEN = hashlib.sha256(f"{AUTH_USER}:{AUTH_PASS}:tekvo_salt_2026".encode()).hexdigest()

DB_CONFIG = {
    "user": "citas_admin",
    "password": "CitasSuperSecretPassword2026!",
    "host": "postgres",
    "database": "citas_db",
    "port": 5432,
}


def get_db():
    return pg8000.native.Connection(**DB_CONFIG)


def normalize_phone(raw_phone):
    if not raw_phone:
        return "+573118198511"
    digits = "".join(ch for ch in raw_phone if ch.isdigit() or ch == "+")
    only_nums = "".join(ch for ch in digits if ch.isdigit())
    if len(only_nums) == 10 and only_nums.startswith("3"):
        return "+57" + only_nums
    if not digits.startswith("+") and only_nums:
        return "+" + only_nums
    return digits


def format_phone_display(phone):
    if not phone:
        return ""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("57") and len(digits) == 12:
        return f"+57 {digits[2:5]} {digits[5:]}"
    elif len(digits) == 10:
        return f"{digits[:3]} {digits[3:]}"
    return str(phone)


WAHA_BASE_URL = "http://citas_waha:3000"
WAHA_API_KEY = "citas-waha-key-2026"
_last_restart_attempt = 0.0


def get_waha_session_status():
    global _last_restart_attempt
    try:
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sessions/default",
            headers={"X-Api-Key": WAHA_API_KEY},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "UNKNOWN")

            # Auto-recuperación si el estado quedó en FAILED o STOPPED
            now = time.time()
            if status in ("FAILED", "STOPPED") and (now - _last_restart_attempt > 15):
                _last_restart_attempt = now
                print(f"[WAHA] Estado {status} detectado. Reiniciando sesión automáticamente...")
                restart_waha_session()

            return status, data.get("me", {})
    except Exception as e:
        return "DISCONNECTED", {"error": str(e)}


def get_waha_qr():
    try:
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/default/auth/qr",
            headers={"X-Api-Key": WAHA_API_KEY},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read()
    except Exception as e:
        print(f"[WAHA QR Error] {e}")
        return None


def restart_waha_session():
    try:
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sessions/default/restart",
            headers={"X-Api-Key": WAHA_API_KEY},
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, "Sesión reiniciada"
    except Exception as e:
        return False, str(e)


def logout_waha_session():
    try:
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sessions/default/logout",
            headers={"X-Api-Key": WAHA_API_KEY},
            data=b"",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, "Sesión desvinculada"
    except Exception as e:
        return False, str(e)


def resolve_lid_to_phone(lid):
    if not lid or "@lid" not in lid:
        return None
    try:
        url = f"{WAHA_BASE_URL}/api/default/lids/{urllib.parse.quote(lid)}"
        req = urllib.request.Request(url, headers={"X-Api-Key": WAHA_API_KEY}, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pn = data.get("pn")
            if pn:
                clean = "".join(c for c in pn.split("@")[0] if c.isdigit())
                if clean:
                    return normalize_phone(clean)
    except Exception as e:
        print(f"[WAHA Resolve LID Error] {lid}: {e}", flush=True)
    return None


def send_waha_text(phone, text):
    try:
        clean_digits = "".join(c for c in phone if c.isdigit())
        chat_id = f"{clean_digits}@c.us"
        payload = {
            "session": "default",
            "chatId": chat_id,
            "text": text,
        }
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sendText",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Api-Key": WAHA_API_KEY,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"[WAHA Text Sent] to {phone} ({chat_id}): {text[:60]}...", flush=True)
            return True, resp.read().decode("utf-8")
    except Exception as e:
        print(f"[WAHA Send Error] to {phone}: {e}", flush=True)
        return False, str(e)


def fetch_tecnicos_and_citas(filters=None):
    if filters is None:
        filters = {}
    tecnicos = []
    citas = []
    clientes_list = []
    admin_tel = "+573118198511"
    try:
        con = get_db()
        rows_tec = con.run(
            "SELECT id, nombre, email, telefono_whatsapp FROM usuarios "
            "WHERE rol = 'TECNICO' AND activo = true ORDER BY nombre ASC"
        )
        for r in rows_tec:
            tecnicos.append({
                "id": str(r[0]),
                "nombre": r[1],
                "email": r[2],
                "telefono": r[3],
            })

        rows_adm = con.run(
            "SELECT telefono_whatsapp FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1"
        )
        if rows_adm:
            admin_tel = rows_adm[0][0]

        rows_cli = con.run(
            "SELECT DISTINCT nombre FROM usuarios WHERE rol = 'CLIENTE' AND activo = true ORDER BY nombre ASC"
        )
        clientes_list = [r[0] for r in rows_cli if r[0]]

        where_clauses = []
        params = {}
        if filters.get("fecha_desde"):
            where_clauses.append("(c.fecha_inicio AT TIME ZONE 'America/Bogota')::date >= :fecha_desde::date")
            params["fecha_desde"] = filters["fecha_desde"]
        if filters.get("fecha_hasta"):
            where_clauses.append("(c.fecha_inicio AT TIME ZONE 'America/Bogota')::date <= :fecha_hasta::date")
            params["fecha_hasta"] = filters["fecha_hasta"]
        if filters.get("cliente_query"):
            where_clauses.append("(LOWER(cli.nombre) LIKE :cli_q OR cli.telefono_whatsapp LIKE :cli_q)")
            params["cli_q"] = f"%{filters['cliente_query'].lower().strip()}%"
        if filters.get("tecnico_id"):
            where_clauses.append("c.tecnico_id::text = :tecnico_id")
            params["tecnico_id"] = filters["tecnico_id"]
        if filters.get("estado"):
            where_clauses.append("c.estado::text = :estado")
            params["estado"] = filters["estado"]

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        sql_citas = (
            "SELECT c.id, c.titulo, "
            "TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS f_ini, "
            "TO_CHAR(c.fecha_fin AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS f_fin, "
            "c.estado, c.confirmacion_cliente, c.confirmacion_tecnico, "
            "cli.nombre, cli.telefono_whatsapp, tec.nombre, tec.telefono_whatsapp, "
            "c.direccion_servicio, c.descripcion, c.microsoft_event_id "
            "FROM citas c "
            "JOIN usuarios cli ON c.cliente_id = cli.id "
            "JOIN usuarios tec ON c.tecnico_id = tec.id "
            f"{where_sql} "
            "ORDER BY c.created_at DESC LIMIT 200"
        )
        rows_citas = con.run(sql_citas, **params)
        for r in rows_citas:
            citas.append({
                "id": str(r[0]),
                "titulo": r[1],
                "fecha": r[2],
                "fecha_fin": r[3],
                "estado": r[4],
                "conf_cli": r[5],
                "conf_tec": r[6],
                "cliente": r[7],
                "cli_tel": r[8],
                "tecnico": r[9],
                "tec_tel": r[10],
                "direccion": r[11],
                "descripcion": r[12] or "",
                "microsoft_event_id": r[13] or "",
            })
        con.close()
    except Exception as e:
        print(f"[Meta Bridge DB Error] {e}")
    return tecnicos, citas, clientes_list, admin_tel


def delete_cita_by_id(cita_id):
    try:
        con = get_db()
        con.run("DELETE FROM citas WHERE id = :id", id=cita_id)
        con.close()
        return True, "Cita eliminada correctamente."
    except Exception as e:
        print(f"[Meta Bridge DB Delete Error] {e}")
        return False, str(e)


def delete_tecnico_by_id(tecnico_id):
    try:
        con = get_db()
        citas_count = con.run("SELECT COUNT(*) FROM citas WHERE tecnico_id = :id", id=tecnico_id)
        count = citas_count[0][0] if citas_count else 0
        if count > 0:
            # Tiene historial de citas: desactivación lógica para preservar integridad
            con.run("UPDATE usuarios SET activo = false WHERE id = :id", id=tecnico_id)
            con.close()
            return True, f"Técnico retirado del equipo (desactivado para nuevas citas porque tiene {count} servicio(s) en su historial)."
        else:
            # No tiene citas asociadas: eliminación física completa
            con.run("DELETE FROM usuarios WHERE id = :id", id=tecnico_id)
            con.close()
            return True, "Técnico eliminado completamente del sistema."
    except Exception as e:
        print(f"[Meta Bridge DB Delete Tecnico Error] {e}")
        return False, str(e)


def render_login_page(error_msg=None):
    error_html = ""
    if error_msg:
        error_html = f"""
        <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px;border-radius:8px;margin-bottom:16px;color:#991b1b;font-size:14px;">
            {html.escape(error_msg)}
        </div>
        """
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Iniciar Sesión | Tekvo Citas</title>
    <style>
        * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background: #0f172a; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 16px; color: #1e293b; }}
        .login-card {{ background: #fff; width: 100%; max-width: 400px; border-radius: 16px; padding: 32px 26px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); }}
        .logo-badge {{ width: 52px; height: 52px; background: #eff6ff; color: #2563eb; border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 26px; margin: 0 auto 14px auto; }}
        h1 {{ text-align: center; margin: 0 0 6px 0; font-size: 22px; color: #0f172a; }}
        .subtitle {{ text-align: center; color: #64748b; font-size: 14px; margin-bottom: 24px; }}
        .form-group {{ margin-bottom: 16px; }}
        label {{ display: block; font-weight: 600; font-size: 13px; margin-bottom: 6px; color: #334155; }}
        input {{ width: 100%; padding: 12px 14px; border: 1px solid #cbd5e1; border-radius: 10px; font-size: 15px; background: #f8fafc; }}
        input:focus {{ outline: none; border-color: #2563eb; background: #fff; }}
        .btn-login {{ width: 100%; background: #2563eb; color: #fff; border: none; padding: 13px; border-radius: 10px; font-size: 16px; font-weight: 700; cursor: pointer; margin-top: 6px; }}
        .btn-login:hover {{ background: #1d4ed8; }}
    </style>
</head>
<body>
    <div class="login-card">
        <div class="logo-badge">🔒</div>
        <h1>Portal de Citas Tekvo</h1>
        <div class="subtitle">Ingresa tus credenciales de administrador</div>
        {error_html}
        <form method="POST" action="/agendar/login">
            <div class="form-group">
                <label>Correo Electrónico</label>
                <input type="email" name="username" required placeholder="servicio@tekvo.co" autocomplete="username">
            </div>
            <div class="form-group">
                <label>Contraseña</label>
                <input type="password" name="password" required placeholder="••••••••••" autocomplete="current-password">
            </div>
            <button type="submit" class="btn-login">Ingresar al Portal</button>
        </form>
    </div>
</body>
</html>"""


def render_whatsapp_page(status, me=None):
    if me is None:
        me = {}

    phone_raw = me.get("id", "") if me else ""
    phone_clean = phone_raw.split("@")[0] if "@" in phone_raw else phone_raw
    phone_formatted = f"+{phone_clean}" if phone_clean else ""
    push_name = me.get("pushName", "") if me else ""

    if status == "WORKING":
        status_badge = '<div class="status-pill connected"><span class="pulse"></span> 🟢 En línea y Operativo</div>'
        content_box = f"""
        <div class="connected-box">
            <div style="font-size:13px;color:#15803d;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;">Número Conectado</div>
            <div class="phone-display">📱 {html.escape(phone_formatted)}</div>
            {f'<div style="font-size:14px;color:#334155;margin-top:4px;">Nombre: <strong>{html.escape(push_name)}</strong></div>' if push_name else ''}
            <div style="font-size:13px;color:#475569;margin-top:12px;padding-top:12px;border-top:1px solid #bbf7d0;">
                ✅ Las confirmaciones automáticas y recordatorios de 24h se están enviando directamente desde este WhatsApp.
            </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;margin-top:16px;">
            <form method="POST" action="/agendar/whatsapp/restart">
                <button type="submit" class="btn-action btn-secondary" style="margin:0;" title="Reconecta la sesión en caso de desconexión sin perder la vinculación actual">🔄 Reconectar Sesión (Sin QR)</button>
            </form>
            <form method="POST" action="/agendar/whatsapp/logout" onsubmit="return confirm('⚠️ ATENCIÓN: ¿Seguro que deseas desvincular este número de WhatsApp?\n\nAl desvincular, la sesión se cerrará de forma permanente y será OBLIGATORIO escanear el código QR con el nuevo teléfono físico para volver a conectar.');">
                <button type="submit" class="btn-action btn-danger" style="margin:0;">⚠️ Desvincular / Cambiar Teléfono</button>
            </form>
        </div>
        """
    elif status == "SCAN_QR_CODE":
        status_badge = '<div class="status-pill waiting">🟡 Esperando Escaneo de QR</div>'
        content_box = f"""
        <div class="qr-box">
            <img id="qrImg" class="qr-img" src="/agendar/whatsapp/qr?t={int(datetime.now().timestamp())}" alt="Código QR WhatsApp" onerror="handleQRError(this)">
            <div id="qrLoadingMsg" style="display:none;padding:80px 20px;font-size:14px;color:#64748b;line-height:1.6;">
                ⏳ Generando código QR actualizado...<br><span style="font-size:12px;color:#94a3b8;">Por favor espera un momento</span>
            </div>
            <div style="font-size:12px;color:#64748b;margin-top:10px;">
                📲 Código QR activo para vincular
            </div>
        </div>
        <div class="instructions">
            <strong style="color:#0f172a;display:block;margin-bottom:6px;">📲 Cómo vincular en 4 pasos:</strong>
            <ol>
                <li>Abre <strong>WhatsApp</strong> en el teléfono (+57 311 819 8511).</li>
                <li>Toca <strong>Menú (⋮)</strong> en Android o <strong>Configuración</strong> en iPhone.</li>
                <li>Selecciona <strong>Dispositivos vinculados</strong>.</li>
                <li>Toca <strong>Vincular un dispositivo</strong> y apunta tu cámara a este código QR.</li>
            </ol>
        </div>
        <div style="display:flex;gap:10px;">
            <button type="button" class="btn-action" onclick="refreshQR()">🔄 Refrescar Código QR</button>
            <form method="POST" action="/agendar/whatsapp/restart" style="flex:1;">
                <button type="submit" class="btn-action btn-secondary" style="margin-top:0;">⚡ Reiniciar Motor</button>
            </form>
        </div>
        """
    elif status in ("FAILED", "STOPPED"):
        status_badge = '<div class="status-pill waiting" style="background:#fee2e2;color:#dc2626;">❌ Conexión Interrumpida / Expirada</div>'
        content_box = f"""
        <div style="background:#fef2f2;border-radius:14px;padding:26px 20px;margin-bottom:20px;border:1px solid #fecaca;text-align:center;">
            <div style="font-size:36px;margin-bottom:8px;">⚠️</div>
            <div style="font-weight:700;font-size:16px;color:#991b1b;">El escaneo del código QR expiró o falló</div>
            <div style="font-size:14px;color:#7f1d1d;margin-top:6px;line-height:1.5;">
                Ocurrió una intermitencia al vincular con el teléfono. El sistema se reiniciará automáticamente, o puedes presionar el botón abajo para obtener un código QR nuevo inmediatamente.
            </div>
        </div>
        <form method="POST" action="/agendar/whatsapp/restart">
            <button type="submit" class="btn-action" style="background:#dc2626;">🔄 Generar Nuevo Código QR</button>
        </form>
        """
    else:
        status_badge = f'<div class="status-pill starting">⏳ Estado: {html.escape(status)}</div>'
        content_box = f"""
        <div style="background:#f8fafc;border-radius:14px;padding:32px 20px;margin-bottom:24px;border:1px solid #e2e8f0;">
            <div style="font-size:32px;margin-bottom:12px;">⏳</div>
            <div style="font-weight:700;font-size:16px;color:#0f172a;">Iniciando motor de WhatsApp Web...</div>
            <div style="font-size:14px;color:#64748b;margin-top:6px;">Esto suele tardar unos segundos mientras carga el código QR.</div>
        </div>
        <form method="POST" action="/agendar/whatsapp/restart">
            <button type="submit" class="btn-action btn-secondary">⚡ Forzar Reinicio del Motor</button>
        </form>
        """

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vinculación de WhatsApp | Tekvo</title>
    <style>
        * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background: #0f172a; margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px 12px; color: #1e293b; }}
        .card {{ background: #fff; width: 100%; max-width: 500px; border-radius: 20px; padding: 32px 26px; box-shadow: 0 20px 40px rgba(0,0,0,0.3); text-align: center; }}
        .back-link {{ display: inline-flex; align-items: center; gap: 6px; color: #64748b; text-decoration: none; font-size: 14px; font-weight: 600; margin-bottom: 20px; transition: color 0.2s; }}
        .back-link:hover {{ color: #2563eb; }}
        .logo-badge {{ width: 56px; height: 56px; background: #dcfce7; color: #16a34a; border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 30px; margin: 0 auto 14px auto; }}
        h1 {{ margin: 0 0 6px 0; font-size: 22px; color: #0f172a; }}
        .subtitle {{ color: #64748b; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }}
        
        .status-pill {{ display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 20px; font-size: 13px; font-weight: 700; margin-bottom: 20px; }}
        .status-pill.connected {{ background: #dcfce7; color: #15803d; }}
        .status-pill.waiting {{ background: #fef3c7; color: #b45309; }}
        .status-pill.starting {{ background: #eff6ff; color: #1d4ed8; }}
        
        .qr-box {{ background: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 16px; padding: 18px; margin: 0 auto 20px auto; display: inline-block; min-width: 250px; min-height: 250px; }}
        .qr-img {{ width: 250px; height: 250px; border-radius: 10px; background: #fff; display: block; margin: 0 auto; box-shadow: 0 4px 10px rgba(0,0,0,0.06); }}
        
        .instructions {{ text-align: left; background: #f8fafc; border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; font-size: 14px; color: #334155; line-height: 1.6; border: 1px solid #e2e8f0; }}
        .instructions ol {{ margin: 8px 0 0 0; padding-left: 20px; }}
        .instructions li {{ margin-bottom: 6px; }}
        
        .btn-action {{ display: inline-flex; align-items: center; justify-content: center; gap: 8px; width: 100%; background: #2563eb; color: #fff; border: none; padding: 12px; border-radius: 10px; font-size: 15px; font-weight: 700; cursor: pointer; text-decoration: none; transition: all 0.2s; }}
        .btn-action:hover {{ background: #1d4ed8; }}
        .btn-secondary {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }}
        .btn-secondary:hover {{ background: #e2e8f0; color: #0f172a; }}
        .btn-danger {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }}
        .btn-danger:hover {{ background: #fecaca; color: #991b1b; }}
        
        .connected-box {{ background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 14px; padding: 20px; margin-bottom: 20px; text-align: left; }}
        .phone-display {{ font-size: 20px; font-weight: 700; color: #166534; margin: 6px 0; }}
        .pulse {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #22c55e; animation: pulseDot 1.5s infinite; }}
        @keyframes pulseDot {{ 0% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.4; transform: scale(1.3); }} 100% {{ opacity: 1; transform: scale(1); }} }}
    </style>
</head>
<body>
    <div class="card">
        <a href="/agendar" class="back-link">← Volver al Portal de Agendamiento</a>
        <div class="logo-badge">💬</div>
        <h1>WhatsApp de la Empresa</h1>
        <div class="subtitle">Conexión directa vía WhatsApp Web (sin perder tu cuenta ni requerir otra SIM)</div>
        
        {status_badge}
        {content_box}
    </div>

    <script>
        const initialStatus = "{status}";
        const qrImg = document.getElementById("qrImg");

        function handleQRError(img) {{
            if (!img) return;
            img.style.display = 'none';
            const msg = document.getElementById('qrLoadingMsg');
            if (msg) msg.style.display = 'block';
            setTimeout(refreshQR, 2500);
        }}

        function refreshQR() {{
            if (qrImg) {{
                const msg = document.getElementById('qrLoadingMsg');
                qrImg.style.display = 'block';
                if (msg) msg.style.display = 'none';
                qrImg.src = "/agendar/whatsapp/qr?t=" + new Date().getTime();
            }}
        }}

        async function pollStatus() {{
            try {{
                const res = await fetch("/agendar/whatsapp/status");
                if (res.ok) {{
                    const data = await res.json();
                    if (data.status !== initialStatus) {{
                        window.location.reload();
                    }}
                }}
            }} catch (e) {{}}
        }}

        setInterval(pollStatus, 3000);
    </script>
</body>
</html>"""


def render_agendar_page(success_data=None, error_msg=None, filters=None):
    if filters is None:
        filters = {}
    tecnicos, citas, clientes_list, admin_tel = fetch_tecnicos_and_citas(filters)

    # Si acabamos de agendar una cita, asegurar que esté al inicio de la tabla y destacada
    recent_mid = success_data.get("microsoft_event_id") if success_data else None
    if recent_mid:
        found_in_list = False
        for c in citas:
            if c.get("microsoft_event_id") == recent_mid:
                c["reciente"] = True
                found_in_list = True
                citas.remove(c)
                citas.insert(0, c)
                break
        if not found_in_list and success_data:
            citas.insert(0, {
                "id": "",
                "titulo": success_data["titulo"],
                "fecha": success_data.get("fecha_label", ""),
                "fecha_fin": "",
                "estado": "PENDIENTE",
                "conf_cli": "PENDIENTE",
                "conf_tec": "PENDIENTE",
                "cliente": success_data["cliente_nombre"],
                "cli_tel": success_data["cliente_telefono"],
                "tecnico": success_data["tecnico_nombre"],
                "tec_tel": "",
                "direccion": "",
                "descripcion": "",
                "microsoft_event_id": recent_mid,
                "reciente": True,
            })

    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    wa_status, _ = get_waha_session_status()
    if wa_status == "WORKING":
        wa_badge_html = """
        <a href="/agendar/whatsapp" title="WhatsApp Conectado y Operativo" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;background:#dcfce7;color:#15803d;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:700;border:1px solid #86efac;">
            <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;"></span> 🟢 WhatsApp Conectado
        </a>
        """
    else:
        wa_badge_html = """
        <a href="/agendar/whatsapp" title="Vincular WhatsApp de la Empresa" style="text-decoration:none;display:inline-flex;align-items:center;gap:6px;background:#fef3c7;color:#b45309;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:700;border:1px solid #fcd34d;">
            <span style="width:8px;height:8px;border-radius:50%;background:#f59e0b;"></span> ⚠️ Vincular WhatsApp (QR)
        </a>
        """

    tec_options_html = ""
    tec_table_rows_html = ""
    for t in tecnicos:
        val = html.escape(f"{t['nombre']}|{t['email']}")
        label = html.escape(f"{t['nombre']} ({format_phone_display(t['telefono'])})")
        tec_options_html += f'<option value="{val}">{label}</option>\n'
        t_nombre_escaped = html.escape(t['nombre']).replace("'", "\\'")
        tec_table_rows_html += f"""
        <tr>
            <td><strong>{html.escape(t['nombre'])}</strong></td>
            <td>{html.escape(format_phone_display(t['telefono']))}</td>
            <td style="text-align:center;">
                <button type="button" class="btn-del" title="Eliminar técnico"
                        onclick="confirmDeleteTecnico('{html.escape(t['id'])}', '{t_nombre_escaped}')">
                    🗑️
                </button>
            </td>
        </tr>
        """
    tec_options_html += '<option value="__NUEVO__">➕ Agregar nuevo técnico...</option>'

    tec_filter_options = '<option value="">-- Todos los técnicos --</option>\n'
    for t in tecnicos:
        sel = 'selected' if str(t['id']) == str(filters.get('tecnico_id', '')) else ''
        tec_filter_options += f'<option value="{html.escape(t["id"])}" {sel}>{html.escape(t["nombre"])}</option>\n'

    cli_datalist_options = ""
    for c_nom in clientes_list:
        cli_datalist_options += f'<option value="{html.escape(c_nom)}"></option>\n'

    est_filter_options = '<option value="">-- Todos los estados --</option>\n'
    for est in ["PENDIENTE", "CONFIRMADA", "CANCELADA", "REQUIERE_REASIGNACION"]:
        sel = 'selected' if est == filters.get('estado', '') else ''
        est_filter_options += f'<option value="{est}" {sel}>{est}</option>\n'

    excel_query_params = urllib.parse.urlencode({
        k: v for k, v in filters.items() if v
    })
    excel_export_url = f"/agendar/exportar?{excel_query_params}" if excel_query_params else "/agendar/exportar"

    citas_rows_html = ""
    for c in citas:
        badge_color = "#f59e0b"
        if c["estado"] == "CONFIRMADA":
            badge_color = "#10b981"
        elif c["estado"] == "CANCELADA":
            badge_color = "#ef4444"
        elif c["estado"] == "REQUIERE_REASIGNACION":
            badge_color = "#f97316"

        c_titulo_escaped = html.escape(c['titulo']).replace("'", "\\'")
        c_cliente_escaped = html.escape(c['cliente']).replace("'", "\\'")

        is_recent = c.get("reciente", False)
        row_style = 'style="background:#f0fdf4;border-left:4px solid #10b981;"' if is_recent else ''
        recent_badge = ' <span style="background:#10b981;color:#fff;font-size:10px;padding:2px 6px;border-radius:10px;font-weight:700;">✨ Recién Creada</span>' if is_recent else ''

        del_btn_html = ""
        if c.get('id'):
            del_btn_html = f"""<button type="button" class="btn-del" title="Eliminar cita"
                        onclick="confirmDeleteCita('{html.escape(c['id'])}', '{c_titulo_escaped}', '{c_cliente_escaped}', '{html.escape(c['fecha'])}')">
                    🗑️
                </button>"""

        citas_rows_html += f"""
        <tr {row_style}>
            <td>
                <strong>{html.escape(c['titulo'])}</strong>{recent_badge}<br>
                <small style="color:#64748b">🗓️ {html.escape(c['fecha'])}</small>
            </td>
            <td>
                {html.escape(c['cliente'])}<br>
                <small style="color:#64748b">📞 {html.escape(format_phone_display(c['cli_tel']))}</small>
            </td>
            <td>
                {html.escape(c['tecnico'])}<br>
                <small style="color:#64748b">📞 {html.escape(format_phone_display(c['tec_tel']))}</small>
            </td>
            <td>
                <span style="background:{badge_color};color:#fff;padding:3px 8px;border-radius:12px;font-size:12px;font-weight:600;">
                    {html.escape(c['estado'])}
                </span>
                <div style="font-size:11px;color:#475569;margin-top:4px;">
                    Cli: {html.escape(c['conf_cli'] or 'PENDIENTE')} | Téc: {html.escape(c['conf_tec'] or 'PENDIENTE')}
                </div>
            </td>
            <td style="text-align:center;">
                {del_btn_html}
            </td>
        </tr>
        """

    alert_banner = ""
    if error_msg:
        alert_banner = f"""
        <div style="background:#fef2f2;border-left:4px solid #ef4444;padding:16px;border-radius:8px;margin-bottom:20px;color:#991b1b;">
            <strong>⚠️ {html.escape(error_msg)}</strong>
        </div>
        """
    elif success_data:
        alert_banner = f"""
        <div style="background:#ecfdf5;border:2px solid #10b981;padding:20px;border-radius:12px;margin-bottom:24px;color:#065f46;">
            <h3 style="margin-top:0;color:#047857;">✅ ¡Cita Agendada y 3 WhatsApps Enviados!</h3>
            <p style="margin:6px 0;"><strong>Servicio:</strong> {html.escape(success_data['titulo'])}</p>
            <p style="margin:6px 0;"><strong>Cliente:</strong> {html.escape(success_data['cliente_nombre'])} ({html.escape(format_phone_display(success_data['cliente_telefono']))})</p>
            <p style="margin:6px 0;"><strong>Técnico:</strong> {html.escape(success_data['tecnico_nombre'])}</p>
            <p style="margin:6px 0;"><strong>Fecha y Hora:</strong> {html.escape(success_data['fecha_label'])}</p>
            <div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap;">
                <a href="{html.escape(success_data['outlook_url'])}" target="_blank"
                   style="background:#0078d4;color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:600;display:inline-block;">
                   📅 Guardar en Calendario Outlook (Servicio@tekvo.co)
                </a>
                <a href="{html.escape(success_data['ics_url'])}"
                   style="background:#334155;color:#fff;text-decoration:none;padding:12px 18px;border-radius:8px;font-weight:600;display:inline-block;">
                   📥 Descargar archivo .ICS (Celular / Outlook App)
                </a>
            </div>
        </div>
        """

    f_desde = html.escape(filters.get("fecha_desde", ""))
    f_hasta = html.escape(filters.get("fecha_hasta", ""))
    cli_q = html.escape(filters.get("cliente_query", ""))

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agendamiento de Citas | Tekvo</title>
    <style>
        * {{ box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        body {{ background: #f1f5f9; margin: 0; padding: 20px 12px; color: #1e293b; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .card {{ background: #fff; border-radius: 14px; padding: 24px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); margin-bottom: 24px; }}
        .top-bar {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; flex-wrap: wrap; }}
        h1 {{ margin: 0 0 6px 0; font-size: 24px; color: #0f172a; }}
        .subtitle {{ color: #64748b; font-size: 14px; margin-bottom: 20px; }}
        .logout-link {{ font-size: 13px; color: #64748b; text-decoration: none; padding: 6px 12px; border: 1px solid #cbd5e1; border-radius: 8px; }}
        .logout-link:hover {{ background: #f8fafc; color: #0f172a; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        @media (max-width: 600px) {{ .grid {{ grid-template-columns: 1fr; }} }}
        .form-group {{ margin-bottom: 16px; }}
        label {{ display: block; font-weight: 600; font-size: 14px; margin-bottom: 6px; color: #334155; }}
        input, select, textarea {{ width: 100%; padding: 11px 12px; border: 1px solid #cbd5e1; border-radius: 8px; font-size: 15px; background: #f8fafc; }}
        input:focus, select:focus, textarea:focus {{ outline: none; border-color: #2563eb; background: #fff; }}
        .btn-submit {{ width: 100%; background: #2563eb; color: #fff; border: none; padding: 14px; border-radius: 10px; font-size: 16px; font-weight: 700; cursor: pointer; transition: background 0.2s; }}
        .btn-submit:hover {{ background: #1d4ed8; }}
        .new-tech-box {{ background: #eff6ff; border: 1px dashed #3b82f6; padding: 16px; border-radius: 10px; margin-bottom: 16px; display: none; }}
        
        /* Filtros y Reporte */
        .filter-panel {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px; margin-bottom: 20px; }}
        .filter-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; align-items: flex-end; }}
        .btn-filter {{ background: #2563eb; color: #fff; border: none; padding: 11px 16px; border-radius: 8px; font-weight: 600; cursor: pointer; font-size: 14px; height: 42px; display: flex; align-items: center; justify-content: center; gap: 6px; }}
        .btn-filter:hover {{ background: #1d4ed8; }}
        .btn-reset {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 11px 14px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600; height: 42px; display: flex; align-items: center; justify-content: center; }}
        .btn-reset:hover {{ background: #e2e8f0; color: #1e293b; }}
        .btn-excel {{ background: #107c41; color: #fff; border: none; padding: 11px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-flex; align-items: center; gap: 8px; box-shadow: 0 2px 6px rgba(16, 124, 65, 0.3); transition: all 0.2s; }}
        .btn-excel:hover {{ background: #0c6133; transform: translateY(-1px); color: #fff; }}
        .table-header-flex {{ display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px; }}
        
        /* Tabla */
        table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        th, td {{ text-align: left; padding: 12px 10px; border-bottom: 1px solid #e2e8f0; }}
        th {{ color: #475569; font-size: 12px; text-transform: uppercase; background: #f8fafc; font-weight: 700; }}
        tr:hover td {{ background: #fbfcfe; }}
        .btn-del {{ background: #fee2e2; border: 1px solid #fca5a5; color: #b91c1c; border-radius: 8px; padding: 6px 10px; cursor: pointer; font-size: 14px; transition: all 0.2s; }}
        .btn-del:hover {{ background: #ef4444; color: #fff; border-color: #dc2626; }}

        /* Modal de Confirmación */
        .modal-overlay {{ position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(15, 23, 42, 0.6); display: none; align-items: center; justify-content: center; z-index: 9999; padding: 16px; backdrop-filter: blur(2px); }}
        .modal-box {{ background: #fff; border-radius: 16px; max-width: 440px; width: 100%; padding: 24px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2); animation: modalIn 0.2s ease-out; }}
        @keyframes modalIn {{ from {{ opacity: 0; transform: scale(0.95); }} to {{ opacity: 1; transform: scale(1); }} }}
        .modal-title {{ margin: 0 0 10px 0; font-size: 18px; color: #991b1b; display: flex; align-items: center; gap: 8px; }}
        .modal-desc {{ color: #475569; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }}
        .modal-actions {{ display: flex; justify-content: flex-end; gap: 10px; }}
        .btn-modal-cancel {{ background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; }}
        .btn-modal-confirm {{ background: #dc2626; color: #fff; border: none; padding: 10px 18px; border-radius: 8px; font-weight: 700; cursor: pointer; }}
        .btn-modal-confirm:hover {{ background: #b91c1c; }}
    </style>
</head>
<body>
<div class="container">
    <div class="card">
        <div class="top-bar">
            <div>
                <h1>📅 Agendar Nueva Cita — Tekvo</h1>
                <div class="subtitle">Organizador: <strong>servicio@tekvo.co</strong> | Alertas WhatsApp Admin: {html.escape(admin_tel)}</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
                {wa_badge_html}
                <a href="/agendar/logout" class="logout-link">🔒 Cerrar sesión</a>
            </div>
        </div>

        {alert_banner}

        <form method="POST" action="/agendar">
            <div class="form-group">
                <label>Título o Servicio a Realizar *</label>
                <input type="text" name="titulo" required placeholder="Ej: Instalación Cámara de Seguridad / Mantenimiento">
            </div>

            <div class="grid">
                <div class="form-group">
                    <label>Nombre del Cliente *</label>
                    <input type="text" name="cliente_nombre" required placeholder="Ej: María Fernanda Gómez">
                </div>
                <div class="form-group">
                    <label>WhatsApp del Cliente *</label>
                    <input type="tel" name="cliente_telefono" id="cliente_telefono" required 
                           placeholder="Ej: 300 4759860" inputmode="numeric" autocomplete="tel">
                </div>
            </div>

            <div class="form-group">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                    <label style="margin-bottom:0;">Técnico Asignado *</label>
                    <button type="button" onclick="openTechModal()" 
                            style="background:none;border:none;color:#2563eb;font-size:13px;font-weight:600;cursor:pointer;padding:0;text-decoration:underline;">
                        👥 Administrar / Eliminar Técnicos
                    </button>
                </div>
                <select name="tecnico_selector" id="tecnico_selector" onchange="toggleNewTech(this.value)" required>
                    {tec_options_html}
                </select>
            </div>

            <div class="new-tech-box" id="new_tech_box">
                <div style="font-weight:700;color:#1e40af;margin-bottom:10px;">➕ Datos del Nuevo Técnico (se guardará para futuras citas)</div>
                <div class="grid">
                    <div class="form-group" style="margin-bottom:0;">
                        <label>Nombre del Técnico *</label>
                        <input type="text" name="nuevo_tecnico_nombre" id="nuevo_tecnico_nombre" placeholder="Ej: Pedro Ramírez">
                    </div>
                    <div class="form-group" style="margin-bottom:0;">
                        <label>WhatsApp del Técnico *</label>
                        <input type="tel" name="nuevo_tecnico_telefono" id="nuevo_tecnico_telefono" 
                               placeholder="Ej: 310 1234567" inputmode="numeric" autocomplete="tel">
                    </div>
                </div>
            </div>

            <div class="grid">
                <div class="form-group">
                    <label>Fecha del Servicio *</label>
                    <input type="date" name="fecha" value="{tomorrow}" required>
                </div>
                <div class="form-group">
                    <label>Hora del Servicio *</label>
                    <input type="time" name="hora_inicio" value="09:00" required>
                </div>
            </div>

            <div class="form-group">
                <label>Dirección del Servicio *</label>
                <input type="text" name="direccion_servicio" required placeholder="Ej: Carrera 15 # 85-30, Of. 302, Bogotá">
            </div>

            <div class="form-group">
                <label>Notas o Descripción para el Técnico</label>
                <textarea name="descripcion" rows="2" placeholder="Detalles adicionales del servicio..."></textarea>
            </div>

            <button type="submit" class="btn-submit">🚀 Agendar Cita y Enviar WhatsApps</button>
        </form>
    </div>

    <div class="card">
        <div class="table-header-flex">
            <div>
                <h2 style="margin:0;font-size:19px;color:#0f172a;">📋 Citas Programadas y Estado en Vivo</h2>
                <div style="font-size:13px;color:#64748b;margin-top:2px;">Mostrando {len(citas)} citas registradas</div>
            </div>
            <a href="{html.escape(excel_export_url)}" class="btn-excel" title="Descargar citas filtradas en formato Microsoft Excel">
                📊 Exportar a Excel (.xlsx)
            </a>
        </div>

        <!-- Panel de Filtros -->
        <div class="filter-panel">
            <form method="GET" action="/agendar" id="filterForm">
                <div class="filter-grid">
                    <div>
                        <label style="font-size:12px;margin-bottom:4px;">Desde Fecha</label>
                        <input type="date" name="fecha_desde" value="{f_desde}">
                    </div>
                    <div>
                        <label style="font-size:12px;margin-bottom:4px;">Hasta Fecha</label>
                        <input type="date" name="fecha_hasta" value="{f_hasta}">
                    </div>
                    <div>
                        <label style="font-size:12px;margin-bottom:4px;">Cliente (Nombre/Tel)</label>
                        <input type="text" name="cliente_query" list="clientes_list_dl" value="{cli_q}" placeholder="Buscar cliente...">
                        <datalist id="clientes_list_dl">
                            {cli_datalist_options}
                        </datalist>
                    </div>
                    <div>
                        <label style="font-size:12px;margin-bottom:4px;">Técnico</label>
                        <select name="tecnico_id">
                            {tec_filter_options}
                        </select>
                    </div>
                    <div>
                        <label style="font-size:12px;margin-bottom:4px;">Estado WhatsApp</label>
                        <select name="estado">
                            {est_filter_options}
                        </select>
                    </div>
                    <div style="display:flex;gap:6px;">
                        <button type="submit" class="btn-filter" style="flex:1;">🔍 Filtrar</button>
                        <a href="/agendar" class="btn-reset" title="Limpiar todos los filtros">✖</a>
                    </div>
                </div>
            </form>
        </div>

        <div style="overflow-x:auto;">
            <table>
                <thead>
                    <tr>
                        <th>Servicio / Fecha</th>
                        <th>Cliente</th>
                        <th>Técnico</th>
                        <th>Estado WhatsApp</th>
                        <th style="text-align:center;width:60px;">Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {citas_rows_html if citas_rows_html else '<tr><td colspan="5" style="text-align:center;padding:24px;color:#64748b;">No se encontraron citas con los filtros seleccionados.</td></tr>'}
                </tbody>
            </table>
        </div>
    </div>
</div>

<!-- Modal de Eliminación de Cita -->
<div class="modal-overlay" id="deleteModal">
    <div class="modal-box">
        <h3 class="modal-title">🗑️ Eliminar Cita</h3>
        <p class="modal-desc" id="deleteModalText">
            ¿Estás seguro de que deseas eliminar esta cita? Esta acción no se puede deshacer.
        </p>
        <form method="POST" action="/agendar/eliminar" id="deleteForm">
            <input type="hidden" name="cita_id" id="deleteCitaId" value="">
            <div class="modal-actions">
                <button type="button" class="btn-modal-cancel" onclick="closeDeleteModal()">Cancelar</button>
                <button type="submit" class="btn-modal-confirm">Sí, Eliminar Cita</button>
            </div>
        </form>
    </div>
</div>

<!-- Modal de Administración de Técnicos -->
<div class="modal-overlay" id="techModal">
    <div class="modal-box" style="max-width:520px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h3 style="margin:0;font-size:18px;color:#0f172a;display:flex;align-items:center;gap:8px;">
                👥 Técnicos Registrados
            </h3>
            <button type="button" onclick="closeTechModal()" 
                    style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748b;line-height:1;">
                ✖
            </button>
        </div>
        <p style="font-size:13px;color:#64748b;margin-bottom:16px;">
            Listado del personal técnico activo. Puedes eliminar técnicos que ya no formen parte de la empresa.
        </p>
        <div style="max-height:260px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:16px;">
            <table style="width:100%;font-size:13px;margin:0;">
                <thead>
                    <tr>
                        <th style="padding:8px 10px;">Nombre</th>
                        <th style="padding:8px 10px;">Teléfono</th>
                        <th style="padding:8px 10px;text-align:center;width:60px;">Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {tec_table_rows_html if tec_table_rows_html else '<tr><td colspan="3" style="text-align:center;padding:16px;">No hay técnicos registrados.</td></tr>'}
                </tbody>
            </table>
        </div>
        <div class="modal-actions">
            <button type="button" class="btn-modal-cancel" onclick="closeTechModal()">Cerrar</button>
        </div>
    </div>
</div>

<!-- Modal de Confirmación para Eliminar Técnico -->
<div class="modal-overlay" id="deleteTecModal">
    <div class="modal-box">
        <h3 class="modal-title">🗑️ Eliminar Técnico</h3>
        <p class="modal-desc" id="deleteTecModalText">
            ¿Deseas retirar a este técnico del sistema?
        </p>
        <form method="POST" action="/agendar/tecnicos/eliminar" id="deleteTecForm">
            <input type="hidden" name="tecnico_id" id="deleteTecId" value="">
            <div class="modal-actions">
                <button type="button" class="btn-modal-cancel" onclick="closeDeleteTecModal()">Cancelar</button>
                <button type="submit" class="btn-modal-confirm">Sí, Retirar Técnico</button>
            </div>
        </form>
    </div>
</div>

<script>
function toggleNewTech(val) {{
    var box = document.getElementById('new_tech_box');
    var nameInput = document.getElementById('nuevo_tecnico_nombre');
    var telInput = document.getElementById('nuevo_tecnico_telefono');
    if (val === '__NUEVO__') {{
        box.style.display = 'block';
        nameInput.required = true;
        telInput.required = true;
    }} else {{
        box.style.display = 'none';
        nameInput.required = false;
        telInput.required = false;
    }}
}}

function confirmDeleteCita(citaId, titulo, cliente, fecha) {{
    document.getElementById('deleteCitaId').value = citaId;
    document.getElementById('deleteModalText').innerHTML = 
        '¿Deseas eliminar permanentemente la cita de <strong>' + titulo + '</strong> agendada para <strong>' + cliente + '</strong> el día <strong>' + fecha + '</strong>?<br><br>⚠️ Esta acción borrará el registro de la base de datos.';
    document.getElementById('deleteModal').style.display = 'flex';
}}

function closeDeleteModal() {{
    document.getElementById('deleteModal').style.display = 'none';
}}

function openTechModal() {{
    document.getElementById('techModal').style.display = 'flex';
}}

function closeTechModal() {{
    document.getElementById('techModal').style.display = 'none';
}}

function confirmDeleteTecnico(tecId, nombre) {{
    document.getElementById('deleteTecId').value = tecId;
    document.getElementById('deleteTecModalText').innerHTML = 
        '¿Deseas eliminar al técnico <strong>' + nombre + '</strong> del equipo?<br><br>Si tiene servicios en su historial, dejará de aparecer para nuevas citas manteniendo el registro histórico intacto.';
    document.getElementById('deleteTecModal').style.display = 'flex';
}}

function closeDeleteTecModal() {{
    document.getElementById('deleteTecModal').style.display = 'none';
}}

// Cerrar modales con Escape o click en fondo
window.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
        closeDeleteModal();
        closeDeleteTecModal();
        closeTechModal();
    }}
}});
document.getElementById('deleteModal').addEventListener('click', function(e) {{
    if (e.target === this) closeDeleteModal();
}});
document.getElementById('techModal').addEventListener('click', function(e) {{
    if (e.target === this) closeTechModal();
}});
document.getElementById('deleteTecModal').addEventListener('click', function(e) {{
    if (e.target === this) closeDeleteTecModal();
}});

// Formateo y validación de números de WhatsApp
function attachPhoneFormatter(id) {{
    var el = document.getElementById(id);
    if (!el) return;

    // Bloquear teclas no numéricas
    el.addEventListener('keypress', function(e) {{
        if (!/[0-9]/.test(e.key) && !(e.key === '+' && el.selectionStart === 0 && !el.value.includes('+'))) {{
            e.preventDefault();
        }}
    }});

    // Formatear automáticamente agregando espacio después de los 3 primeros números (Ej: 300 4759860)
    el.addEventListener('input', function() {{
        var raw = el.value;
        var hasPlus = raw.startsWith('+');
        // Remover todo excepto dígitos
        var digits = raw.replace(/[^0-9]/g, '');

        if (hasPlus) {{
            if (digits.startsWith('57')) {{
                var rest = digits.slice(2);
                if (rest.length > 3) {{
                    el.value = '+57 ' + rest.slice(0, 3) + ' ' + rest.slice(3, 10);
                }} else if (rest.length > 0) {{
                    el.value = '+57 ' + rest;
                }} else {{
                    el.value = '+57 ';
                }}
            }} else {{
                el.value = '+' + digits.slice(0, 15);
            }}
        }} else {{
            if (digits.startsWith('57') && digits.length > 10) {{
                var rest = digits.slice(2);
                if (rest.length > 3) {{
                    el.value = '+57 ' + rest.slice(0, 3) + ' ' + rest.slice(3, 10);
                }} else {{
                    el.value = '+57 ' + rest;
                }}
            }} else {{
                // Formato estándar Colombia (10 dígitos): 300 4759860
                if (digits.length > 3) {{
                    el.value = digits.slice(0, 3) + ' ' + digits.slice(3, 10);
                }} else {{
                    el.value = digits;
                }}
            }}
        }}
    }});
}}

attachPhoneFormatter('cliente_telefono');
attachPhoneFormatter('nuevo_tecnico_telefono');

var agendarForm = document.querySelector('form[action="/agendar"]');
if (agendarForm) {{
    agendarForm.addEventListener('submit', function(e) {{
        var telEl = document.getElementById('cliente_telefono');
        if (telEl) {{
            var digits = telEl.value.replace(/[^0-9]/g, '');
            if (digits.length < 10) {{
                alert('Por favor introduce un número de WhatsApp del cliente válido (al menos 10 dígitos. Ej: 300 4759860).');
                telEl.focus();
                e.preventDefault();
                return false;
            }}
        }}
    }});
}}
</script>
</body>
</html>"""


class MetaBridgeHandler(BaseHTTPRequestHandler):
    def is_authenticated(self):
        cookie_header = self.headers.get("Cookie", "")
        if not cookie_header:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
            if SESSION_COOKIE_NAME in cookie:
                return cookie[SESSION_COOKIE_NAME].value == SESSION_TOKEN
        except Exception:
            pass
        return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # 1. Meta Webhook Verification Handshake
        if "webhook/whatsapp/webhook" in parsed.path:
            query = urllib.parse.parse_qs(parsed.query)
            token = query.get("hub.verify_token", [""])[0]
            challenge = query.get("hub.challenge", [""])[0]
            if token == VERIFY_TOKEN and challenge:
                print(f"[Meta Bridge] Handshake verificado exitosamente con challenge: {challenge}")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(challenge.encode("utf-8"))
                return

        # 2. Cerrar Sesión
        if parsed.path == "/agendar/logout":
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}=; Path=/agendar; Max-Age=0; HttpOnly; SameSite=Lax",
            )
            self.send_header("Location", "/agendar")
            self.end_headers()
            return

        # 3. Descarga de archivo .ICS para Calendario (requiere sesión)
        if parsed.path == "/agendar/ics":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            titulo = q.get("titulo", ["Cita Tekvo"])[0]
            inicio = q.get("inicio", [""])[0]
            fin = q.get("fin", [""])[0]
            ubicacion = q.get("ubicacion", [""])[0]
            desc = q.get("desc", [""])[0]
            uid = str(uuid.uuid4())
            now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            ics_content = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//Tekvo//Sistema de Citas//ES\r\n"
                "METHOD:PUBLISH\r\n"
                "BEGIN:VEVENT\r\n"
                f"UID:{uid}\r\n"
                f"DTSTAMP:{now_utc}\r\n"
                f"DTSTART;TZID=America/Bogota:{inicio}\r\n"
                f"DTEND;TZID=America/Bogota:{fin}\r\n"
                f"SUMMARY:{titulo}\r\n"
                f"LOCATION:{ubicacion}\r\n"
                f"DESCRIPTION:{desc}\r\n"
                "END:VEVENT\r\n"
                "END:VCALENDAR\r\n"
            )
            body = ics_content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="cita-tekvo.ics"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 4. Exportar Reporte a Excel (.xlsx) con filtros aplicados (requiere sesión)
        if parsed.path == "/agendar/exportar":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            q = urllib.parse.parse_qs(parsed.query)
            filters = {
                "fecha_desde": q.get("fecha_desde", [""])[0].strip(),
                "fecha_hasta": q.get("fecha_hasta", [""])[0].strip(),
                "cliente_query": q.get("cliente_query", [""])[0].strip(),
                "tecnico_id": q.get("tecnico_id", [""])[0].strip(),
                "estado": q.get("estado", [""])[0].strip(),
            }
            _, citas_export, _, _ = fetch_tecnicos_and_citas(filters)
            headers_row = [
                "ID Cita",
                "Servicio / Labor",
                "Fecha Inicio",
                "Fecha Fin",
                "Cliente",
                "Teléfono Cliente",
                "Técnico Asignado",
                "Teléfono Técnico",
                "Dirección de Servicio",
                "Estado Cita",
                "Confirmación Cliente",
                "Confirmación Técnico",
                "Notas / Descripción"
            ]
            rows_data = [headers_row]
            for c in citas_export:
                rows_data.append([
                    c["id"],
                    c["titulo"],
                    c["fecha"],
                    c["fecha_fin"],
                    c["cliente"],
                    c["cli_tel"],
                    c["tecnico"],
                    c["tec_tel"],
                    c["direccion"],
                    c["estado"],
                    c["conf_cli"] or "PENDIENTE",
                    c["conf_tec"] or "PENDIENTE",
                    c["descripcion"] or ""
                ])
            xlsx_bytes = generate_excel_xml(rows_data)
            now_filename = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", f'attachment; filename="reporte_citas_tekvo_{now_filename}.xlsx"')
            self.send_header("Content-Length", str(len(xlsx_bytes)))
            self.end_headers()
            self.wfile.write(xlsx_bytes)
            return

        # 5. Portal Web de Agendamiento (requiere login)
        if parsed.path in ["/agendar", "/agendar/", "/agendar/login"]:
            if not self.is_authenticated():
                page = render_login_page().encode("utf-8")
            else:
                q = urllib.parse.parse_qs(parsed.query)
                filters = {
                    "fecha_desde": q.get("fecha_desde", [""])[0].strip(),
                    "fecha_hasta": q.get("fecha_hasta", [""])[0].strip(),
                    "cliente_query": q.get("cliente_query", [""])[0].strip(),
                    "tecnico_id": q.get("tecnico_id", [""])[0].strip(),
                    "estado": q.get("estado", [""])[0].strip(),
                }
                msg_del = q.get("msg", [""])[0].strip()
                err_del = q.get("error", [""])[0].strip()
                page = render_agendar_page(
                    error_msg=err_del if err_del else None,
                    filters=filters
                ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        # 6. Interfaz de Vinculación WhatsApp Web (requiere login)
        if parsed.path == "/agendar/whatsapp":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            wa_status, wa_me = get_waha_session_status()
            page = render_whatsapp_page(wa_status, wa_me).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return

        # 6.1. WhatsApp Status API
        if parsed.path == "/agendar/whatsapp/status":
            if not self.is_authenticated():
                self.send_response(401)
                self.end_headers()
                return
            wa_status, wa_me = get_waha_session_status()
            resp_body = json.dumps({"status": wa_status, "me": wa_me}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
            return

        # 6.2. WhatsApp Live QR PNG
        if parsed.path == "/agendar/whatsapp/qr":
            if not self.is_authenticated():
                self.send_response(401)
                self.end_headers()
                return
            qr_bytes = get_waha_qr()
            if qr_bytes:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(qr_bytes)))
                self.end_headers()
                self.wfile.write(qr_bytes)
            else:
                self.send_response(404)
                self.end_headers()
            return

        # Otherwise proxy to n8n
        self.proxy_request("GET")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/agendar/login":
            self.handle_login_submit()
            return
        if parsed.path == "/agendar/whatsapp/restart":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            restart_waha_session()
            self.send_response(302)
            self.send_header("Location", "/agendar/whatsapp")
            self.end_headers()
            return
        if parsed.path == "/agendar/whatsapp/logout":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            logout_waha_session()
            self.send_response(302)
            self.send_header("Location", "/agendar/whatsapp")
            self.end_headers()
            return
        if parsed.path == "/webhook/waha":
            self.handle_waha_inbound()
            return
        if parsed.path == "/agendar/eliminar":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            self.handle_eliminar_submit()
            return
        if parsed.path == "/agendar/tecnicos/eliminar":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            self.handle_eliminar_tecnico_submit()
            return
        if parsed.path in ["/agendar", "/agendar/"]:
            if not self.is_authenticated():
                page = render_login_page(error_msg="Tu sesión expiró. Por favor ingresa nuevamente.").encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            self.handle_agendar_submit()
            return
        self.proxy_request("POST")

    def handle_waha_inbound(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(raw_body)
            event = data.get("event")
            payload = data.get("payload", {})

            sender_phone = None
            body_text = None

            if event == "poll.vote":
                vote = payload.get("vote", {})
                selected_options = vote.get("selectedOptions", [])
                if selected_options:
                    body_text = str(selected_options[0]).strip().upper()
                else:
                    body_text = ""

                candidates = [
                    vote.get("from", ""),
                    vote.get("participant", ""),
                    vote.get("to", ""),
                    payload.get("poll", {}).get("to", ""),
                    payload.get("poll", {}).get("from", "")
                ]

                for candidate in candidates:
                    if not candidate:
                        continue
                    if "@lid" in candidate:
                        resolved = resolve_lid_to_phone(candidate)
                        if resolved:
                            sender_phone = resolved
                            break
                    elif "@" in candidate:
                        clean = "".join(c for c in candidate.split("@")[0] if c.isdigit())
                        if len(clean) >= 10:
                            sender_phone = normalize_phone(clean)
                            break
                    elif any(c.isdigit() for c in candidate):
                        clean = "".join(c for c in candidate if c.isdigit())
                        if len(clean) >= 10:
                            sender_phone = normalize_phone(clean)
                            break

                print(f"[WAHA Inbound Poll Vote] Candidates: {candidates}, Resolved: {sender_phone}, Option: {body_text}", flush=True)

            elif event == "message":
                raw_from = payload.get("from", "")
                if "@lid" in raw_from:
                    sender_phone = resolve_lid_to_phone(raw_from)
                elif "@" in raw_from:
                    from_clean = raw_from.split("@")[0]
                    sender_phone = normalize_phone(from_clean)
                body_text = payload.get("body", "").strip().upper()
                print(f"[WAHA Inbound Message] From: {sender_phone}, Body: {body_text}", flush=True)

            if sender_phone and body_text:
                action = None
                if ("✅" in body_text or "SÍ" in body_text or "CONFIRM" in body_text or 
                    body_text in ["1", "SI", "OK", "VOY", "DE ACUERDO"]):
                    action = "CONFIRMAR"
                elif ("❌" in body_text or "CANCEL" in body_text or "NO DISPONIBLE" in body_text or "NO PUEDO" in body_text or
                      body_text in ["2", "NO"]):
                    action = "CANCELAR"

                if action:
                    clean_p = "".join(c for c in sender_phone if c.isdigit())
                    con = get_db()
                    rows = con.run("""
                        SELECT c.id, c.titulo,
                               TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                               c.estado, c.confirmacion_cliente, c.confirmacion_tecnico,
                               cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                               tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                               COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                               CASE WHEN REGEXP_REPLACE(cli.telefono_whatsapp, '[^0-9]', '', 'g') = :p THEN 'CLIENTE' ELSE 'TECNICO' END AS rol
                        FROM citas c
                        JOIN usuarios cli ON c.cliente_id = cli.id
                        JOIN usuarios tec ON c.tecnico_id = tec.id
                        LEFT JOIN usuarios adm ON c.admin_id = adm.id
                        WHERE (REGEXP_REPLACE(cli.telefono_whatsapp, '[^0-9]', '', 'g') = :p 
                            OR REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p)
                          AND c.fecha_inicio >= NOW() - INTERVAL '1 day'
                          AND c.estado IN ('PENDIENTE', 'CONFIRMADA', 'REQUIERE_REASIGNACION')
                        ORDER BY c.fecha_inicio ASC
                        LIMIT 1
                    """, p=clean_p)

                    if rows:
                        r = rows[0]
                        cita_id, titulo, fecha_fmt, estado_actual, conf_cli, conf_tec, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, rol = r

                        nuevo_estado = estado_actual
                        nuevo_conf_cli = conf_cli
                        nuevo_conf_tec = conf_tec
                        motivo = None

                        if rol == "CLIENTE":
                            if action == "CONFIRMAR":
                                nuevo_conf_cli = "CONFIRMADA"
                                nuevo_estado = "CONFIRMADA" if conf_tec == "CONFIRMADA" else "PENDIENTE"
                            else:
                                nuevo_conf_cli = "CANCELADA"
                                nuevo_estado = "CANCELADA"
                                motivo = "Cancelada por el cliente vía WhatsApp"
                        else:  # TECNICO
                            if action == "CONFIRMAR":
                                nuevo_conf_tec = "CONFIRMADA"
                                nuevo_estado = "CONFIRMADA" if conf_cli == "CONFIRMADA" else "PENDIENTE"
                            else:
                                nuevo_conf_tec = "CANCELADA"
                                nuevo_estado = "REQUIERE_REASIGNACION"
                                motivo = "Técnico indicó que no está disponible vía WhatsApp"

                        con.run("""
                            UPDATE citas
                            SET confirmacion_cliente = :cc,
                                confirmacion_tecnico = :ct,
                                estado = :est::estado_cita_enum,
                                motivo_cancelacion = COALESCE(:mot, motivo_cancelacion),
                                updated_at = NOW()
                            WHERE id = :id
                        """, cc=nuevo_conf_cli, ct=nuevo_conf_tec, est=nuevo_estado, mot=motivo, id=cita_id)
                        con.close()

                        if action == "CONFIRMAR":
                            reply_msg = f"🙌 ¡Muchas gracias! Tu respuesta para el servicio *{titulo}* ({fecha_fmt}) ha sido registrada exitosamente como CONFIRMADA."
                        else:
                            reply_msg = f"⚠️ Tu respuesta para el servicio *{titulo}* ({fecha_fmt}) ha sido registrada como CANCELADA / NO DISPONIBLE. El administrador de Tekvo ha sido notificado."
                        send_waha_text(sender_phone, reply_msg)

                        if rol == "CLIENTE" and action == "CANCELAR":
                            tec_alert = f"⚠️ *Aviso de Cancelación*\n\nHola {tec_nom}, la cita de *{titulo}* programada para {fecha_fmt} con {cli_nom} ha sido CANCELADA por el cliente.\n\nTu agenda queda liberada en esa franja horaria."
                            send_waha_text(tec_tel, tec_alert)

                        admin_alert = (
                            f"🔔 *Actualización de Cita Tekvo*\n\n"
                            f"- Cita: *{titulo}* ({fecha_fmt})\n"
                            f"- Quien respondió: {cli_nom if rol == 'CLIENTE' else tec_nom} ({rol})\n"
                            f"- Respuesta: {'✅ CONFIRMADO' if action == 'CONFIRMAR' else '❌ CANCELADO'}\n"
                            f"- Estado Cita: {nuevo_estado}"
                        )
                        send_waha_text(adm_tel, admin_alert)
                        print(f"[Admin Alert Sent] to {adm_tel}: {admin_alert[:60]}...", flush=True)
                    else:
                        con.close()
                        print(f"[WAHA Inbound] No pending cita found for phone {sender_phone} (clean: {clean_p})", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception as e:
            print(f"[WAHA Inbound Error] {e}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"error"}')

    def handle_eliminar_tecnico_submit(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_post = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(raw_post)
            tecnico_id = form.get("tecnico_id", [""])[0].strip()
            if not tecnico_id:
                self.send_response(302)
                self.send_header("Location", "/agendar?error=" + urllib.parse.quote("ID de técnico inválido."))
                self.end_headers()
                return
            ok, msg = delete_tecnico_by_id(tecnico_id)
            redirect_url = "/agendar" if ok else "/agendar?error=" + urllib.parse.quote(msg)
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.end_headers()
        except Exception as e:
            self.send_response(302)
            self.send_header("Location", "/agendar?error=" + urllib.parse.quote(str(e)))
            self.end_headers()

    def handle_eliminar_submit(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_post = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(raw_post)
            cita_id = form.get("cita_id", [""])[0].strip()
            if not cita_id:
                self.send_response(302)
                self.send_header("Location", "/agendar?error=" + urllib.parse.quote("ID de cita inválido."))
                self.end_headers()
                return
            ok, msg = delete_cita_by_id(cita_id)
            redirect_url = "/agendar" if ok else "/agendar?error=" + urllib.parse.quote(msg)
            self.send_response(302)
            self.send_header("Location", redirect_url)
            self.end_headers()
        except Exception as e:
            self.send_response(302)
            self.send_header("Location", "/agendar?error=" + urllib.parse.quote(str(e)))
            self.end_headers()

    def handle_login_submit(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_post = self.rfile.read(content_length).decode("utf-8")
        form = urllib.parse.parse_qs(raw_post)
        username = form.get("username", [""])[0].strip().lower()
        password = form.get("password", [""])[0].strip().replace(" ", "")
        # Aceptar tanto 3118198511 como +573118198511
        if username == AUTH_USER and password in [AUTH_PASS, f"+57{AUTH_PASS}", f"57{AUTH_PASS}"]:
            self.send_response(302)
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={SESSION_TOKEN}; Path=/agendar; Max-Age=2592000; HttpOnly; SameSite=Lax",
            )
            self.send_header("Location", "/agendar")
            self.end_headers()
        else:
            page = render_login_page(error_msg="Usuario o contraseña incorrectos.").encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def handle_agendar_submit(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_post = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(raw_post)

            titulo = form.get("titulo", ["Servicio Técnico"])[0].strip()
            cliente_nombre = form.get("cliente_nombre", ["Cliente"])[0].strip()
            cliente_telefono = normalize_phone(form.get("cliente_telefono", [""])[0].strip())
            fecha = form.get("fecha", [""])[0].strip()
            hora_inicio = form.get("hora_inicio", ["09:00"])[0].strip()
            hora_fin = form.get("hora_fin", [""])[0].strip()

            if not hora_fin:
                try:
                    dt_start = datetime.strptime(f"{fecha} {hora_inicio}", "%Y-%m-%d %H:%M")
                    dt_end = dt_start + timedelta(hours=2)
                    hora_fin = dt_end.strftime("%H:%M")
                except Exception:
                    hora_fin = "11:00"

            direccion = form.get("direccion_servicio", ["Por confirmar"])[0].strip()
            descripcion = form.get("descripcion", [""])[0].strip()

            tecnico_selector = form.get("tecnico_selector", [""])[0]
            if tecnico_selector == "__NUEVO__":
                tecnico_nombre = form.get("nuevo_tecnico_nombre", ["Técnico"])[0].strip()
                tecnico_tel = normalize_phone(form.get("nuevo_tecnico_telefono", [""])[0].strip())
                digits_only = "".join(c for c in tecnico_tel if c.isdigit())
                tecnico_email = f"tec_{digits_only}@tekvo.co"
                con = get_db()
                con.run(
                    "INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol, activo) "
                    "VALUES (:n, :e, :t, 'TECNICO', true) "
                    "ON CONFLICT (email) DO UPDATE SET nombre = EXCLUDED.nombre, telefono_whatsapp = EXCLUDED.telefono_whatsapp",
                    n=tecnico_nombre,
                    e=tecnico_email,
                    t=tecnico_tel,
                )
                con.close()
            else:
                parts = tecnico_selector.split("|")
                tecnico_nombre = parts[0]
                tecnico_email = parts[1] if len(parts) > 1 else ""

            fecha_inicio_iso = f"{fecha}T{hora_inicio}:00-05:00"
            fecha_fin_iso = f"{fecha}T{hora_fin}:00-05:00"

            ms_event_id = f"WEB-{uuid.uuid4().hex[:8].upper()}"
            payload = {
                "titulo": titulo,
                "descripcion": descripcion,
                "direccion_servicio": direccion,
                "fecha_inicio": fecha_inicio_iso,
                "fecha_fin": fecha_fin_iso,
                "cliente_nombre": cliente_nombre,
                "cliente_telefono": cliente_telefono,
                "tecnico_nombre": tecnico_nombre,
                "tecnico_email": tecnico_email,
                "admin_email": "servicio@tekvo.co",
                "microsoft_event_id": ms_event_id,
            }

            req = urllib.request.Request(
                f"{TARGET_HOST}/webhook/citas/crear",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as _:
                    pass
            except Exception as e:
                print(f"[Meta Bridge] Error llamando webhook de n8n: {e}", flush=True)

            # Sincronización activa: esperar a que n8n complete la inserción en PostgreSQL (máx 3.0s, chequeo cada 40ms)
            cita_confirmada_db = False
            start_wait = time.time()
            while time.time() - start_wait < 3.0:
                try:
                    con_chk = get_db()
                    chk = con_chk.run("SELECT id FROM citas WHERE microsoft_event_id = :mid", mid=ms_event_id)
                    con_chk.close()
                    if chk:
                        cita_confirmada_db = True
                        break
                except Exception:
                    pass
                time.sleep(0.04)

            # Si n8n tardó o falló, asegurar la inserción directa en PostgreSQL para que figure inmediatamente
            if not cita_confirmada_db:
                print(f"[Meta Bridge Fallback] Insertando cita directamente en PostgreSQL para {ms_event_id}...", flush=True)
                try:
                    con_fb = get_db()
                    digits_cli = "".join(c for c in cliente_telefono if c.isdigit())
                    cli_email = f"cli_{digits_cli}@cliente.com"
                    con_fb.run(
                        "INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol) "
                        "VALUES (:n, :e, :t, 'CLIENTE') "
                        "ON CONFLICT (email) DO UPDATE SET nombre = EXCLUDED.nombre, telefono_whatsapp = EXCLUDED.telefono_whatsapp",
                        n=cliente_nombre, e=cli_email, t=cliente_telefono
                    )
                    cli_row = con_fb.run("SELECT id FROM usuarios WHERE email = :e", e=cli_email)
                    cli_id = cli_row[0][0] if cli_row else None

                    tec_row = con_fb.run(
                        "SELECT id FROM usuarios WHERE rol = 'TECNICO' AND activo = true "
                        "ORDER BY CASE WHEN email = :e THEN 1 WHEN LOWER(nombre) = LOWER(:n) THEN 2 ELSE 3 END ASC LIMIT 1",
                        e=tecnico_email, n=tecnico_nombre
                    )
                    tec_id = tec_row[0][0] if tec_row else None

                    adm_row = con_fb.run("SELECT id FROM usuarios WHERE rol = 'ADMINISTRADOR' AND activo = true LIMIT 1")
                    adm_id = adm_row[0][0] if adm_row else None

                    if cli_id and tec_id:
                        con_fb.run(
                            "INSERT INTO citas (cliente_id, tecnico_id, admin_id, titulo, descripcion, direccion_servicio, "
                            "fecha_inicio, fecha_fin, estado, microsoft_event_id, confirmacion_cliente, confirmacion_tecnico, "
                            "recordatorio_24h_enviado, recordatorio_cliente_enviado, recordatorio_tecnico_enviado, recordatorio_enviado_at) "
                            "VALUES (:cli_id, :tec_id, :adm_id, :tit, :desc, :dir, :fi::timestamptz, :ff::timestamptz, "
                            "'PENDIENTE', :mid, 'PENDIENTE', 'PENDIENTE', "
                            "CASE WHEN :fi::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END, "
                            "CASE WHEN :fi::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END, "
                            "CASE WHEN :fi::timestamptz <= (NOW() + INTERVAL '24 hours') THEN TRUE ELSE FALSE END, "
                            "CASE WHEN :fi::timestamptz <= (NOW() + INTERVAL '24 hours') THEN NOW() ELSE NULL END)",
                            cli_id=cli_id, tec_id=tec_id, adm_id=adm_id, tit=titulo, desc=descripcion, dir=direccion,
                            fi=fecha_inicio_iso, ff=fecha_fin_iso, mid=ms_event_id
                        )
                    con_fb.close()
                except Exception as fb_err:
                    print(f"[Meta Bridge Fallback Error] {fb_err}", flush=True)

            cal_body = (
                f"Cliente: {cliente_nombre}\n"
                f"Teléfono WhatsApp: {cliente_telefono}\n"
                f"Técnico Asignado: {tecnico_nombre}\n"
                f"Dirección: {direccion}\n"
                f"Notas: {descripcion}"
            )
            outlook_params = urllib.parse.urlencode({
                "path": "/calendar/action/compose",
                "rru": "addevent",
                "subject": f"{titulo} - {cliente_nombre}",
                "startdt": fecha_inicio_iso,
                "enddt": fecha_fin_iso,
                "location": direccion,
                "body": cal_body,
            })
            outlook_url = f"https://outlook.office.com/calendar/0/deeplink/compose?{outlook_params}"

            ics_start = fecha.replace("-", "") + "T" + hora_inicio.replace(":", "") + "00"
            ics_end = fecha.replace("-", "") + "T" + hora_fin.replace(":", "") + "00"
            ics_params = urllib.parse.urlencode({
                "titulo": f"{titulo} - {cliente_nombre}",
                "inicio": ics_start,
                "fin": ics_end,
                "ubicacion": direccion,
                "desc": cal_body.replace("\n", "\\n"),
            })
            ics_url = f"/agendar/ics?{ics_params}"

            success_data = {
                "titulo": titulo,
                "cliente_nombre": cliente_nombre,
                "cliente_telefono": cliente_telefono,
                "tecnico_nombre": tecnico_nombre,
                "fecha_label": f"{fecha} ({hora_inicio} a {hora_fin})",
                "outlook_url": outlook_url,
                "ics_url": ics_url,
                "microsoft_event_id": ms_event_id,
            }
            page = render_agendar_page(success_data=success_data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        except Exception as e:
            page = render_agendar_page(error_msg=str(e)).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    def proxy_request(self, method):
        target_url = f"{TARGET_HOST}{self.path}"
        headers = {}
        for k, v in self.headers.items():
            if k.lower() not in ["host", "content-length"]:
                headers[k] = v

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        req = urllib.request.Request(target_url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ["transfer-encoding", "content-encoding", "content-length"]:
                        self.send_header(k, v)
                resp_body = resp.read()
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() not in ["transfer-encoding", "content-encoding", "content-length"]:
                    self.send_header(k, v)
            e_body = e.read()
            self.send_header("Content-Length", str(len(e_body)))
            self.end_headers()
            self.wfile.write(e_body)
        except Exception as e:
            print(f"[Meta Bridge] Proxy error: {e}")
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(e).encode("utf-8"))


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 8000), MetaBridgeHandler)
    print("Meta Bridge & Portal Agendamiento escuchando en 0.0.0.0:8000")
    server.serve_forever()
