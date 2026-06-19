import os
import unittest
from unittest.mock import patch
import importlib


class ConfigDefaultsTests(unittest.TestCase):
    def _reload_config(self, env_overrides=None):
        """Reload config module with a controlled environment (dotenv skipped)."""
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GITHUB_USER", "GITHUB_PROJECT_NUMBER")}
        if env_overrides:
            env.update(env_overrides)
        with patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv"):
            import config
            importlib.reload(config)
            return config

    def test_default_github_user_is_swtandy(self):
        config = self._reload_config()
        self.assertEqual(config.GITHUB_USER, "swtandy")

    def test_default_github_project_number_is_2(self):
        config = self._reload_config()
        self.assertEqual(config.GITHUB_PROJECT_NUMBER, 2)

    def test_github_token_defaults_to_empty_string_not_error(self):
        config = self._reload_config()
        self.assertEqual(config.GITHUB_TOKEN, "")

    def test_oxmiq_token_fallback_is_absent(self):
        import inspect
        import config
        source = inspect.getsource(config)
        self.assertNotIn("OXMIQ_GITHUB_TOKEN", source)

    def test_env_overrides_are_respected(self):
        config = self._reload_config({
            "GITHUB_USER": "otheruser",
            "GITHUB_PROJECT_NUMBER": "5",
            "GITHUB_TOKEN": "test-token",
        })
        self.assertEqual(config.GITHUB_USER, "otheruser")
        self.assertEqual(config.GITHUB_PROJECT_NUMBER, 5)
        self.assertEqual(config.GITHUB_TOKEN, "test-token")


if __name__ == "__main__":
    unittest.main()
