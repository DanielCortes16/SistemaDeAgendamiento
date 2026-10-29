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
from datetime import datetime, timedelta, timezone
import pg8000.native
import threading


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
    try:
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sessions/default",
            headers={"X-Api-Key": WAHA_API_KEY},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "UNKNOWN")
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


def restart_waha_session(force=False):
    global _last_restart_attempt
    now = time.time()
    if not force and (now - _last_restart_attempt < 30):
        print(f"[WAHA Restart Ignorado] Cooldown activo ({now - _last_restart_attempt:.1f}s < 30s).", flush=True)
        return False, "Cooldown activo"
    _last_restart_attempt = now
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


def send_waha_text(phone, text, max_retries=3):
    clean_digits = "".join(c for c in phone if c.isdigit())
    chat_id = f"{clean_digits}@c.us"
    payload = {
        "session": "default",
        "chatId": chat_id,
        "text": text,
    }
    backoff_delays = [1.0, 2.5, 5.0]
    last_error = None
    for attempt in range(max_retries):
        try:
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
            last_error = e
            if attempt < max_retries - 1:
                delay = backoff_delays[attempt]
                print(f"[WAHA Retry Text] Intento {attempt + 1}/{max_retries} a {phone} falló ({e}). Reintentando en {delay}s...", flush=True)
                time.sleep(delay)
            else:
                print(f"[WAHA Send Error] Fallaron los {max_retries} intentos a {phone}: {e}", flush=True)
                return False, str(last_error)


def send_waha_poll(phone, poll_name, options, max_retries=3):
    clean_digits = "".join(c for c in phone if c.isdigit())
    chat_id = f"{clean_digits}@c.us"
    # WhatsApp limit is 255 characters for poll title
    if len(poll_name) > 250:
        poll_name = poll_name[:247] + "..."
    # WhatsApp strictly requires at least 2 options in polls
    if not options or len(options) == 0:
        options = ["✅ Sí", "❌ No"]
    elif len(options) == 1:
        options = [options[0], "⏳ Más tarde"]
    payload = {
        "session": "default",
        "chatId": chat_id,
        "poll": {
            "name": poll_name,
            "options": options,
            "multipleAnswers": False
        }
    }
    backoff_delays = [1.0, 2.5, 5.0]
    last_error = None
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                f"{WAHA_BASE_URL}/api/sendPoll",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Api-Key": WAHA_API_KEY,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[WAHA Poll Sent] to {phone} ({chat_id}): {poll_name[:60]}...", flush=True)
                return True, resp.read().decode("utf-8")
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                delay = backoff_delays[attempt]
                print(f"[WAHA Retry Poll] Intento {attempt + 1}/{max_retries} a {phone} falló ({e}). Reintentando en {delay}s...", flush=True)
                time.sleep(delay)
            else:
                print(f"[WAHA Poll Error] Fallaron los {max_retries} intentos a {phone}: {e}", flush=True)
                return False, str(last_error)


def check_and_dispatch_due_start_prompts():
    """
    Busca citas CONFIRMADAS cuya fecha_inicio ya llegó (fecha_inicio <= NOW()),
    que no hayan recibido el prompt de inicio (prompt_inicio_enviado = FALSE)
    y no tengan fecha_inicio_real registrada, despachando la encuesta interactiva
    [▶️ Iniciar Labor] al WhatsApp del técnico a la hora exacta programada.
    """
    try:
        con = get_db()
        rows = con.run("""
            SELECT c.id, c.titulo,
                   TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                   cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                   tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                   COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                   c.direccion_servicio
            FROM citas c
            JOIN usuarios cli ON c.cliente_id = cli.id
            JOIN usuarios tec ON c.tecnico_id = tec.id
            LEFT JOIN usuarios adm ON c.admin_id = adm.id
            WHERE c.estado = 'CONFIRMADA'
              AND c.fecha_inicio >= NOW() - INTERVAL '2 days'
              AND c.fecha_inicio <= NOW()
              AND c.prompt_inicio_enviado = FALSE
              AND c.fecha_inicio_real IS NULL
            ORDER BY c.fecha_inicio ASC
        """)
        con.close()

        if not rows:
            return

        for r in rows:
            cita_id, titulo, fecha_fmt, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, direccion = r
            if not tec_tel or not any(ch.isdigit() for ch in tec_tel):
                continue

            try:
                # Reclamar de forma atómica para prevenir envíos duplicados concurrentes
                con_claim = get_db()
                claimed = con_claim.run("""
                    UPDATE citas
                    SET prompt_inicio_enviado = TRUE,
                        prompt_inicio_enviado_at = NOW(),
                        updated_at = NOW()
                    WHERE id = :id AND prompt_inicio_enviado = FALSE
                    RETURNING id
                """, id=cita_id)
                con_claim.close()

                if not claimed:
                    continue

                poll_tit = (titulo[:45] + "...") if len(titulo) > 45 else titulo
                poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                poll_dir = (direccion[:35] + "...") if len(direccion) > 35 else direccion
                tec_start_poll = f"🛠️ *UT TEKVO - Inicio de Labor*\n\n¿Listo para iniciar *{poll_tit}* con {poll_cli}?\n📍 {poll_dir}"

                success, _ = send_waha_poll(tec_tel, tec_start_poll, ["▶️ Iniciar Labor", "⏳ En camino"])
                if success:
                    admin_notice = (
                        f"⏰ *Hora Programada de Labor - UT TEKVO*\n\n"
                        f"La cita programada para las *{fecha_fmt}* ha alcanzado su hora de ejecución.\n\n"
                        f"📋 *Detalles del Servicio:*\n"
                        f"• *ID:* `{str(cita_id)[:8]}`\n"
                        f"• *Servicio:* *{titulo}*\n"
                        f"• *Técnico Responsable:* *{tec_nom}* ({tec_tel})\n"
                        f"• *Cliente:* {cli_nom} ({cli_tel})\n"
                        f"• *Dirección:* {direccion}\n\n"
                        f"👉 Se envió automáticamente la opción interactiva [▶️ Iniciar Labor] al WhatsApp del técnico."
                    )
                    send_waha_text(adm_tel, admin_notice)
                    print(f"[Start Prompt Dispatched] Cita {cita_id} enviada al técnico {tec_nom} ({tec_tel})", flush=True)
                else:
                    # En caso de fallo transitorio en WAHA, liberar la bandera para reintento en el siguiente ciclo
                    con_revert = get_db()
                    con_revert.run("""
                        UPDATE citas
                        SET prompt_inicio_enviado = FALSE,
                            prompt_inicio_enviado_at = NULL,
                            updated_at = NOW()
                        WHERE id = :id AND fecha_inicio_real IS NULL
                    """, id=cita_id)
                    con_revert.close()
                    print(f"[Start Prompt Retry] Falló envío WAHA para cita {cita_id}. Reintentando en siguiente ciclo.", flush=True)

            except Exception as item_err:
                print(f"[Start Prompt Error Item] Cita {cita_id}: {item_err}", flush=True)

    except Exception as e:
        print(f"[Start Prompt Daemon Error] {e}", flush=True)


def start_prompt_daemon_loop():
    print("[Start Prompt Daemon] Hilo en segundo plano iniciado (frecuencia: cada 20s)...", flush=True)
    while True:
        try:
            check_and_dispatch_due_start_prompts()
        except Exception as e:
            print(f"[Start Prompt Daemon Loop Error] {e}", flush=True)
        time.sleep(20)


