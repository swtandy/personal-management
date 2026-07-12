import json
import unittest
import urllib.parse
from unittest.mock import patch

from agents import gtd_mgmt_mcp_server as server


class AttachmentMcpWiringTests(unittest.TestCase):
    @patch.object(server, "_request_json", return_value={"ok": True})
    @patch.object(server, "_ensure_gui")
    def test_get_issue_file_forwards_selector_and_output_options(self, mock_ensure, mock_request):
        result = json.loads(server.get_issue_file(
            7, path="issues/7/file.png", output="write", dest_path="/tmp/file.png",
            overwrite=True, repo="owner/repo", launch_if_needed=False,
        ))

        self.assertTrue(result["ok"])
        mock_ensure.assert_called_once_with(False)
        method, request_path = mock_request.call_args.args
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request_path).query)
        self.assertEqual(method, "GET")
        self.assertEqual(query["path"], ["issues/7/file.png"])
        self.assertEqual(query["output"], ["write"])
        self.assertEqual(query["overwrite"], ["true"])

    @patch.object(server, "_request_json", return_value={"ok": True})
    @patch.object(server, "_ensure_gui")
    def test_get_issue_files_forwards_batch_options(self, mock_ensure, mock_request):
        result = json.loads(server.get_issue_files(
            8, "/tmp/files", mime_prefix="image/", fail_fast=True,
            max_total_bytes=1234, repo="owner/repo", launch_if_needed=False,
        ))

        self.assertTrue(result["ok"])
        mock_ensure.assert_called_once_with(False)
        method, request_path = mock_request.call_args.args
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request_path).query)
        self.assertEqual(method, "GET")
        self.assertEqual(query["dest_dir"], ["/tmp/files"])
        self.assertEqual(query["mime_prefix"], ["image/"])
        self.assertEqual(query["fail_fast"], ["true"])
        self.assertEqual(query["max_total_bytes"], ["1234"])


if __name__ == "__main__":
    unittest.main()
