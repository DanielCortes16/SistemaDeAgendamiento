import urllib.request
import urllib.parse
import json
import http.cookiejar

# 1. Setup session / cookiejar for authentication
cookie_jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))

# Log in
login_data = urllib.parse.urlencode({
    "username": "servicio@tekvo.co",
    "password": "3118198511"
}).encode("utf-8")

login_req = urllib.request.Request("http://127.0.0.1:8088/agendar/login", data=login_data, method="POST")
resp = opener.open(login_req)
print("Login status:", resp.status)

# 2. Test GET /agendar to verify initial technicians
req = urllib.request.Request("http://127.0.0.1:8088/agendar")
html = opener.open(req).read().decode("utf-8")
assert "➕ Registrar Técnico" in html, "Button '➕ Registrar Técnico' not found in /agendar"
assert "👥 Administrar" in html, "Button '👥 Administrar' not found in /agendar"
assert "Felipe" in html, "Felipe should be in /agendar"
assert "Daniel" in html, "Daniel should be in /agendar"
assert "Victor Cossio" in html, "Victor Cossio should be in /agendar"
print("Initial /agendar page verified: Felipe, Daniel, and Victor Cossio are present.")

# 3. Test POST /agendar/tecnicos/crear - Register new technician
new_tec_data = urllib.parse.urlencode({
    "nombre": "Andres Tecnico Prueba",
    "telefono": "3123456789"
}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8088/agendar/tecnicos/crear", data=new_tec_data, method="POST")
resp = opener.open(req)
html_after_create = resp.read().decode("utf-8")
assert "Andres Tecnico Prueba" in html_after_create, "New technician not found in /agendar after creation"
assert "Felipe" in html_after_create, "Felipe should STILL be present (NOT replaced!)"
assert "Daniel" in html_after_create, "Daniel should STILL be present (NOT replaced!)"
assert "Victor Cossio" in html_after_create, "Victor Cossio should STILL be present (NOT replaced!)"
print("Test 1 passed: New technician created successfully without eliminating previous technicians!")

# Find Andres' ID in the page
import re
andres_match = re.search(r"confirmDeleteTecnico\('([a-f0-9\-]+)',\s*'Andres Tecnico Prueba'\)", html_after_create)
assert andres_match, "Could not find Andres ID in page"
andres_id = andres_match.group(1)
print(f"Found Andres ID: {andres_id}")

# 4. Test POST /agendar/tecnicos/eliminar - Deactivate technician
del_tec_data = urllib.parse.urlencode({
    "tecnico_id": andres_id
}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8088/agendar/tecnicos/eliminar", data=del_tec_data, method="POST")
resp = opener.open(req)
html_after_del = resp.read().decode("utf-8")
assert "Reactivar" in html_after_del, "Reactivar button should appear for deactivated technician"
assert andres_id in html_after_del, "Andres should appear in modal as inactive"
print("Test 2 passed: Technician deactivated cleanly, with option to reactivate.")

# 5. Test POST /agendar/tecnicos/reactivar - Reactivate technician
react_tec_data = urllib.parse.urlencode({
    "tecnico_id": andres_id
}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8088/agendar/tecnicos/reactivar", data=react_tec_data, method="POST")
resp = opener.open(req)
html_after_react = resp.read().decode("utf-8")
# Check that Andres is active again
assert "Andres Tecnico Prueba" in html_after_react
print("Test 3 passed: Technician reactivated successfully!")

# 6. Clean up test technician
import subprocess
subprocess.run([
    'docker', 'exec', 'citas_postgres', 'psql', '-U', 'citas_admin', '-d', 'citas_db',
    '-c', "DELETE FROM usuarios WHERE email = 'tec_573123456789@tekvo.co';"
], check=True)
print("Cleaned up test technician Andres.")

print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
