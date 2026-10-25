# 🛠️ Scripts de Utilidad y Migraciones

Esta carpeta contiene utilidades y scripts de mantenimiento ejecutados durante la configuración, migración o ajuste de flujos y base de datos:

| Script | Descripción |
| :--- | :--- |
| `apply_dynamic_character_budget.py` | Configura el presupuesto dinámico de caracteres en el workflow de n8n para garantizar que los polls de WhatsApp nunca excedan el límite estricto de 255 caracteres de WAHA/WhatsApp. |
| `apply_smart_scheduling_flow.py` | Configura la bifurcación lógica en n8n: encuestas interactivas con botones si la cita inicia en < 24h, o confirmación informativa + recordatorio diferido a 24h si inicia en > 24h. |
| `update_admin_phone_everywhere.py` | Actualiza de forma atómica y consistente el número de teléfono del administrador en PostgreSQL, `.env`, `meta_bridge.py` y nodos de n8n. |
| `upgrade_multi_admin.py` | Migra la estructura de la base de datos para soportar múltiples administradores con asignación explícita por cita (`admin_id`). |
| `fix_technician_poll_length.py` / `fix_n8n_waha.py` | Herramientas de diagnóstico y parcheo para validación de endpoints y payloads de encuestas interactivas de WAHA. |
| `apply_poll_and_cron_fix.py` / `fix_workflow.py` | Ajustes de sincronización para el cron de recordatorios cada 15 minutos en n8n. |
