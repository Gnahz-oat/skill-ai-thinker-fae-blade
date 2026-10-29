import importlib.util
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

FILE = Path(__file__).resolve().parents[1] / "skills/ai-thinker-fae-blade/scripts/blade.py"
spec = importlib.util.spec_from_file_location("blade", FILE)
blade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blade)
FAKE_TOKEN = "FAKE_TEST_TOKEN_NOT_A_REAL_CREDENTIAL"


def add_skill(source, name, description="A supported embedded task"):
    folder = source / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\nTask instructions.\n", encoding="utf-8")
    (folder / "references").mkdir(exist_ok=True)
    (folder / "references/data.bin").write_bytes(b"\x00\xff\x80\x01")


class FakeWiki:
    def __init__(self, headers):
        self.headers = headers

    def initialize(self):
        return {"protocolVersion": "2025-03-26", "serverInfo": {"name": "test-wiki"}}

    def tools(self):
        return [{"name": "search", "inputSchema": {"type": "object"}}]


class BladeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="fae-blade-test-")
        self.base = Path(self.tmp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        (self.source / "LICENSE").write_text("MIT fixture", encoding="utf-8")
        add_skill(self.source, "module-selector")
        self.root = self.base / "skill"

    def tearDown(self):
        # TemporaryDirectory is a fixed test-owned directory, never a user path.
        self.tmp.cleanup()

    def test_snapshot_discovers_new_skill_and_preserves_binary_resources(self):
        initial = blade.promote(self.root, self.source, {"module-selector"}, {"source": "fixture"})
        add_skill(self.source, "new-radar-guide", "Radar setup and troubleshooting")
        result = blade.promote(self.root, self.source, {"module-selector", "new-radar-guide"}, {"source": "fixture"})
        active, folder, catalog = blade.active_snapshot(self.root)
        self.assertNotEqual(result["snapshot"], initial["snapshot"])
        self.assertEqual({e["name"] for e in catalog["skills"]}, {"module-selector", "new-radar-guide"})
        self.assertEqual((folder / "source/skills/new-radar-guide/references/data.bin").read_bytes(), b"\x00\xff\x80\x01")
        self.assertTrue((self.root / "upstream" / initial["snapshot"]).exists())

    def test_missing_new_official_skill_keeps_old_active_pointer(self):
        blade.promote(self.root, self.source, {"module-selector"}, {})
        old = (self.root / "upstream/active.json").read_bytes()
        with self.assertRaisesRegex(blade.BladeError, "board-pins"):
            blade.promote(self.root, self.source, {"module-selector", "board-pins"}, {})
        self.assertEqual(old, (self.root / "upstream/active.json").read_bytes())

    def test_invalid_yaml_keeps_old_active_pointer(self):
        blade.promote(self.root, self.source, {"module-selector"}, {})
        old = (self.root / "upstream/active.json").read_bytes()
        (self.source / "skills/module-selector/SKILL.md").write_text("---\nname: [broken\ndescription: invalid\n---\n", encoding="utf-8")
        with self.assertRaises(blade.BladeError):
            blade.promote(self.root, self.source, {"module-selector"}, {})
        self.assertEqual(old, (self.root / "upstream/active.json").read_bytes())

    def test_initial_incomplete_import_recovers_when_source_is_complete(self):
        initial = blade.promote(self.root, self.source, {"module-selector", "board-pins"}, {}, True)
        self.assertEqual(initial["missing"], ["board-pins"])
        add_skill(self.source, "board-pins")
        recovered = blade.promote(self.root, self.source, {"module-selector", "board-pins"}, {})
        self.assertTrue(recovered["complete"])
        self.assertEqual(recovered["missing"], [])

    def test_tampered_snapshot_is_rejected(self):
        blade.promote(self.root, self.source, {"module-selector"}, {})
        _, folder, _ = blade.active_snapshot(self.root)
        (folder / "source/LICENSE").write_text("modified", encoding="utf-8")
        with self.assertRaisesRegex(blade.BladeError, "integrity"):
            blade.active_snapshot(self.root)

    def test_catalog_parses_html_split_spans_and_discovers_unknown_names(self):
        raw = '<span>npx skills add Ai-Thinker-AIoT/skills --skill </span><span>new-guide</span>'
        self.assertEqual(blade.official_names(raw), {"new-guide"})
        with self.assertRaises(blade.BladeError):
            blade.official_names("unrelated content")
        raw += '<h3>another-guide</h3><pre>npx skills add Ai-Thinker-AIoT/skills --skill another-guide</pre><h3>next-guide</h3>'
        self.assertEqual(blade.official_names(raw), {"new-guide", "another-guide"})

    def test_config_preserves_existing_settings_for_all_three_clients(self):
        for client in ("codex", "claude", "cursor"):
            with self.subTest(client=client):
                home = self.base / client
                path = blade.config_path(client, home)
                path.parent.mkdir(parents=True)
                raw = 'model = "chosen-model"\n[mcp_servers.other]\nurl = "https://other.example/mcp"\n' if client == "codex" else json.dumps({"somePreference": True, "mcpServers": {"other": {"url": "https://other.example/mcp"}}})
                path.write_text(raw, encoding="utf-8")
                with patch.object(blade, "fetch", return_value="Bearer " + FAKE_TOKEN), patch.object(blade, "WikiClient", FakeWiki):
                    result = blade.setup_mcp(client, home)
                    first = path.read_bytes()
                    second = blade.setup_mcp(client, home)
                self.assertEqual(result["status"], "configured")
                self.assertEqual(second["status"], "reused")
                self.assertEqual(path.read_bytes(), first)
                data, _ = blade.load_config(path, client)
                self.assertEqual(data["model"] if client == "codex" else data["somePreference"], "chosen-model" if client == "codex" else True)
                servers = data["mcp_servers" if client == "codex" else "mcpServers"]
                self.assertEqual(servers["other"]["url"], "https://other.example/mcp")
                self.assertNotIn(FAKE_TOKEN, json.dumps(result))
                self.assertEqual(len(list(path.parent.glob(path.name + ".blade-backup-*"))), 1)

    def test_existing_alias_is_reused_without_fetching_public_token(self):
        home = self.base / "home"
        path = blade.config_path("cursor", home)
        blade.write_json(path, {"mcpServers": {"Ai-Thinker wiki": {"url": blade.MCP_URL, "headers": {"Authorization": "Bearer " + FAKE_TOKEN}}}})
        old = path.read_bytes()
        with patch.object(blade, "WikiClient", FakeWiki), patch.object(blade, "fetch", side_effect=AssertionError("must not fetch")):
            result = blade.setup_mcp("cursor", home)
        self.assertEqual(result["name"], "Ai-Thinker wiki")
        self.assertEqual(path.read_bytes(), old)

    def test_mcp_failure_does_not_create_config(self):
        home = self.base / "home"
        with patch.object(blade, "fetch", return_value="Bearer " + FAKE_TOKEN), patch.object(blade, "WikiClient", side_effect=blade.BladeError("not connected")):
            with self.assertRaises(blade.BladeError):
                blade.setup_mcp("codex", home)
        self.assertFalse(blade.config_path("codex", home).exists())

    def test_malformed_or_disabled_configuration_is_not_overwritten(self):
        home = self.base / "home"
        path = blade.config_path("codex", home)
        path.parent.mkdir(parents=True)
        for raw in ('[broken', f'[mcp_servers.wiki]\nurl = "{blade.MCP_URL}"\nenabled = false\n'):
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(blade.BladeError):
                blade.setup_mcp("codex", home)
            self.assertEqual(path.read_text(encoding="utf-8"), raw)

    def test_credential_parsing_and_env_substitution(self):
        self.assertEqual(blade.token_from_page(f'<span>Bearer </span><span>{FAKE_TOKEN}</span>'), FAKE_TOKEN)
        with self.assertRaises(blade.BladeError):
            blade.token_from_page("Bearer " + FAKE_TOKEN + " Bearer A_DIFFERENT_FAKE_TEST_CREDENTIAL")
        with patch.dict(os.environ, {"BLADE_TEST_TOKEN": FAKE_TOKEN}):
            self.assertEqual(blade.server_headers({"headers": {"Authorization": "Bearer ${env:BLADE_TEST_TOKEN}"}}, "cursor")["Authorization"], "Bearer " + FAKE_TOKEN)

    def test_rpc_response_supports_json_and_sse(self):
        expected = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        raw = json.dumps(expected).encode()
        self.assertEqual(blade.decode_rpc(raw), expected)
        self.assertEqual(blade.decode_rpc(b"event: message\r\ndata: " + raw + b"\r\n\r\n"), expected)


if __name__ == "__main__":
    unittest.main()
