"""Root conftest: put tools/ on sys.path so tests can import github_client, issue_tree, mcp_server."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tools"))
