import unittest
import json
import re

class TestClientPrivacy(unittest.TestCase):
    def setUp(self):
        with open('/home/cortes/stacks/citas-sistema/workflows/n8n_citas_workflow.json', 'r', encoding='utf-8') as f:
            self.wf = json.load(f)
        with open('/home/cortes/stacks/citas-sistema/meta_bridge.py', 'r', encoding='utf-8') as f:
            self.meta_code = f.read()

    def test_n8n_creation_client_node(self):
        node = next(n for n in self.wf['nodes'] if n['name'] == 'WA: Notificar Creacion a Cliente')
        body = node['parameters']['jsonBody']
        # Must NOT expose technician phone
        self.assertNotIn("tecnico_telefono", body)
        # Must include admin phone reference
        self.assertIn("admin_telefono", body)

    def test_n8n_responder_boton_node(self):
        node = next(n for n in self.wf['nodes'] if n['name'] == 'WA: Responder a Quien Presiono Boton')
        body = node['parameters']['jsonBody']
        # Check that admin phone is defined in the body
        self.assertIn("admin_telefono", body)
        # In client branch, must NOT have tecnico_telefono
        client_branch = body.split('if ($json.rol_que_respondio === "CLIENTE")')[1].split('} else {')[0]
        self.assertNotIn("tecnico_telefono", client_branch)
        self.assertIn("adm", client_branch)

    def test_meta_bridge_client_confirmation(self):
        # Locate the reply_msg section for CLIENTE
        client_section_match = re.search(r'else:\s*# CLIENTE\s*\n\s*if action == "CONFIRMAR":\s*\n\s*reply_msg = \((.*?)\n\s*\)\s*\n\s*else:\s*\n\s*reply_msg = \((.*?)\n\s*\)', self.meta_code, re.DOTALL)
        self.assertIsNotNone(client_section_match, "CLIENTE reply_msg block not found in meta_bridge.py")
        confirm_msg, cancel_msg = client_section_match.groups()
        
        # In confirm_msg: MUST NOT have tec_tel
        self.assertNotIn("tec_tel", confirm_msg)
        # In confirm_msg: MUST have adm_tel
        self.assertIn("adm_tel", confirm_msg)

        # In cancel_msg: MUST NOT have tec_tel
        self.assertNotIn("tec_tel", cancel_msg)
        # In cancel_msg: MUST have adm_tel
        self.assertIn("adm_tel", cancel_msg)

    def test_meta_bridge_labor_start_client_msg(self):
        # Check start labor message to client
        cli_msg_match = re.search(r'# 3\. Notificar al cliente\s*\n\s*cli_msg = \((.*?)\n\s*\)\s*\n\s*send_waha_text\(cli_tel', self.meta_code, re.DOTALL)
        self.assertIsNotNone(cli_msg_match, "cli_msg for start labor not found")
        msg = cli_msg_match.group(1)
        self.assertNotIn("tec_tel", msg)
        self.assertIn("adm_tel", msg)

    def test_meta_bridge_csat_thank_you_client_msg(self):
        # Check CSAT thank you messages to client
        self.assertNotIn("tec_tel", self.meta_code.split("🙌 ¡Muchas gracias por tu calificación")[1].split("send_waha_text")[0])
        self.assertIn("adm_tel", self.meta_code.split("🙌 ¡Muchas gracias por tu calificación")[1].split("send_waha_text")[0])

if __name__ == '__main__':
    unittest.main()