def send_waha_presence(presence="available"):
    try:
        payload = {"presence": presence}
        req = urllib.request.Request(
            f"{WAHA_BASE_URL}/api/sessions/default/presence",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Api-Key": WAHA_API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as _:
            return True
    except Exception:
        return False


def waha_heartbeat_daemon_loop():
    """
    Regla de Oro 2: Heartbeat Keep-Alive en segundo plano.
    Envía pings de estado a WAHA cada 30 segundos para mantener el socket activo
    y ejecutar auto-recuperación si detecta desconexión.
    """
    print("[WAHA Heartbeat Daemon] Iniciado (revisión de presencia cada 30s)...", flush=True)
    _cycles = 0
    while True:
        try:
            status, me = get_waha_session_status()
            _cycles += 1
            if status == "WORKING":
                send_waha_presence("available")
            if _cycles % 20 == 0:  # Log de pulso cada 10 minutos (20 ciclos de 30s)
                phone_id = me.get("id", "N/A") if isinstance(me, dict) else "N/A"
                print(f"[WAHA Heartbeat Pulse] Sesión: default | Estado: {status} | Usuario: {phone_id}", flush=True)
        except Exception as e:
            print(f"[WAHA Heartbeat Error] {e}", flush=True)
        time.sleep(30)


def fetch_tecnicos_and_citas(filters=None):
    if filters is None:
        filters = {}
    tecnicos = []
    todos_los_tecnicos = []
    citas = []
    clientes_list = []
    admin_tel = "+573118198511"
    try:
        con = get_db()
        rows_tec = con.run(
            "SELECT id, nombre, email, telefono_whatsapp, activo FROM usuarios "
            "WHERE rol = 'TECNICO' ORDER BY activo DESC, nombre ASC"
        )
        for r in rows_tec:
            item = {
                "id": str(r[0]),
                "nombre": r[1],
                "email": r[2],
                "telefono": r[3],
                "activo": bool(r[4]),
            }
            todos_los_tecnicos.append(item)
            if r[4]:
                tecnicos.append(item)

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
            "c.direccion_servicio, c.descripcion, c.microsoft_event_id, "
            "TO_CHAR(c.fecha_inicio_real AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS f_ini_real, "
            "TO_CHAR(c.fecha_fin_real AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS f_fin_real, "
            "c.calificacion, c.fecha_inicio_real, c.fecha_fin_real "
            "FROM citas c "
            "JOIN usuarios cli ON c.cliente_id = cli.id "
            "JOIN usuarios tec ON c.tecnico_id = tec.id "
            f"{where_sql} "
            "ORDER BY c.created_at DESC LIMIT 200"
        )
        rows_citas = con.run(sql_citas, **params)
        for r in rows_citas:
            f_ini_real = r[14]
            f_fin_real = r[15]
            calificacion = r[16]
            dt_ini_real = r[17]
            dt_fin_real = r[18]

            duracion_real = "-"
            if dt_ini_real and dt_fin_real:
                total_secs = max(0, int((dt_fin_real - dt_ini_real).total_seconds()))
                hrs = total_secs // 3600
                mins = (total_secs % 3600) // 60
                duracion_real = f"{hrs}h {mins}m" if hrs > 0 else f"{mins} min"
            elif dt_ini_real:
                duracion_real = "En progreso"

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
                "f_ini_real": f_ini_real or "",
                "f_fin_real": f_fin_real or "",
                "duracion_real": duracion_real,
                "calificacion": calificacion,
            })
        con.close()
    except Exception as e:
        print(f"[Meta Bridge DB Error] {e}")
    return tecnicos, citas, clientes_list, admin_tel, todos_los_tecnicos


def delete_cita_by_id(cita_id):
    try:
        con = get_db()
        con.run("DELETE FROM citas WHERE id = :id", id=cita_id)
        con.close()
        return True, "Cita eliminada correctamente."
    except Exception as e:
        print(f"[Meta Bridge DB Delete Error] {e}")
        return False, str(e)


def delete_citas_anteriores(fecha_limite):
    """
    Elimina todas las citas cuya fecha_inicio sea estrictamente anterior a fecha_limite (en zona horaria de Bogotá).
    """
    try:
        dt = datetime.strptime(fecha_limite.strip(), "%Y-%m-%d")
        fecha_limite_fmt = dt.strftime("%Y-%m-%d")
        con = get_db()
        count_rows = con.run(
            "SELECT COUNT(*) FROM citas WHERE (fecha_inicio AT TIME ZONE 'America/Bogota')::date < :lim::date",
            lim=fecha_limite_fmt
        )
        total = count_rows[0][0] if count_rows else 0
        if total == 0:
            con.close()
            return True, f"No se encontraron citas con fecha anterior al {fecha_limite_fmt}."

        con.run(
            "DELETE FROM citas WHERE (fecha_inicio AT TIME ZONE 'America/Bogota')::date < :lim::date",
            lim=fecha_limite_fmt
        )
        con.close()
        return True, f"Se han eliminado exitosamente {total} cita(s) con fecha anterior al {fecha_limite_fmt}."
    except Exception as e:
        print(f"[Meta Bridge DB Purge Error] {e}", flush=True)
        return False, f"Error al purgar citas: {str(e)}"


def delete_tecnico_by_id(tecnico_id):
    try:
        con = get_db()
        citas_count = con.run("SELECT COUNT(*) FROM citas WHERE tecnico_id = :id", id=tecnico_id)
        has_citas = citas_count[0][0] if citas_count else 0
        if has_citas == 0:
            con.run("DELETE FROM usuarios WHERE id = :id AND rol = 'TECNICO'", id=tecnico_id)
            con.close()
            return True, "Técnico eliminado completamente de la base de datos (sin citas asociadas)."
        else:
            con.run("UPDATE usuarios SET activo = false, updated_at = NOW() WHERE id = :id", id=tecnico_id)
            con.close()
            return True, f"Técnico retirado del equipo activo (conservado como inactivo por {has_citas} citas en historial)."
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
        if (initialStatus === "SCAN_QR_CODE") {{
            setInterval(refreshQR, 15000);
        }}
    </script>
