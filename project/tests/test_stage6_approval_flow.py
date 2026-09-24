import os
import sys
from pathlib import Path
import json
import uuid
import datetime

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch, MagicMock
from agent.graph import graph
from services.approvals import (
    compute_payload_hash,
    generate_approval_token_hash,
    parse_approval_reply,
    validate_and_process_approval,
    create_pending_approval,
)


class TestStage6ApprovalFlow(unittest.TestCase):
    """Stage 6 Verification Tests per IMPLEMENTATION_STAGES.md and PROJECT_SPEC.md §11."""

    def test_parse_approval_reply(self):
        """Test parsing of WhatsApp approval commands."""
        # 1. Standard APPROVE
        res = parse_approval_reply("APPROVE APR-1234AB")
        self.assertIsNotNone(res)
        self.assertEqual(res["action"], "APPROVE")
        self.assertEqual(res["approval_code"], "APR-1234AB")

        # 2. Case insensitive with spaces
        res2 = parse_approval_reply("  approve   apr-5678cd  ")
        self.assertIsNotNone(res2)
        self.assertEqual(res2["action"], "APPROVE")
        self.assertEqual(res2["approval_code"], "APR-5678CD")

        # 3. REJECT with reason
        res3 = parse_approval_reply("REJECT APR-1234AB Exceeds monthly budget")
        self.assertIsNotNone(res3)
        self.assertEqual(res3["action"], "REJECT")
        self.assertEqual(res3["approval_code"], "APR-1234AB")
        self.assertEqual(res3["extra_text"], "Exceeds monthly budget")

        # 4. EDIT with payload
        res4 = parse_approval_reply("EDIT APR-1234AB {\"required\": true}")
        self.assertIsNotNone(res4)
        self.assertEqual(res4["action"], "EDIT")
        self.assertEqual(res4["extra_text"], "{\"required\": true}")

        # 5. Non-approval text returns None
        self.assertIsNone(parse_approval_reply("Add an expense of 5000 to Metro"))
        self.assertIsNone(parse_approval_reply("Hello bot"))

    @patch("services.approvals.execute_query")
    def test_checklist_role_unauthorized_fails_with_invalid_context(self, mock_query):
        """Active user without matching approver role fails with invalid_approval_context."""
        approver_hash = "approver_unauth_hash"
        approval_code = "APR-TEST01"

        def mock_db(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                # User exists and is active, but only has field_worker role
                return [{"id": "user-worker-1", "display_name": "Field Worker", "role": "field_worker", "is_active": True}]
            if "FROM PUBLIC.PENDING_APPROVALS" in sql_clean:
                return [{
                    "id": "11111111-1111-1111-1111-111111111111",
                    "run_id": "run-1",
                    "thread_id": "thread-1",
                    "requested_by": "user-requester-1",
                    "required_approver_role": "project_admin",
                    "operation": "create_project_field",
                    "proposed_payload": {"project_id": "proj-1", "field_name": "temperature"},
                    "status": "pending",
                    "approval_token_hash": "token-hash-1",
                    "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat(),
                }]
            if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                # No field approval permission
                return [{"can_approve_fields": False}]
            return []

        mock_query.side_effect = mock_db

        result = validate_and_process_approval(
            approval_code=approval_code,
            approver_sender_hash=approver_hash,
            action="APPROVE",
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["decision_reason"], "invalid_approval_context")

    @patch("services.approvals.execute_query")
    def test_checklist_stale_or_already_decided_rejected(self, mock_query):
        """Stale or already decided approval is rejected rather than re-executed."""
        approver_hash = "approver_admin_hash"
        approval_code = "APR-TEST02"

        def mock_db(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                return [{"id": "user-admin-1", "display_name": "Admin", "role": "project_admin", "is_active": True}]
            if "FROM PUBLIC.PENDING_APPROVALS" in sql_clean:
                # Already approved status
                return [{
                    "id": "22222222-2222-2222-2222-222222222222",
                    "run_id": "run-2",
                    "thread_id": "thread-2",
                    "requested_by": "user-requester-1",
                    "required_approver_role": "project_admin",
                    "operation": "create_project_field",
                    "proposed_payload": {"project_id": "proj-1"},
                    "status": "approved",
                    "approval_token_hash": "token-hash-2",
                    "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat(),
                }]
            return []

        mock_query.side_effect = mock_db

        result = validate_and_process_approval(
            approval_code=approval_code,
            approver_sender_hash=approver_hash,
            action="APPROVE",
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["decision_reason"], "invalid_approval_context")

    @patch("services.approvals.execute_query")
    def test_checklist_token_or_payload_tampered_rejected(self, mock_query):
        """Tampered token hash or modified payload triggers invalid_approval_context."""
        approver_hash = "approver_admin_hash"
        approval_code = "APR-TEST03"

        def mock_db(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                return [{"id": "user-admin-1", "display_name": "Admin", "role": "project_admin", "is_active": True}]
            if "FROM PUBLIC.PENDING_APPROVALS" in sql_clean:
                return [{
                    "id": "33333333-3333-3333-3333-333333333333",
                    "run_id": "run-3",
                    "thread_id": "thread-3",
                    "requested_by": "user-requester-1",
                    "required_approver_role": "project_admin",
                    "operation": "create_project_field",
                    "proposed_payload": {"project_id": "proj-1", "field_name": "tampered_field"},
                    "status": "pending",
                    # Bad token hash that does not match compute
                    "approval_token_hash": "forged_or_tampered_hash_value",
                    "expires_at": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2)).isoformat(),
                }]
            if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                return [{"can_approve_fields": True}]
            return []

        mock_query.side_effect = mock_db

        result = validate_and_process_approval(
            approval_code=approval_code,
            approver_sender_hash=approver_hash,
            action="APPROVE",
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["decision_reason"], "invalid_approval_context")

    @patch("services.whatsapp.send_whatsapp_message")
    @patch("services.database.execute_query")
    @patch("services.approvals.execute_query")
    @patch("services.audit.execute_query")
    @patch("services.authorization.execute_query")
    @patch("agent.nodes.execute_query")
    @patch("agent.nodes._get_llm_reply")
    def test_low_privilege_field_addition_creates_approval_and_exits(
        self,
        mock_llm,
        mock_node_exec,
        mock_auth_exec,
        mock_audit_exec,
        mock_appr_exec,
        mock_db_exec,
        mock_send_wa,
    ):
        """As a low-privilege user, requesting a field addition creates pending approval and pauses."""
        # Setup env for approver phone
        os.environ["APPROVER_WHATSAPP_NUMBER"] = "15559998888"

        mock_llm.return_value = json.dumps({
            "intent": "propose_field",
            "selected_tool": "create_project_field",
            "project_name": "Pipeline Alpha",
            "tool_arguments": {
                "field_name": "soil_density",
                "field_type": "numeric",
                "record_type": "daily_log",
            }
        })

        def mock_db_router(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                return [{"id": "user-worker-1", "display_name": "Field Worker", "role": "field_worker", "is_active": True}]
            if "FROM PUBLIC.CHAT_SESSIONS" in sql_clean:
                return []
            if "FROM PUBLIC.PROJECTS" in sql_clean:
                return [{"id": "proj-1", "project_name": "Pipeline Alpha", "project_code": "PA-01"}]
            if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                # Allowed to propose fields
                return [{"can_propose_fields": True, "can_read": True}]
            if "INSERT INTO PUBLIC.PENDING_APPROVALS" in sql_clean:
                return [{"id": "44444444-4444-4444-4444-444444444444", "status": "pending"}]
            return []

        mock_node_exec.side_effect = mock_db_router
        mock_auth_exec.side_effect = mock_db_router
        mock_appr_exec.side_effect = mock_db_router
        mock_db_exec.side_effect = mock_db_router
        mock_audit_exec.side_effect = mock_db_router

        initial_state = {
            "run_id": "test-run-field-approval",
            "thread_id": "test-thread-field-approval",
            "incoming_message": "Add field soil_density to Pipeline Alpha",
            "sender_wa_id": "15551112222",
            "sender_hash": "requester_hash_1",
        }

        result = graph.invoke(initial_state, config={"configurable": {"thread_id": "test-thread-field-approval"}})

        # Confirm pending approval was created
        self.assertTrue(result.get("approval_code", "").startswith("APR-"))
        self.assertEqual(result.get("approval_status"), "pending")
        self.assertIn("Approval required", result.get("final_response", ""))

        # Confirm WhatsApp message was sent to approver, NOT the requester
        mock_send_wa.assert_called()
        call_recipient, call_message = mock_send_wa.call_args[0]
        self.assertEqual(call_recipient, "15559998888")
        self.assertIn("soil_density", call_message)
        self.assertIn("Pipeline Alpha", call_message)

    @patch("services.whatsapp.send_whatsapp_message")
    @patch("tools.create_project_field.execute_query")
    @patch("services.database.execute_query")
    @patch("services.approvals.execute_query")
    @patch("services.audit.execute_query")
    @patch("services.authorization.execute_query")
    @patch("agent.nodes.execute_query")
    def test_approver_approve_resumes_thread_and_inserts_field(
        self,
        mock_node_exec,
        mock_auth_exec,
        mock_audit_exec,
        mock_appr_exec,
        mock_db_exec,
        mock_tool_exec,
        mock_send_wa,
    ):
        """As the approver, replying APPROVE APR-XXXX resumes paused thread and inserts field."""
        from langgraph.types import Command

        # Pre-seed state by running an interrupted request or setting up the checkpoint
        thread_id = "test-thread-resume-approve"
        approval_id = "55555555-5555-5555-5555-555555555555"
        approval_code = "APR-555555"

        # Mock DB for create_project_field tool insertion and read-back
        def mock_tool_db(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "INSERT INTO PUBLIC.PROJECT_FIELD_DEFINITIONS" in sql_clean:
                return [{
                    "id": "field-def-1",
                    "project_id": "proj-1",
                    "record_type": "daily_log",
                    "field_name": "soil_density",
                    "field_type": "numeric",
                    "required": False,
                    "default_value": None,
                    "validation_rules": {},
                    "created_at": "2026-09-24T10:00:00Z",
                }]
            if "SELECT ID, PROJECT_ID, RECORD_TYPE" in sql_clean and "FROM PUBLIC.PROJECT_FIELD_DEFINITIONS" in sql_clean:
                # Read-back verification
                return [{
                    "id": "field-def-1",
                    "project_id": "proj-1",
                    "record_type": "daily_log",
                    "field_name": "soil_density",
                    "field_type": "numeric",
                }]
            return []

        mock_tool_exec.side_effect = mock_tool_db

        # First invoke to pause at request_approval
        with patch("agent.nodes._get_llm_reply") as mock_llm:
            mock_llm.return_value = json.dumps({
                "intent": "propose_field",
                "selected_tool": "create_project_field",
                "project_name": "Pipeline Alpha",
                "tool_arguments": {
                    "field_name": "soil_density",
                    "field_type": "numeric",
                    "record_type": "daily_log",
                }
            })
            def mock_init_db(sql, params=None, **kwargs):
                sql_clean = " ".join(sql.split()).upper()
                if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                    return [{"id": "user-worker-1", "display_name": "Field Worker", "role": "field_worker", "is_active": True}]
                if "FROM PUBLIC.PROJECTS" in sql_clean:
                    return [{"id": "proj-1", "project_name": "Pipeline Alpha", "project_code": "PA-01"}]
                if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                    return [{"can_propose_fields": True, "can_read": True}]
                if "INSERT INTO PUBLIC.PENDING_APPROVALS" in sql_clean:
                    return [{"id": approval_id, "status": "pending"}]
                return []
            mock_node_exec.side_effect = mock_init_db
            mock_auth_exec.side_effect = mock_init_db
            mock_appr_exec.side_effect = mock_init_db
            mock_db_exec.side_effect = mock_init_db
            mock_audit_exec.side_effect = mock_init_db

            initial_state = {
                "run_id": "run-initial-1",
                "thread_id": thread_id,
                "incoming_message": "Add field soil_density to Pipeline Alpha",
                "sender_wa_id": "15551112222",
                "sender_hash": "requester_hash_1",
            }
            paused_res = graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
            self.assertEqual(paused_res.get("approval_status"), "pending")

        # Now resume the paused thread with approval
        resume_cmd = Command(resume={
            "decision": "approved",
            "decision_reason": "Approved by project admin",
        })
        resumed_res = graph.invoke(resume_cmd, config={"configurable": {"thread_id": thread_id}})

        # Confirm field creation completed and grounded reply generated
        self.assertTrue(resumed_res.get("goal_complete"))
        self.assertIn("soil_density", resumed_res.get("final_response", ""))
        self.assertIn("Successfully defined new custom field", resumed_res.get("final_response", ""))

    @patch("services.whatsapp.send_whatsapp_message")
    @patch("services.database.execute_query")
    @patch("services.approvals.execute_query")
    @patch("services.audit.execute_query")
    @patch("services.authorization.execute_query")
    @patch("agent.nodes.execute_query")
    def test_approver_reject_resumes_thread_and_aborts(
        self,
        mock_node_exec,
        mock_auth_exec,
        mock_audit_exec,
        mock_appr_exec,
        mock_db_exec,
        mock_send_wa,
    ):
        """As the approver, replying REJECT APR-XXXX notifies requester with reason and creates nothing."""
        from langgraph.types import Command

        thread_id = "test-thread-resume-reject"
        with patch("agent.nodes._get_llm_reply") as mock_llm:
            mock_llm.return_value = json.dumps({
                "intent": "propose_field",
                "selected_tool": "create_project_field",
                "project_name": "Pipeline Alpha",
                "tool_arguments": {
                    "field_name": "soil_density",
                    "field_type": "numeric",
                    "record_type": "daily_log",
                }
            })
            def mock_init_db(sql, params=None, **kwargs):
                sql_clean = " ".join(sql.split()).upper()
                if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                    return [{"id": "user-worker-1", "display_name": "Field Worker", "role": "field_worker", "is_active": True}]
                if "FROM PUBLIC.PROJECTS" in sql_clean:
                    return [{"id": "proj-1", "project_name": "Pipeline Alpha", "project_code": "PA-01"}]
                if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                    return [{"can_propose_fields": True, "can_read": True}]
                if "INSERT INTO PUBLIC.PENDING_APPROVALS" in sql_clean:
                    return [{"id": "66666666-6666-6666-6666-666666666666", "status": "pending"}]
                return []
            mock_node_exec.side_effect = mock_init_db
            mock_auth_exec.side_effect = mock_init_db
            mock_appr_exec.side_effect = mock_init_db
            mock_db_exec.side_effect = mock_init_db
            mock_audit_exec.side_effect = mock_init_db

            initial_state = {
                "run_id": "run-initial-2",
                "thread_id": thread_id,
                "incoming_message": "Add field soil_density to Pipeline Alpha",
                "sender_wa_id": "15551112222",
                "sender_hash": "requester_hash_1",
            }
            graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})

        # Now resume the paused thread with rejection
        resume_cmd = Command(resume={
            "decision": "rejected",
            "decision_reason": "Not needed for this project",
        })
        resumed_res = graph.invoke(resume_cmd, config={"configurable": {"thread_id": thread_id}})

        self.assertFalse(resumed_res.get("goal_complete"))
        self.assertIn("rejected by approver: Not needed for this project", resumed_res.get("final_response", ""))

    @patch("api.index._send_whatsapp_reply")
    @patch("services.approvals.validate_and_process_approval")
    @patch("agent.graph.graph.invoke")
    def test_webhook_approval_reply_flow(self, mock_invoke, mock_validate, mock_send_reply):
        """POST webhook receiving APPROVE APR-XXXX processes approval and notifies parties."""
        from fastapi.testclient import TestClient
        from api.index import app

        client = TestClient(app)

        mock_validate.return_value = {
            "valid": True,
            "status": "approved",
            "decision": "approve",
            "decision_reason": "Approved by project admin",
            "approval_id": "77777777-7777-7777-7777-777777777777",
            "thread_id": "wa-requester-thread",
            "operation": "create_project_field",
            "payload": {"field_name": "soil_density"},
            "requested_by": "user-requester-1",
        }

        mock_invoke.return_value = {
            "final_response": "Successfully defined new custom field 'soil_density' (numeric) for daily_log in project 'Pipeline Alpha'.",
            "goal_complete": True,
            "sender_wa_id": "15551112222",  # Original requester number
        }

        approver_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.approval_reply_1",
                                        "from": "15559998888",
                                        "text": {"body": "APPROVE APR-777777"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        resp = client.post("/api/index", json=approver_payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["approval_code"], "APR-777777")
        self.assertEqual(data["decision"], "approve")

        # Confirm original requester got confirmation
        mock_send_reply.assert_any_call("15551112222", mock_invoke.return_value["final_response"])

        # Confirm approver got acknowledgement
        mock_send_reply.assert_any_call("15559998888", "Approval APR-777777 processed: approve.")


if __name__ == "__main__":
    unittest.main()
