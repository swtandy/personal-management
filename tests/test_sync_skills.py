import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_SKILLS = REPO_ROOT / ".agents" / "skills"
SKILL_NAMES = ["gtd_mgmt", "gtd_workflow"]


class AgentsSkillsStructureTests(unittest.TestCase):
    def test_agents_skills_directory_exists(self):
        self.assertTrue(AGENTS_SKILLS.is_dir(), f"{AGENTS_SKILLS} does not exist")

    def test_gtd_mgmt_skill_md_exists(self):
        p = AGENTS_SKILLS / "gtd_mgmt" / "SKILL.md"
        self.assertTrue(p.exists(), f"{p} does not exist")
        self.assertGreater(p.stat().st_size, 0, "SKILL.md is empty")

    def test_gtd_workflow_skill_md_exists(self):
        p = AGENTS_SKILLS / "gtd_workflow" / "SKILL.md"
        self.assertTrue(p.exists(), f"{p} does not exist")
        self.assertGreater(p.stat().st_size, 0, "SKILL.md is empty")

    def test_skill_md_has_required_frontmatter(self):
        for skill in SKILL_NAMES:
            with self.subTest(skill=skill):
                text = (AGENTS_SKILLS / skill / "SKILL.md").read_text()
                parts = text.split("---", 2)
                self.assertGreaterEqual(len(parts), 3,
                    f"{skill}/SKILL.md has no YAML frontmatter block")
                fm = yaml.safe_load(parts[1])
                self.assertIn("name", fm,
                    f"{skill}/SKILL.md frontmatter missing 'name'")
                self.assertIn("description", fm,
                    f"{skill}/SKILL.md frontmatter missing 'description'")
                self.assertTrue(fm["name"],
                    f"{skill}/SKILL.md 'name' is empty")
                self.assertTrue(fm["description"],
                    f"{skill}/SKILL.md 'description' is empty")

    def test_openai_yaml_uses_interface_key(self):
        for skill in SKILL_NAMES:
            with self.subTest(skill=skill):
                p = AGENTS_SKILLS / skill / "agents" / "openai.yaml"
                self.assertTrue(p.exists(), f"{p} does not exist")
                data = yaml.safe_load(p.read_text())
                self.assertIn("interface", data,
                    f"{skill}/agents/openai.yaml must use nested 'interface:' key, "
                    f"not flat root keys. Got: {list(data.keys())}")

    def test_openai_yaml_declares_mcp_dependency(self):
        for skill in SKILL_NAMES:
            with self.subTest(skill=skill):
                p = AGENTS_SKILLS / skill / "agents" / "openai.yaml"
                data = yaml.safe_load(p.read_text())
                tools = data.get("dependencies", {}).get("tools", [])
                mcp_tools = [t for t in tools if t.get("type") == "mcp"]
                self.assertTrue(mcp_tools,
                    f"{skill}/agents/openai.yaml has no MCP dependency under "
                    f"dependencies.tools")
                values = [t["value"] for t in mcp_tools]
                self.assertIn("gtd_mgmt", values,
                    f"{skill}/agents/openai.yaml MCP dependency must declare "
                    f"value='gtd_mgmt', got: {values}")


class SyncScriptCodexTests(unittest.TestCase):
    def _sync_script_text(self):
        return (REPO_ROOT / "scripts" / "sync_skills.sh").read_text()

    def test_sync_script_does_not_copy_to_codex_skills(self):
        """Regression: sync script must not copy to ~/.codex/skills/ (Codex ignores it)."""
        script = self._sync_script_text()
        # The old pattern assigned codex_skills_dir and used it as a cp destination.
        # Neither the variable assignment nor a cp into that path should be present.
        self.assertNotIn('codex_skills_dir="$codex_home/skills"', script,
            "sync_skills.sh must not use codex_skills_dir copy pattern — "
            "Codex app reads from .agents/skills/ in the repo, no copy needed")

    def test_sync_script_validates_agents_skills(self):
        """Sync script should reference .agents/skills/ for Codex skill validation."""
        script = self._sync_script_text()
        self.assertIn(".agents/skills/", script,
            "sync_skills.sh should validate .agents/skills/ skill files exist")


class CodexConfigTomlTests(unittest.TestCase):
    def test_codex_config_toml_mcp_entry_exists(self):
        config_path = REPO_ROOT / ".codex" / "config.toml"
        self.assertTrue(config_path.exists(), ".codex/config.toml does not exist")
        text = config_path.read_text()
        self.assertIn("[mcp_servers.gtd_mgmt]", text,
            ".codex/config.toml must contain [mcp_servers.gtd_mgmt] section")
        for key in ("command", "args", "cwd"):
            self.assertIn(key, text,
                f".codex/config.toml [mcp_servers.gtd_mgmt] missing '{key}'")


if __name__ == "__main__":
    unittest.main()
