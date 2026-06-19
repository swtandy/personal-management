"""Central configuration for SWT Personal Management."""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or ""
GITHUB_USER = os.getenv("GITHUB_USER", "swtandy")
GITHUB_PROJECT_NUMBER = int(os.getenv("GITHUB_PROJECT_NUMBER", "2"))

# GTD label taxonomy
PRIORITY_LABELS = ["P1-Critical", "P2-High", "P3-Medium", "P4-Low"]
CONTEXT_LABELS  = ["@work", "@home", "@computer", "@phone", "@waiting", "@someday"]
TYPE_LABELS     = ["type:task", "type:project", "type:reference", "type:collaboration"]

# GitHub Projects V2 GraphQL endpoint
GH_GRAPHQL_URL = "https://api.github.com/graphql"