</body>
</html>"""


def render_agendar_page(success_data=None, error_msg=None, info_msg=None, filters=None):
    if filters is None:
        filters = {}
    tecnicos, citas, clientes_list, admin_tel, todos_los_tecnicos = fetch_tecnicos_and_citas(filters)

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

    today_dt = datetime.now()
    today_date = today_dt.strftime("%Y-%m-%d")
    tomorrow = (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")
    first_of_this_month = today_dt.strftime("%Y-%m-01")
    first_prev_month = (today_dt.replace(day=1) - timedelta(days=1)).strftime("%Y-%m-01")
    first_two_months_ago = (today_dt.replace(day=1) - timedelta(days=40)).strftime("%Y-%m-01")

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
    for t in tecnicos:
        val = html.escape(f"{t['nombre']}|{t['email']}")
        label = html.escape(f"{t['nombre']} ({format_phone_display(t['telefono'])})")
        tec_options_html += f'<option value="{val}">{label}</option>\n'
    tec_options_html += '<option value="__NUEVO__">➕ Agregar nuevo técnico desde este formulario...</option>'

    tec_table_rows_html = ""
    for t in todos_los_tecnicos:
        t_nombre_escaped = html.escape(t['nombre']).replace("'", "\\'")
        if t['activo']:
            status_badge = '<span style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">🟢 Activo</span>'
            action_btn = f"""
            <button type="button" class="btn-del" title="Retirar técnico de la lista activa"
                    onclick="confirmDeleteTecnico('{html.escape(t['id'])}', '{t_nombre_escaped}')"
                    style="padding:4px 8px;font-size:11px;background:#fef2f2;border:1px solid #fecaca;color:#dc2626;border-radius:6px;cursor:pointer;">
                🗑️ Desactivar
            </button>
            """
        else:
            status_badge = '<span style="background:#f1f5f9;color:#64748b;padding:3px 8px;border-radius:12px;font-size:11px;font-weight:700;">⚪ Inactivo</span>'
            action_btn = f"""
            <form method="POST" action="/agendar/tecnicos/reactivar" style="display:inline;margin:0;">
                <input type="hidden" name="tecnico_id" value="{html.escape(t['id'])}">
                <button type="submit" style="background:#eff6ff;border:1px solid #bfdbfe;color:#1d4ed8;padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;">
                    🔄 Reactivar
                </button>
            </form>
            """
        row_bg = "background:#fff;" if t['activo'] else "background:#f8fafc;color:#64748b;"
        tec_table_rows_html += f"""
        <tr style="{row_bg}">
            <td style="padding:8px 10px;"><strong>{html.escape(t['nombre'])}</strong></td>
            <td style="padding:8px 10px;">{html.escape(format_phone_display(t['telefono']))}</td>
            <td style="text-align:center;padding:8px 10px;">{status_badge}</td>
            <td style="text-align:center;padding:8px 10px;">{action_btn}</td>
        </tr>
        """

    tec_filter_options = '<option value="">-- Todos los técnicos --</option>\n'
    for t in tecnicos:
        sel = 'selected' if str(t['id']) == str(filters.get('tecnico_id', '')) else ''
        tec_filter_options += f'<option value="{html.escape(t["id"])}" {sel}>{html.escape(t["nombre"])}</option>\n'

    cli_datalist_options = ""
    for c_nom in clientes_list:
        cli_datalist_options += f'<option value="{html.escape(c_nom)}"></option>\n'

    est_filter_options = '<option value="">-- Todos los estados --</option>\n'
    for est in ["PENDIENTE", "CONFIRMADA", "EN_PROGRESO", "COMPLETADA", "CANCELADA", "REQUIERE_REASIGNACION"]:
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
        elif c["estado"] == "EN_PROGRESO":
            badge_color = "#2563eb"
        elif c["estado"] == "COMPLETADA":
            badge_color = "#7c3aed"

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

        exec_details = []
        if c.get("f_ini_real"):
            exec_details.append(f"▶️ {html.escape(c['f_ini_real'])}")
        if c.get("duracion_real") and c["duracion_real"] != "-":
            exec_details.append(f"⏱️ {html.escape(c['duracion_real'])}")
        if c.get("calificacion"):
            stars_str = "⭐" * int(c["calificacion"])
            exec_details.append(f"<span style='color:#d97706;font-weight:700;'>{stars_str} ({c['calificacion']}/5)</span>")

        exec_html = f"<div style='font-size:11px;color:#334155;margin-top:4px;'>{' • '.join(exec_details)}</div>" if exec_details else ""

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
                {exec_html}
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
    elif info_msg:
        alert_banner = f"""
        <div style="background:#ecfdf5;border-left:4px solid #10b981;padding:16px;border-radius:8px;margin-bottom:20px;color:#065f46;font-size:14px;font-weight:600;">
            ✅ {html.escape(info_msg)}
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
        .btn-purge {{ background: #fff1f2; color: #be123c; border: 1px solid #fecdd3; padding: 11px 16px; border-radius: 8px; font-weight: 700; cursor: pointer; font-size: 14px; text-decoration: none; display: inline-flex; align-items: center; gap: 6px; box-shadow: 0 1px 3px rgba(190, 18, 60, 0.1); transition: all 0.2s; }}
        .btn-purge:hover {{ background: #ffe4e6; color: #9f1239; transform: translateY(-1px); }}
        .btn-preset {{ background: #f8fafc; border: 1px solid #cbd5e1; padding: 5px 10px; border-radius: 6px; font-size: 12px; cursor: pointer; color: #475569; font-weight: 600; transition: background 0.15s; }}
        .btn-preset:hover {{ background: #e2e8f0; color: #0f172a; }}
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
                <select name="titulo" id="titulo" required>
                    <option value="" disabled selected>-- Seleccione el tipo de servicio --</option>
                    <option value="M.P (Preventivo)">M.P (Preventivo)</option>
                    <option value="M.C (Correctivo)">M.C (Correctivo)</option>
                    <option value="D. (Diagnostico)">D. (Diagnostico)</option>
                    <option value="V.T (Visita Tecnica)">V.T (Visita Tecnica)</option>
                    <option value="I. (Instalacion)">I. (Instalacion)</option>
                    <option value="R. (Repuesto)">R. (Repuesto)</option>
                </select>
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
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:8px;">
                    <label style="margin-bottom:0;font-weight:600;">Técnico Asignado *</label>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <button type="button" onclick="openTechModal(true)" 
                                style="background:#2563eb;color:#fff;border:none;font-size:12px;font-weight:700;cursor:pointer;padding:5px 12px;border-radius:6px;display:inline-flex;align-items:center;gap:4px;box-shadow:0 1px 2px rgba(0,0,0,0.05);">
                            ➕ Registrar Técnico
                        </button>
                        <button type="button" onclick="openTechModal(false)" 
                                style="background:#f1f5f9;border:1px solid #cbd5e1;color:#334155;font-size:12px;font-weight:600;cursor:pointer;padding:5px 10px;border-radius:6px;display:inline-flex;align-items:center;gap:4px;">
                            👥 Administrar ({len(tecnicos)})
                        </button>
                    </div>
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
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
                <button type="button" onclick="openPurgeModal()" class="btn-purge" title="Eliminar citas de meses o fechas anteriores">
                    🗑️ Purgar Citas Antiguas
                </button>
                <a href="{html.escape(excel_export_url)}" class="btn-excel" title="Descargar citas filtradas en formato Microsoft Excel">
                    📊 Exportar a Excel (.xlsx)
                </a>
            </div>
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
    <div class="modal-box" style="max-width:580px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
            <h3 style="margin:0;font-size:18px;color:#0f172a;display:flex;align-items:center;gap:8px;">
                👥 Gestión de Personal Técnico
            </h3>
            <button type="button" onclick="closeTechModal()" 
                    style="background:none;border:none;font-size:20px;cursor:pointer;color:#64748b;line-height:1;">
                ✖
            </button>
        </div>
        <p style="font-size:13px;color:#64748b;margin-bottom:14px;">
            Registra nuevos técnicos para el equipo o gestiona el estado del personal existente. Los técnicos activos estarán disponibles inmediatamente para asignación de servicios.
        </p>

        <!-- Formulario para Registrar Nuevo Técnico Directamente -->
        <div style="background:#f0f9ff;border:1px solid #bae6fd;padding:14px 16px;border-radius:10px;margin-bottom:16px;">
            <div style="font-weight:700;color:#0369a1;font-size:13px;margin-bottom:10px;display:flex;align-items:center;gap:6px;">
                ➕ Registrar Nuevo Técnico
            </div>
            <form method="POST" action="/agendar/tecnicos/crear" id="crearTecForm" onsubmit="return validateCrearTecForm()">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                    <div>
                        <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">Nombre Completo *</label>
                        <input type="text" name="nombre" id="modal_nuevo_tecnico_nombre" placeholder="Ej: Pedro Ramírez" required 
                               style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:14px;background:#fff;box-sizing:border-box;">
                    </div>
                    <div>
                        <label style="font-size:12px;font-weight:600;color:#334155;display:block;margin-bottom:4px;">WhatsApp Técnico *</label>
                        <input type="tel" name="telefono" id="modal_nuevo_tecnico_telefono" placeholder="Ej: 310 1234567" required 
                               style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;font-size:14px;background:#fff;box-sizing:border-box;"
                               inputmode="numeric" autocomplete="tel">
                    </div>
                </div>
                <div style="text-align:right;">
                    <button type="submit" class="btn-primary" style="padding:8px 16px;font-size:13px;border-radius:6px;cursor:pointer;background:#0284c7;font-weight:600;">
                        💾 Guardar y Activar Técnico
                    </button>
                </div>
            </form>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
            <div style="font-size:13px;font-weight:700;color:#334155;">
                Técnicos Registrados ({len(todos_los_tecnicos)}):
            </div>
            <div style="font-size:12px;color:#64748b;">
                🟢 {len(tecnicos)} activo(s)
            </div>
        </div>
        <div style="max-height:220px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:16px;">
            <table style="width:100%;font-size:13px;margin:0;">
                <thead>
                    <tr style="background:#f8fafc;position:sticky;top:0;">
                        <th style="padding:8px 10px;">Nombre</th>
                        <th style="padding:8px 10px;">Teléfono</th>
                        <th style="padding:8px 10px;text-align:center;">Estado</th>
                        <th style="padding:8px 10px;text-align:center;width:95px;">Acción</th>
                    </tr>
                </thead>
                <tbody>
                    {tec_table_rows_html if tec_table_rows_html else '<tr><td colspan="4" style="text-align:center;padding:16px;">No hay técnicos registrados.</td></tr>'}
                </tbody>
            </table>
        </div>
        <div class="modal-actions">
            <button type="button" class="btn-modal-cancel" onclick="closeTechModal()">Cerrar</button>
        </div>
    </div>
</div>

<!-- Modal de Confirmación para Eliminar / Desactivar Técnico -->
<div class="modal-overlay" id="deleteTecModal">
    <div class="modal-box">
        <h3 class="modal-title">🗑️ Eliminar / Desactivar Técnico</h3>
        <p class="modal-desc" id="deleteTecModalText">
            ¿Deseas retirar a este técnico del equipo?
        </p>
        <p style="font-size:12px;color:#64748b;margin-bottom:16px;">
            ℹ️ Si el técnico no tiene citas registradas, se eliminará permanentemente de la base de datos. Si tiene citas históricas, se desactivará para proteger los reportes del sistema.
        </p>
        <form method="POST" action="/agendar/tecnicos/eliminar" id="deleteTecForm">
            <input type="hidden" name="tecnico_id" id="deleteTecId" value="">
            <div class="modal-actions">
                <button type="button" class="btn-modal-cancel" onclick="closeDeleteTecModal()">Cancelar</button>
                <button type="submit" class="btn-modal-confirm" style="background:#dc2626;">Sí, Retirar</button>
            </div>
        </form>
    </div>
</div>

<!-- Modal de Purga / Eliminación de Citas Antiguas -->
<div class="modal-overlay" id="purgeModal">
    <div class="modal-box" style="max-width:480px;">
        <h3 class="modal-title" style="color:#be123c;">🗑️ Eliminar Citas por Fecha hacia Atrás</h3>
        <p class="modal-desc" style="color:#475569;margin-bottom:14px;">
            Elimina permanentemente de la base de datos todas las citas registradas con fecha <strong>anterior</strong> a la fecha límite que selecciones.
        </p>
        <form method="POST" action="/agendar/citas/purgar" id="purgeForm" onsubmit="return validatePurgeForm()">
            <div class="form-group" style="margin-bottom:12px;">
                <label style="font-weight:600;font-size:13px;color:#1e293b;margin-bottom:6px;display:block;">
                    📅 Eliminar todas las citas anteriores al día:
                </label>
                <input type="date" name="fecha_limite" id="fechaLimiteInput" required 
                       value="{first_of_this_month}" max="{today_date}"
                       style="width:100%;padding:10px 12px;border:1px solid #cbd5e1;border-radius:8px;font-size:15px;background:#fff;">
            </div>
            
            <div style="margin-bottom:16px;">
                <label style="font-size:12px;font-weight:600;color:#64748b;margin-bottom:6px;display:block;">Accesos rápidos:</label>
                <div style="display:flex;gap:6px;flex-wrap:wrap;">
                    <button type="button" class="btn-preset" onclick="setPurgeDate('{first_of_this_month}')">🗓️ Inicio de este mes ({first_of_this_month})</button>
                    <button type="button" class="btn-preset" onclick="setPurgeDate('{first_prev_month}')">🗓️ Mes anterior ({first_prev_month})</button>
                    <button type="button" class="btn-preset" onclick="setPurgeDate('{first_two_months_ago}')">🗓️ Hace 2 meses ({first_two_months_ago})</button>
                </div>
            </div>

            <div style="background:#fff1f2;border:1px solid #fecdd3;padding:12px;border-radius:8px;margin-bottom:18px;font-size:13px;color:#9f1239;">
                ⚠️ <strong>Advertencia irreversible:</strong> Se borrarán definitivamente todas las citas anteriores a esa fecha, junto con su historial de notificaciones.
            </div>

            <div class="modal-actions">
                <button type="button" class="btn-modal-cancel" onclick="closePurgeModal()">Cancelar</button>
                <button type="submit" class="btn-modal-confirm" style="background:#be123c;">Sí, Purgar Citas Antiguas</button>
            </div>
        </form>
    </div>
</div>

<script>
function openPurgeModal() {{
    document.getElementById('purgeModal').style.display = 'flex';
}}

function closePurgeModal() {{
    document.getElementById('purgeModal').style.display = 'none';
}}

function setPurgeDate(d) {{
    document.getElementById('fechaLimiteInput').value = d;
}}

function validatePurgeForm() {{
    var val = document.getElementById('fechaLimiteInput').value;
    if (!val) {{
        alert('Por favor selecciona una fecha límite.');
        return false;
    }}
    return confirm('⚠️ ¿Estás completamente seguro de que deseas eliminar todas las citas anteriores al ' + val + '?\\n\\nEsta acción es irreversible y borrará el historial de esas fechas.');
}}
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

function openTechModal(focusNew) {{
    document.getElementById('techModal').style.display = 'flex';
    if (focusNew) {{
        setTimeout(function() {{
            var input = document.getElementById('modal_nuevo_tecnico_nombre');
            if (input) input.focus();
        }}, 100);
    }}
}}

function closeTechModal() {{
    document.getElementById('techModal').style.display = 'none';
}}

function confirmDeleteTecnico(tecId, nombre) {{
    document.getElementById('deleteTecId').value = tecId;
    document.getElementById('deleteTecModalText').innerHTML = 
        '¿Deseas retirar a <strong>' + nombre + '</strong> del equipo activo?';
    document.getElementById('deleteTecModal').style.display = 'flex';
}}

function closeDeleteTecModal() {{
    document.getElementById('deleteTecModal').style.display = 'none';
}}

function validateCrearTecForm() {{
    var nom = document.getElementById('modal_nuevo_tecnico_nombre').value.trim();
    var tel = document.getElementById('modal_nuevo_tecnico_telefono').value.trim();
    if (!nom) {{
        alert('Por favor ingresa el nombre del técnico.');
        return false;
    }}
    var digits = tel.replace(/[^0-9]/g, '');
    if (digits.length < 10) {{
        alert('Por favor ingresa un número de WhatsApp válido (mínimo 10 dígitos. Ej: 310 1234567).');
        return false;
    }}
    return true;
}}

// Cerrar modales con Escape o click en fondo
window.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
        closeDeleteModal();
        closeDeleteTecModal();
        closeTechModal();
        closePurgeModal();
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
document.getElementById('purgeModal').addEventListener('click', function(e) {{
    if (e.target === this) closePurgeModal();
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
attachPhoneFormatter('modal_nuevo_tecnico_telefono');

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
            _, citas_export, _, _, _ = fetch_tecnicos_and_citas(filters)
            headers_row = [
                "ID Cita",
                "Servicio / Labor",
                "Fecha y Hora",
                "Inicio Real",
                "Fin Real",
                "Duración Real",
                "Calificación CSAT",
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
                    c.get("f_ini_real") or "",
                    c.get("f_fin_real") or "",
                    c.get("duracion_real") or "",
                    f"{c['calificacion']}/5 ⭐" if c.get("calificacion") else "",
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
                    info_msg=msg_del if msg_del else None,
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
            restart_waha_session(force=True)
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
        if parsed.path == "/agendar/citas/purgar":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            self.handle_purgar_citas_submit()
            return
        if parsed.path == "/agendar/tecnicos/crear":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            self.handle_crear_tecnico_submit()
            return
        if parsed.path == "/agendar/tecnicos/reactivar":
            if not self.is_authenticated():
                self.send_response(302)
                self.send_header("Location", "/agendar")
                self.end_headers()
                return
            self.handle_reactivar_tecnico_submit()
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

            # Regla de Oro 4: Manejo proactivo de eventos de estado de sesión
            if event == "session.status":
                sess_status = payload.get("status")
                print(f"[WAHA Event session.status] Sesión: {data.get('session')} | Estado: {sess_status}", flush=True)
                if sess_status == "FAILED":
                    print(f"[WAHA Auto-Recovery] Estado FAILED detectado. Intentando reinicio con cooldown...", flush=True)
                    restart_waha_session(force=False)
                elif sess_status == "STOPPED":
                    print("[WAHA Status Info] Sesión en STOPPED. No se auto-reinicia por evento para evitar loops de ciclo de vida.", flush=True)
                elif sess_status == "SCAN_QR_CODE":
                    print("[WAHA Critical Alert] La sesión de WhatsApp requiere escanear código QR.", flush=True)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return

            sender_phone = None
            body_text = None
            is_poll_vote = False

            if event == "poll.vote":
                is_poll_vote = True
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
                sender_phone = None
                if "@lid" in raw_from:
                    sender_phone = resolve_lid_to_phone(raw_from)
                elif "@" in raw_from:
                    from_clean = raw_from.split("@")[0]
                    sender_phone = normalize_phone(from_clean)
                body_text = str(payload.get("body") or "").strip()
                print(f"[WAHA Chat Libre Ignorado] De {sender_phone}: '{body_text[:50]}' (Las acciones del bot solo operan mediante encuestas interactivas)", flush=True)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
                return

            if sender_phone and body_text:
                clean_p = "".join(c for c in sender_phone if c.isdigit())

                # FLUJO 1: Técnico inicia labor (voto en encuesta interactiva)
                if "INICIAR" in body_text or "▶️" in body_text:
                    con = get_db()
                    rows = con.run("""
                        SELECT c.id, c.titulo,
                               TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                               cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                               tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                               COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                               c.direccion_servicio
                        FROM citas c
                        JOIN usuarios cli ON c.cliente_id = cli.id
                        JOIN usuarios tec ON c.tecnico_id = tec.id
                        LEFT JOIN usuarios adm ON c.admin_id = adm.id
                        WHERE REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p
                          AND c.estado = 'CONFIRMADA'
                          AND c.fecha_inicio_real IS NULL
                        ORDER BY c.fecha_inicio ASC
                        LIMIT 1
                    """, p=clean_p)
                    if rows:
                        cita_id, titulo, fecha_fmt, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, direccion = rows[0]
                        con.run("""
                            UPDATE citas
                            SET estado = 'EN_PROGRESO'::estado_cita_enum,
                                fecha_inicio_real = NOW(),
                                prompt_inicio_enviado = TRUE,
                                prompt_inicio_enviado_at = COALESCE(prompt_inicio_enviado_at, NOW()),
                                updated_at = NOW()
                            WHERE id = :id
                        """, id=cita_id)
                        con.close()

                        bogota_tz = timezone(timedelta(hours=-5))
                        hora_inicio = datetime.now(bogota_tz).strftime("%I:%M %p")

                        # 1. Responder al técnico
                        tec_msg = (
                            f"⏱️ *Labor Iniciada con Éxito - UT TEKVO*\n\n"
                            f"• *Servicio:* *{titulo}*\n"
                            f"• *Cliente:* {cli_nom} ({cli_tel})\n"
                            f"• *Dirección:* {direccion}\n"
                            f"• *Hora de Inicio:* {hora_inicio}\n\n"
                            f"¡Muchos éxitos en la labor!"
                        )
                        send_waha_text(tec_tel, tec_msg)

                        # 2. Enviar encuesta interactiva para finalizar labor
                        poll_tit = (titulo[:45] + "...") if len(titulo) > 45 else titulo
                        poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                        fin_poll_name = f"🛠️ *UT TEKVO - Finalizar Labor*\n\nLabor en curso: *{poll_tit}* ({poll_cli}).\nPresiona al culminar:"
                        send_waha_poll(tec_tel, fin_poll_name, ["⏹️ Finalizar Labor", "⏳ Sigo trabajando"])

                        # 3. Notificar al administrador (al cliente no se le envía mensaje para evitar redundancia presencial)
                        admin_msg = (
                            f"⏳ *Labor en Progreso - UT TEKVO*\n\n"
                            f"• *ID:* `{str(cita_id)[:8]}`\n"
                            f"• *Servicio:* *{titulo}*\n"
                            f"• *Técnico:* {tec_nom} ({tec_tel})\n"
                            f"• *Cliente:* {cli_nom} ({cli_tel})\n"
                            f"• *Dirección:* {direccion}\n"
                            f"• *Hora Inicio:* {hora_inicio}\n"
                            f"• *Estado:* EN_PROGRESO"
                        )
                        send_waha_text(adm_tel, admin_msg)
                        print(f"[Labor Iniciada] Cita {cita_id} iniciada por {tec_nom}", flush=True)
                    else:
                        con.close()
                        print(f"[Labor Iniciar] No confirmed cita found for technician phone {sender_phone} (clean: {clean_p})", flush=True)
                        if is_poll_vote:
                            send_waha_text(sender_phone, "ℹ️ No tienes servicios en estado CONFIRMADA pendientes por iniciar.")

                # FLUJO 1.5: Técnico avisa que va en camino (voto en encuesta interactiva)
                elif "EN CAMINO" in body_text or "⏳" in body_text:
                    con = get_db()
                    rows = con.run("""
                        SELECT c.id, c.titulo,
                               TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                               cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                               tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                               COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                               c.direccion_servicio
                        FROM citas c
                        JOIN usuarios cli ON c.cliente_id = cli.id
                        JOIN usuarios tec ON c.tecnico_id = tec.id
                        LEFT JOIN usuarios adm ON c.admin_id = adm.id
                        WHERE REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p
                          AND c.estado = 'CONFIRMADA'
                          AND c.fecha_inicio_real IS NULL
                        ORDER BY c.fecha_inicio ASC
                        LIMIT 1
                    """, p=clean_p)
                    if rows:
                        cita_id, titulo, fecha_fmt, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, direccion = rows[0]
                        con.close()

                        # 1. Responder al técnico
                        tec_ack = (
                            f"🛵 ¡Recibido, {tec_nom}! Notificamos al cliente y a la administración que vas en camino hacia {direccion}.\n\n"
                            f"Tan pronto arribes al sitio y des inicio a la labor, presiona [▶️ Iniciar Labor]."
                        )
                        send_waha_text(tec_tel, tec_ack)

                        # 2. Re-enviar poll interactivo al técnico listo para cuando arribe
                        poll_tit = (titulo[:45] + "...") if len(titulo) > 45 else titulo
                        poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                        poll_dir = (direccion[:35] + "...") if len(direccion) > 35 else direccion
                        tec_start_poll = f"🛠️ *UT TEKVO - Inicio de Labor*\n\n¿Ya llegaste para iniciar *{poll_tit}* con {poll_cli}?\n📍 {poll_dir}"
                        send_waha_poll(tec_tel, tec_start_poll, ["▶️ Iniciar Labor", "⏳ En camino"])

                        # 3. Notificar al cliente (sin revelar el teléfono del técnico)
                        cli_notice = (
                            f"🛵 *Aviso de Servicio - UT TEKVO*\n\n"
                            f"Hola {cli_nom}, te informamos que tu técnico asignado *{tec_nom}* ya va en camino hacia tu ubicación para atender tu servicio de *{titulo}*.\n\n"
                            f"📞 Para cualquier duda, reporte o solicitud durante la visita, comunícate con la administración al {adm_tel}."
                        )
                        send_waha_text(cli_tel, cli_notice)

                        # 4. Notificar al administrador
                        adm_notice = (
                            f"🛵 *Técnico en Camino - UT TEKVO*\n\n"
                            f"• *ID:* `{str(cita_id)[:8]}`\n"
                            f"• *Servicio:* *{titulo}*\n"
                            f"• *Hora Programada:* {fecha_fmt}\n"
                            f"• *Técnico:* {tec_nom} ({tec_tel})\n"
                            f"• *Cliente:* {cli_nom} ({cli_tel})\n"
                            f"• *Dirección:* {direccion}\n\n"
                            f"👉 El técnico notificó que va en camino. El cliente ha sido avisado debidamente."
                        )
                        send_waha_text(adm_tel, adm_notice)
                        print(f"[Labor En Camino] Técnico {tec_nom} en camino para cita {cita_id}", flush=True)
                    else:
                        con.close()
                        send_waha_text(sender_phone, "ℹ️ No tienes servicios en estado CONFIRMADA pendientes por iniciar.")

                # FLUJO 2: Técnico finaliza labor (voto en encuesta interactiva)
                elif "FINALIZAR" in body_text or "⏹️" in body_text:
                    con = get_db()
                    rows = con.run("""
                        SELECT c.id, c.titulo,
                               TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                               cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                               tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                               COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                               c.direccion_servicio
                        FROM citas c
                        JOIN usuarios cli ON c.cliente_id = cli.id
                        JOIN usuarios tec ON c.tecnico_id = tec.id
                        LEFT JOIN usuarios adm ON c.admin_id = adm.id
                        WHERE REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p
                          AND c.estado = 'EN_PROGRESO'
                        ORDER BY c.fecha_inicio_real DESC NULLS LAST
                        LIMIT 1
                    """, p=clean_p)
                    if rows:
                        cita_id, titulo, fecha_fmt, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, direccion = rows[0]
                        res_update = con.run("""
                            UPDATE citas
                            SET estado = 'COMPLETADA'::estado_cita_enum,
                                fecha_fin_real = NOW(),
                                updated_at = NOW()
                            WHERE id = :id
                            RETURNING fecha_inicio_real, fecha_fin_real
                        """, id=cita_id)
                        con.close()

                        f_ini_dt = res_update[0][0] if res_update else None
                        f_fin_dt = res_update[0][1] if res_update else None
                        duracion_str = "N/A"
                        if f_ini_dt and f_fin_dt:
                            total_secs = max(0, int((f_fin_dt - f_ini_dt).total_seconds()))
                            hrs = total_secs // 3600
                            mins = (total_secs % 3600) // 60
                            duracion_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins} min"

                        # 1. Responder al técnico
                        tec_msg = (
                            f"✅ *Labor Finalizada con Éxito - UT TEKVO*\n\n"
                            f"• *Servicio:* *{titulo}*\n"
                            f"• *Cliente:* {cli_nom}\n"
                            f"• *Dirección:* {direccion}\n"
                            f"• *Duración Real:* *{duracion_str}*\n\n"
                            f"¡Excelente trabajo!"
                        )
                        send_waha_text(tec_tel, tec_msg)

                        # 2. Notificar al administrador
                        admin_msg = (
                            f"🏁 *Labor Completada - UT TEKVO*\n\n"
                            f"• *ID:* `{str(cita_id)[:8]}`\n"
                            f"• *Servicio:* *{titulo}*\n"
                            f"• *Técnico:* {tec_nom} ({tec_tel})\n"
                            f"• *Cliente:* {cli_nom} ({cli_tel})\n"
                            f"• *Dirección:* {direccion}\n"
                            f"• *Duración Real:* *{duracion_str}*\n"
                            f"• *Estado:* COMPLETADA\n\n"
                            f"👉 Se envió automáticamente la encuesta de satisfacción CSAT al cliente."
                        )
                        send_waha_text(adm_tel, admin_msg)

                        # 3. Enviar encuesta CSAT interactiva al cliente
                        poll_tit = (titulo[:35] + "...") if len(titulo) > 35 else titulo
                        poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                        poll_tec = (tec_nom[:25] + "...") if len(tec_nom) > 25 else tec_nom
                        csat_poll_name = f"⭐ *Calificación Servicio UT TEKVO*\n\nHola {poll_cli}, tu servicio de *{poll_tit}* ha finalizado. ¿Cómo calificarías la atención de {poll_tec}?"
                        csat_options = [
                            "⭐ 5 - Excelente",
                            "⭐ 4 - Muy Bueno",
                            "⭐ 3 - Regular",
                            "⭐ 2 - Malo",
                            "⭐ 1 - Muy Malo"
                        ]
                        send_waha_poll(cli_tel, csat_poll_name, csat_options)
                        print(f"[Labor Finalizada] Cita {cita_id} completada por {tec_nom}, duración: {duracion_str}", flush=True)
                    else:
                        con.close()
                        print(f"[Labor Finalizar] No in-progress cita found for technician phone {sender_phone} (clean: {clean_p})", flush=True)
                        send_waha_text(sender_phone, "ℹ️ No tienes servicios en estado EN PROGRESO pendientes por finalizar.")

                # FLUJO 2.5: Técnico presiona [⏳ Sigo trabajando] (voto en encuesta interactiva)
                elif any(k in body_text for k in ["SIGO TRABAJANDO", "TRABAJANDO", "⏳"]):
                    con = get_db()
                    rows = con.run("""
                        SELECT c.id, c.titulo,
                               cli.nombre AS cli_nom,
                               tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                               c.direccion_servicio
                        FROM citas c
                        JOIN usuarios cli ON c.cliente_id = cli.id
                        JOIN usuarios tec ON c.tecnico_id = tec.id
                        WHERE REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p
                          AND c.estado = 'EN_PROGRESO'
                        ORDER BY c.fecha_inicio_real DESC NULLS LAST
                        LIMIT 1
                    """, p=clean_p)
                    if rows:
                        cita_id, titulo, cli_nom, tec_nom, tec_tel, direccion = rows[0]
                        con.close()
                        send_waha_text(tec_tel, f"👍 ¡Entendido, {tec_nom}! El servicio *{titulo}* continúa en progreso.\n\nTan pronto termines, presiona aquí para registrar la finalización:")
                        poll_tit = (titulo[:45] + "...") if len(titulo) > 45 else titulo
                        poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                        fin_poll_name = f"🛠️ *UT TEKVO - Finalizar Labor*\n\nLabor en curso: *{poll_tit}* ({poll_cli}).\nPresiona al culminar:"
                        send_waha_poll(tec_tel, fin_poll_name, ["⏹️ Finalizar Labor", "⏳ Sigo trabajando"])
                    else:
                        con.close()
                        send_waha_text(sender_phone, "ℹ️ No tienes servicios en estado EN PROGRESO en este momento.")

                # FLUJO 3: Calificación CSAT (voto en encuesta interactiva)
                elif "⭐" in body_text or any(k in body_text for k in ["EXCELENTE", "MUY BUENO", "REGULAR", "MUY MALO", "MALO"]):
                    score = None
                    if "5" in body_text or "EXCELENTE" in body_text:
                        score = 5
                    elif "4" in body_text or "MUY BUENO" in body_text:
                        score = 4
                    elif "3" in body_text or "REGULAR" in body_text:
                        score = 3
                    elif "2" in body_text or ("MALO" in body_text and "MUY" not in body_text):
                        score = 2
                    elif "1" in body_text or "MUY MALO" in body_text:
                        score = 1

                    if score is not None:
                        con = get_db()
                        rows = con.run("""
                            SELECT c.id, c.titulo,
                                   TO_CHAR(c.fecha_inicio AT TIME ZONE 'America/Bogota', 'YYYY-MM-DD HH24:MI') AS fecha_fmt,
                                   cli.nombre AS cli_nom, cli.telefono_whatsapp AS cli_tel,
                                   tec.nombre AS tec_nom, tec.telefono_whatsapp AS tec_tel,
                                   COALESCE(adm.telefono_whatsapp, '+573118198511') AS adm_tel,
                                   c.direccion_servicio
                            FROM citas c
                            JOIN usuarios cli ON c.cliente_id = cli.id
                            JOIN usuarios tec ON c.tecnico_id = tec.id
                            LEFT JOIN usuarios adm ON c.admin_id = adm.id
                            WHERE REGEXP_REPLACE(cli.telefono_whatsapp, '[^0-9]', '', 'g') = :p
                              AND c.estado = 'COMPLETADA'
                              AND c.calificacion IS NULL
                            ORDER BY c.fecha_fin_real DESC NULLS LAST, c.updated_at DESC
                            LIMIT 1
                        """, p=clean_p)
                        if rows:
                            cita_id, titulo, fecha_fmt, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, direccion = rows[0]
                            con.run("UPDATE citas SET calificacion = :score, updated_at = NOW() WHERE id = :id", score=score, id=cita_id)
                            con.close()

                            # Responder al cliente
                            send_waha_text(
                                cli_tel,
                                f"🙌 ¡Muchas gracias por tu calificación de {score}/5 ⭐!\n"
                                f"En UT TEKVO valoramos tu opinión para seguir brindando el mejor servicio.\n\n"
                                f"📞 Para nuevas solicitudes o soporte, comunícate con nuestra administración al {adm_tel}."
                            )

                            # Notificar al técnico
                            send_waha_text(tec_tel, f"⭐ *Calificación de Cliente - UT TEKVO*\n\nEl cliente {cli_nom} ha calificado tu servicio en *{titulo}* con *{score}/5 ⭐*.")

                            # Notificar al administrador con reporte completo
                            stars_bar = "⭐" * score
                            if score <= 2:
                                header_csat = "🚨 *ALERTA CSAT BAJO (Calificación Negativa) - UT TEKVO*"
                                guia_csat = "👉 *Atención Inmediata:* Se sugiere contactar al cliente de inmediato para seguimiento y atención de garantía / calidad."
                            elif score == 3:
                                header_csat = "⚠️ *Calificación Regular Recibida - UT TEKVO*"
                                guia_csat = "👉 Se recomienda revisar posibles oportunidades de mejora en el servicio con el técnico."
                            else:
                                header_csat = "⭐ *Nueva Calificación Positiva Recibida - UT TEKVO*"
                                guia_csat = "👉 ¡Cliente satisfecho con la atención técnica brindada!"

                            adm_alert = (
                                f"{header_csat}\n\n"
                                f"📋 *Datos del Servicio:*\n"
                                f"• *ID:* `{str(cita_id)[:8]}`\n"
                                f"• *Servicio:* *{titulo}*\n"
                                f"• *Fecha:* {fecha_fmt}\n"
                                f"• *Dirección:* {direccion}\n\n"
                                f"👤 *Cliente Calificador:*\n"
                                f"• *Nombre:* *{cli_nom}*\n"
                                f"• *Teléfono:* {cli_tel}\n\n"
                                f"🔧 *Técnico Responsable:*\n"
                                f"• *Nombre:* *{tec_nom}*\n"
                                f"• *Teléfono:* {tec_tel}\n\n"
                                f"⭐ *Puntuación Otorgada:* {stars_bar} *({score}/5)*\n\n"
                                f"{guia_csat}"
                            )
                            send_waha_text(adm_tel, adm_alert)
                            print(f"[CSAT Registrado] Cita {cita_id} calificada con {score}/5 por {cli_nom}", flush=True)
                        else:
                            con.close()
                            print(f"[CSAT Warning] No unrated completed cita found for client {sender_phone} (clean: {clean_p})", flush=True)
                            if is_poll_vote:
                                send_waha_text(sender_phone, "ℹ️ Gracias por responder. No tienes servicios completados pendientes por calificar.")

                # FLUJO 4: Confirmación o Cancelación previa a la labor (exclusivo vía Encuesta Interactiva)
                else:
                    action = None
                    if any(k in body_text for k in ["CONFIRM", "SÍ", "SI", "✅"]):
                        action = "CONFIRMAR"
                    elif any(k in body_text for k in ["CANCEL", "NO", "❌"]):
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
                                   CASE WHEN REGEXP_REPLACE(cli.telefono_whatsapp, '[^0-9]', '', 'g') = :p THEN 'CLIENTE' ELSE 'TECNICO' END AS rol,
                                   c.direccion_servicio, c.descripcion,
                                   (c.fecha_inicio <= NOW()) AS es_ahora
                            FROM citas c
                            JOIN usuarios cli ON c.cliente_id = cli.id
                            JOIN usuarios tec ON c.tecnico_id = tec.id
                            LEFT JOIN usuarios adm ON c.admin_id = adm.id
                            WHERE (REGEXP_REPLACE(cli.telefono_whatsapp, '[^0-9]', '', 'g') = :p 
                                OR REGEXP_REPLACE(tec.telefono_whatsapp, '[^0-9]', '', 'g') = :p)
                              AND c.fecha_inicio >= NOW() - INTERVAL '30 minutes'
                              AND c.estado IN ('PENDIENTE', 'CONFIRMADA', 'REQUIERE_REASIGNACION')
                            ORDER BY c.fecha_inicio ASC
                            LIMIT 1
                        """, p=clean_p)

                        if rows:
                            r = rows[0]
                            cita_id, titulo, fecha_fmt, estado_actual, conf_cli, conf_tec, cli_nom, cli_tel, tec_nom, tec_tel, adm_tel, rol, direccion, descripcion, es_ahora = r

                            # Control de Idempotencia: Si ya estaba en ese estado, no reenviar la plantilla completa
                            if rol == "TECNICO":
                                if action == "CONFIRMAR" and conf_tec == "CONFIRMADA":
                                    con.close()
                                    if is_poll_vote:
                                        send_waha_text(sender_phone, f"ℹ️ Hola {tec_nom}, la disponibilidad para tu labor ({titulo} - {fecha_fmt}) ya se encuentra registrada como *CONFIRMADA*. ¡Todo listo!")
                                    return
                                elif action == "CANCELAR" and conf_tec == "CANCELADA":
                                    con.close()
                                    if is_poll_vote:
                                        send_waha_text(sender_phone, f"ℹ️ Hola {tec_nom}, tu respuesta para ({titulo} - {fecha_fmt}) ya fue registrada como cancelada anteriormente.")
                                    return
                            else:  # CLIENTE
                                if action == "CONFIRMAR" and conf_cli == "CONFIRMADA":
                                    con.close()
                                    if is_poll_vote:
                                        send_waha_text(sender_phone, f"ℹ️ Hola {cli_nom}, tu asistencia para la cita de {titulo} ({fecha_fmt}) ya se encuentra registrada como *CONFIRMADA*. ¡Gracias!")
                                    return
                                elif action == "CANCELAR" and conf_cli == "CANCELADA":
                                    con.close()
                                    if is_poll_vote:
                                        send_waha_text(sender_phone, f"ℹ️ Hola {cli_nom}, tu cancelación para {titulo} ya fue procesada anteriormente.")
                                    return

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

                            if rol == "TECNICO":
                                if action == "CONFIRMAR":
                                    reply_msg = (
                                        f"🙌 ¡Muchas gracias, {tec_nom}! Tu disponibilidad para la labor técnica ha sido registrada exitosamente como *CONFIRMADA*.\n\n"
                                        f"📋 *Detalles de la Labor Asignada:*\n"
                                        f"• *Servicio:* {titulo}\n"
                                        f"• *Fecha y Hora:* {fecha_fmt}\n"
                                        f"• *Cliente:* {cli_nom}\n"
                                        f"• *Teléfono Cliente:* {cli_tel}\n"
                                        f"• *Dirección:* {direccion}\n"
                                    )
                                    if descripcion:
                                        reply_msg += f"• *Notas:* {descripcion}\n"
                                    reply_msg += "\n¡Gracias por tu compromiso con el servicio de UT TEKVO!"
                                else:
                                    reply_msg = (
                                        f"⚠️ Hola {tec_nom}, tu respuesta para el servicio *{titulo}* ({fecha_fmt}) con el cliente {cli_nom} ha sido registrada como *CANCELADA / NO DISPONIBLE*.\n\n"
                                        f"El administrador de UT TEKVO ha sido notificado para reasignar la labor."
                                    )
                            else:  # CLIENTE
                                if action == "CONFIRMAR":
                                    reply_msg = (
                                        f"🙌 ¡Muchas gracias, {cli_nom}! Tu asistencia ha sido registrada exitosamente como *CONFIRMADA*.\n\n"
                                        f"📋 *Detalles de tu Cita:*\n"
                                        f"• *Servicio:* {titulo}\n"
                                        f"• *Fecha y Hora:* {fecha_fmt}\n"
                                        f"• *Técnico Asignado:* {tec_nom}\n"
                                        f"• *Dirección:* {direccion}\n\n"
                                        f"📞 *Atención y Soporte:* Toda comunicación, cambio o solicitud sobre tu servicio debe realizarse directamente a través de la administración: {adm_tel}.\n\n"
                                        f"Nuestro personal técnico estará puntual en tu ubicación. ¡Gracias por confiar en UT TEKVO!"
                                    )
                                else:
                                    reply_msg = (
                                        f"⚠️ Hola {cli_nom}, tu cita para *{titulo}* programada para el {fecha_fmt} ha sido registrada como *CANCELADA*.\n\n"
                                        f"📞 Si deseas reprogramar el servicio o tienes alguna inquietud, comunícate directamente con la administración de UT TEKVO al {adm_tel}."
                                    )
                            send_waha_text(sender_phone, reply_msg)

                            if rol == "CLIENTE" and action == "CANCELAR":
                                tec_alert = (
                                    f"⚠️ *Aviso de Cancelación de Cita*\n\n"
                                    f"Hola {tec_nom}, la cita de *{titulo}* programada para {fecha_fmt} con el cliente {cli_nom} ({cli_tel}) en {direccion} ha sido *CANCELADA* por el cliente.\n\n"
                                    f"Tu agenda queda liberada en esa franja horaria."
                                )
                                send_waha_text(tec_tel, tec_alert)

                            quien_nom = cli_nom if rol == "CLIENTE" else tec_nom
                            quien_tel = cli_tel if rol == "CLIENTE" else tec_tel

                            est_cli_str = "✅ CONFIRMADA" if nuevo_conf_cli == "CONFIRMADA" else ("❌ CANCELADA" if nuevo_conf_cli == "CANCELADA" else "⏳ PENDIENTE")
                            est_tec_str = "✅ CONFIRMADA" if nuevo_conf_tec == "CONFIRMADA" else ("❌ CANCELADA" if nuevo_conf_tec == "CANCELADA" else "⏳ PENDIENTE")

                            if nuevo_estado == "CONFIRMADA":
                                header_alert = "🎉 *CITA 100% CONFIRMADA POR AMBOS - UT TEKVO*"
                                if es_ahora:
                                    guia_accion = "👉 *Ambos confirmaron:* La cita está en horario de ejecución. Se envió automáticamente la opción interactiva [▶️ Iniciar Labor] al técnico."
                                else:
                                    guia_accion = f"👉 *Ambos confirmaron:* Cita confirmada para el {fecha_fmt}. La opción interactiva [▶️ Iniciar Labor] se enviará automáticamente al técnico a la hora programada del servicio."
                            elif nuevo_estado == "CANCELADA":
                                header_alert = "🚨 *ALERTA: CITA CANCELADA POR EL CLIENTE - UT TEKVO*"
                                guia_accion = f"👉 El cliente canceló la cita. La agenda del técnico {tec_nom} fue liberada automáticamente."
                            elif nuevo_estado == "REQUIERE_REASIGNACION":
                                header_alert = "🚨 *URGENTE: TÉCNICO NO DISPONIBLE - UT TEKVO*"
                                guia_accion = f"👉 *ACCIÓN REQUERIDA:* El técnico {tec_nom} indicó no estar disponible. Reasignar técnico para este servicio de inmediato."
                            else:
                                header_alert = "🔔 *Confirmación Parcial de Cita - UT TEKVO*"
                                if nuevo_conf_cli == "CONFIRMADA":
                                    guia_accion = f"👉 *Pendiente:* Falta confirmación del técnico {tec_nom} ({tec_tel})."
                                else:
                                    guia_accion = f"👉 *Pendiente:* Falta confirmación del cliente {cli_nom} ({cli_tel})."

                            admin_alert = (
                                f"{header_alert}\n\n"
                                f"📋 *Datos de la Cita:*\n"
                                f"• *ID:* `{str(cita_id)[:8]}`\n"
                                f"• *Servicio:* *{titulo}*\n"
                                f"• *Fecha y Hora:* *{fecha_fmt}*\n"
                                f"• *Dirección:* {direccion}\n\n"
                                f"👤 *Quien Respondió Ahora:*\n"
                                f"• *Persona:* *{quien_nom}* ({rol})\n"
                                f"• *Teléfono:* {quien_tel}\n"
                                f"• *Respuesta:* {'✅ CONFIRMADO' if action == 'CONFIRMAR' else '❌ CANCELADO'}\n\n"
                                f"📊 *Estado en Vivo de Ambas Partes:*\n"
                                f"• *Cliente:* {cli_nom} ({cli_tel}) ➔ {est_cli_str}\n"
                                f"• *Técnico:* {tec_nom} ({tec_tel}) ➔ {est_tec_str}\n"
                                f"• *Estado General:* *{nuevo_estado}*\n\n"
                                f"{guia_accion}"
                            )

                            if nuevo_estado == "CONFIRMADA":
                                if es_ahora:
                                    poll_tit = (titulo[:45] + "...") if len(titulo) > 45 else titulo
                                    poll_cli = (cli_nom[:25] + "...") if len(cli_nom) > 25 else cli_nom
                                    poll_dir = (direccion[:35] + "...") if len(direccion) > 35 else direccion
                                    tec_start_poll = f"🛠️ *UT TEKVO - Inicio de Labor*\n\n¿Listo para iniciar *{poll_tit}* con {poll_cli}?\n📍 {poll_dir}"
                                    send_waha_poll(tec_tel, tec_start_poll, ["▶️ Iniciar Labor", "⏳ En camino"])
                                    con_p = get_db()
                                    con_p.run("""
                                        UPDATE citas
                                        SET prompt_inicio_enviado = TRUE,
                                            prompt_inicio_enviado_at = NOW(),
                                            updated_at = NOW()
                                        WHERE id = :id
                                    """, id=cita_id)
                                    con_p.close()
                                else:
                                    print(f"[Cita Confirmada] Cita {cita_id} confirmada para {fecha_fmt}. La opción interactiva [▶️ Iniciar Labor] se despachará en el horario exacto programado.", flush=True)

                            send_waha_text(adm_tel, admin_alert)
                            print(f"[Admin Alert Sent] to {adm_tel}: {admin_alert[:60]}...", flush=True)

                        else:
                            con.close()
                            print(f"[WAHA Poll Vote] No pending cita found for phone {sender_phone} (clean: {clean_p})", flush=True)
                            send_waha_text(sender_phone, "ℹ️ No se encontró ninguna cita futura pendiente de confirmación asociada a este voto.")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        except Exception as e:
            print(f"[WAHA Inbound Error] {e}")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"error"}')

    def handle_crear_tecnico_submit(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_post = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(raw_post)
            nombre = form.get("nombre", [""])[0].strip()
            tel_raw = form.get("telefono", [""])[0].strip()
            telefono = normalize_phone(tel_raw)
            digits_only = "".join(c for c in telefono if c.isdigit())
            if not nombre or len(digits_only) < 10:
                self.send_response(302)
                self.send_header("Location", "/agendar?error=" + urllib.parse.quote("Por favor ingresa un nombre y un teléfono de WhatsApp válido (mínimo 10 dígitos)."))
                self.end_headers()
                return

            email = f"tec_{digits_only}@tekvo.co"
            con = get_db()
            con.run("""
                INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol, activo, updated_at)
                VALUES (:n, :e, :t, 'TECNICO', true, NOW())
                ON CONFLICT (email) DO UPDATE
                SET nombre = EXCLUDED.nombre,
                    telefono_whatsapp = EXCLUDED.telefono_whatsapp,
                    rol = 'TECNICO',
                    activo = true,
                    updated_at = NOW()
            """, n=nombre, e=email, t=telefono)
            con.close()
            msg = f"Técnico '{nombre}' guardado y activado exitosamente en el equipo."

            self.send_response(302)
            self.send_header("Location", "/agendar?msg=" + urllib.parse.quote(msg))
            self.end_headers()
        except Exception as e:
            print(f"[Crear Tecnico Error] {e}", flush=True)
            self.send_response(302)
            self.send_header("Location", "/agendar?error=" + urllib.parse.quote(str(e)))
            self.end_headers()

    def handle_reactivar_tecnico_submit(self):
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

            con = get_db()
            rows = con.run("UPDATE usuarios SET activo = true, updated_at = NOW() WHERE id = :id AND rol = 'TECNICO' RETURNING nombre", id=tecnico_id)
            con.close()
            nombre = rows[0][0] if rows else "Técnico"
            self.send_response(302)
            self.send_header("Location", "/agendar?msg=" + urllib.parse.quote(f"Técnico '{nombre}' reactivado exitosamente."))
            self.end_headers()
        except Exception as e:
            print(f"[Reactivar Tecnico Error] {e}", flush=True)
            self.send_response(302)
            self.send_header("Location", "/agendar?error=" + urllib.parse.quote(str(e)))
            self.end_headers()

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

    def handle_purgar_citas_submit(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_post = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(raw_post)
            fecha_limite = form.get("fecha_limite", [""])[0].strip()
            if not fecha_limite:
                self.send_response(302)
                self.send_header("Location", "/agendar?error=" + urllib.parse.quote("Debes seleccionar una fecha límite."))
                self.end_headers()
                return
            ok, msg = delete_citas_anteriores(fecha_limite)
            param = "msg=" if ok else "error="
            self.send_response(302)
            self.send_header("Location", f"/agendar?{param}" + urllib.parse.quote(msg))
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
                con.run("""
                    INSERT INTO usuarios (nombre, email, telefono_whatsapp, rol, activo, updated_at)
                    VALUES (:n, :e, :t, 'TECNICO', true, NOW())
                    ON CONFLICT (email) DO UPDATE
                    SET nombre = EXCLUDED.nombre,
                        telefono_whatsapp = EXCLUDED.telefono_whatsapp,
                        rol = 'TECNICO',
                        activo = true,
                        updated_at = NOW()
                """, n=tecnico_nombre, e=tecnico_email, t=tecnico_tel)
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
                "fecha_label": f"{fecha} {hora_inicio}",
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
    daemon_thread = threading.Thread(target=start_prompt_daemon_loop, daemon=True, name="StartPromptDaemon")
    daemon_thread.start()
    heartbeat_thread = threading.Thread(target=waha_heartbeat_daemon_loop, daemon=True, name="WAHAHeartbeatDaemon")
    heartbeat_thread.start()
    server = ThreadingHTTPServer(("0.0.0.0", 8000), MetaBridgeHandler)
    print("Meta Bridge & Portal Agendamiento escuchando en 0.0.0.0:8000")
    server.serve_forever()
