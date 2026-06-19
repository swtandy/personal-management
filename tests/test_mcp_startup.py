import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MCP_SCRIPT = REPO_ROOT / "agents" / "gtd_mgmt_mcp_server.py"


class McpStartupTests(unittest.TestCase):
    def test_server_imports_from_clean_cwd_without_token(self):
        env = dict(os.environ)
        env.pop("GITHUB_TOKEN", None)
        env["MCP_SCRIPT"] = str(MCP_SCRIPT)

        with tempfile.TemporaryDirectory() as tmpdir:
            code = (
                "import asyncio, os, runpy; "
                "os.chdir(%r); "
                "ns = runpy.run_path(os.environ['MCP_SCRIPT'], run_name='__smoke__'); "
                "tools = asyncio.run(ns['mcp'].list_tools()); "
                "print(ns['mcp'].name); "
                "print(','.join(tool.name for tool in tools))"
            ) % tmpdir
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=tmpdir,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], "gtd_mgmt")
        self.assertIn("resume_from_issue", lines[1])
        self.assertIn("create_resume_handoff", lines[1])
        self.assertIn("create_issue", lines[1])
        self.assertIn("bulk_organize_issues", lines[1])

    def test_server_lists_tools_over_stdio_from_clean_cwd_without_token(self):
        env = dict(os.environ)
        env.pop("GITHUB_TOKEN", None)
        env["MCP_SCRIPT"] = str(MCP_SCRIPT)

        with tempfile.TemporaryDirectory() as tmpdir:
            code = (
                "import asyncio, os\n"
                "from mcp.client.session import ClientSession\n"
                "from mcp.client.stdio import StdioServerParameters, stdio_client\n"
                "async def main():\n"
                "    env = dict(os.environ)\n"
                "    env.pop('GITHUB_TOKEN', None)\n"
                "    params = StdioServerParameters(command=%r, args=[os.environ['MCP_SCRIPT']], cwd=%r, env=env)\n"
                "    async with stdio_client(params) as streams:\n"
                "        read, write = streams\n"
                "        async with ClientSession(read, write) as session:\n"
                "            await session.initialize()\n"
                "            result = await session.list_tools()\n"
                "            print(','.join(tool.name for tool in result.tools))\n"
                "asyncio.run(main())"
            ) % (sys.executable, tmpdir)
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=tmpdir,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("resume_from_issue", result.stdout)
        self.assertIn("create_resume_handoff", result.stdout)
        self.assertIn("create_issue", result.stdout)
        self.assertIn("bulk_organize_issues", result.stdout)


if __name__ == "__main__":
    unittest.main()
