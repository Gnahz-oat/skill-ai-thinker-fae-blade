#!/usr/bin/env python3
"""Ai-Thinker FAE bundle maintenance and lazy MCP setup (Python 3.11+)."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request

try:
    import yaml
except ImportError:
    raise SystemExit("Missing PyYAML. Run: python -m pip install -r scripts/requirements.txt")

ROOT = Path(__file__).resolve().parents[1]
DOCS = "https://docs.ai-thinker.com/skills/install.html"
MCP_DOCS = "https://docs.ai-thinker.com/mcp/"
MCP_URL = "https://mcp.wiki.ai-thinker.com/mcp"
SOURCES = ["https://github.com/Ai-Thinker-AIoT/skills.git",
           "https://gitee.com/Ai-Thinker-Open/skills.git"]
NAME = "ai-thinker-wiki"


class BladeError(Exception):
    pass


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in {"p", "div", "pre", "h1", "h2", "h3", "h4", "li", "tr", "td", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"p", "div", "pre", "h1", "h2", "h3", "h4", "li", "tr", "td"}:
            self.parts.append("\n")


def page_text(raw):
    parser = TextParser()
    parser.feed(raw)
    return html.unescape("".join(parser.parts))


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ai-thinker-fae-blade/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise BladeError("Official page exceeds size limit")
    return raw.decode("utf-8")


def official_names(raw):
    names = set(re.findall(r"npx\s+skills\s+add\s+Ai-Thinker-AIoT/skills\s+--skill\s+([a-z0-9-]+)", page_text(raw)))
    if not names:
        raise BladeError("Cannot identify official Skill catalog; existing snapshot retained")
    return names


def atomic_write(path, text, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".blade-", dir=path.parent)
    try:
        if private and os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def write_json(path, data, private=False):
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", private)


def frontmatter(path):
    raw = path.read_text(encoding="utf-8-sig")
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\s*\r?\n|$)", raw, re.S)
    if not match:
        raise BladeError(f"Missing frontmatter: {path.name}")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise BladeError(f"Invalid YAML: {path.name}") from None
    if not isinstance(data, dict):
        raise BladeError("Frontmatter must be a mapping")
    name, description = data.get("name"), data.get("description")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
        raise BladeError("Invalid skill name")
    if not isinstance(description, str) or not description.strip():
        raise BladeError(f"Missing description: {name}")
    if path.parent.name != name:
        raise BladeError(f"Skill folder/name mismatch: {name}")
    return {"name": name, "description": description.strip()}


def inventory(source):
    source = Path(source)
    skills = source / "skills"
    if not skills.is_dir() or not (source / "LICENSE").is_file():
        raise BladeError("Upstream must include skills/ and LICENSE")
    entries, files = [], {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BladeError("Upstream symlinks are not accepted")
        if path.is_file() and ".git" not in path.relative_to(source).parts:
            if path.stat().st_size > 32 * 1024 * 1024:
                raise BladeError("Upstream file exceeds size limit")
            relative = path.relative_to(source).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    for child in sorted(skills.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "SKILL.md").is_file():
            raise BladeError(f"Skill directory missing SKILL.md: {child.name}")
        entry = frontmatter(child / "SKILL.md")
        entry["path"] = f"source/skills/{child.name}/SKILL.md"
        entries.append(entry)
    if not entries:
        raise BladeError("Empty upstream Skill bundle")
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return entries, files, fingerprint


def require_complete(entries, expected, previous=()):
    actual = {entry["name"] for entry in entries}
    missing = (set(expected) | set(previous)) - actual
    if missing:
        raise BladeError("Incomplete upstream; missing: " + ", ".join(sorted(missing)))


def active_snapshot(root):
    active = json.loads((root / "upstream/active.json").read_text(encoding="utf-8"))
    folder = (root / "upstream" / active["snapshot"]).resolve()
    if not folder.is_relative_to((root / "upstream/snapshots").resolve()):
        raise BladeError("Invalid snapshot path")
    catalog = json.loads((folder / "catalog.json").read_text(encoding="utf-8"))
    entries, files, fingerprint = inventory(folder / "source")
    if files != catalog["files"] or fingerprint != catalog["fingerprint"] or entries != catalog["skills"]:
        raise BladeError("Snapshot integrity verification failed")
    return active, folder, catalog


def promote(root, source, expected, provenance, allow_incomplete=False):
    entries, files, fingerprint = inventory(source)
    previous = []
    if (root / "upstream/active.json").exists():
        _, _, old = active_snapshot(root)
        previous = [entry["name"] for entry in old["skills"]]
    missing = sorted((set(expected) | set(previous)) - {e["name"] for e in entries})
    if not allow_incomplete:
        require_complete(entries, expected, previous)
    elif previous:
        raise BladeError("Incomplete import cannot replace an existing snapshot")
    snapshot = root / "upstream/snapshots" / fingerprint
    if not snapshot.exists():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".stage-", dir=snapshot.parent) as temporary:
            staging = Path(temporary) / "snapshot"
            shutil.copytree(source, staging / "source", ignore=shutil.ignore_patterns(".git"))
            copied_entries, copied_files, copied_fingerprint = inventory(staging / "source")
            if (copied_entries, copied_files, copied_fingerprint) != (entries, files, fingerprint):
                raise BladeError("Copy verification failed")
            write_json(staging / "catalog.json", {"skills": entries, "files": files,
                "fingerprint": fingerprint, "provenance": provenance,
                "official_catalog": sorted(expected), "missing": missing, "complete": not missing})
            staging.rename(snapshot)
    active = {"snapshot": f"snapshots/{fingerprint}", "complete": not missing,
              "missing": missing, "skill_count": len(entries)}
    # Verify an existing generation before changing the active pointer.
    existing = json.loads((snapshot / "catalog.json").read_text(encoding="utf-8"))
    check_entries, check_files, check_fingerprint = inventory(snapshot / "source")
    if check_files != existing["files"] or check_entries != existing["skills"] or check_fingerprint != existing["fingerprint"]:
        raise BladeError("Existing generation integrity verification failed")
    write_json(root / "upstream/active.json", active)
    return active


def run_git(*args):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=90, env=environment)
    if result.returncode:
        raise BladeError("Official Git source unavailable")
    return result.stdout.strip()


def sync(root, if_due=False, source_dir=None, catalog_file=None, allow_incomplete=False):
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    state_path = runtime / "sync.json"
    if if_due and state_path.exists() and (root / "upstream/active.json").exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if time.time() - state.get("last_check", 0) < 24 * 3600:
            active, _, _ = active_snapshot(root)
            return {"status": "cached_after_failed_check" if state.get("failed") else "cached", **active}
    lock = root / "upstream/.sync-lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError:
        raise BladeError("Another sync is running; existing snapshot retained") from None
    try:
        expected = official_names(Path(catalog_file).read_text(encoding="utf-8") if catalog_file else fetch(DOCS))
        if source_dir:
            source = Path(source_dir).resolve()
            remote = run_git("-c", f"safe.directory={source.as_posix()}", "-C", str(source), "config", "--get", "remote.origin.url")
            provenance = {"source": remote if remote in SOURCES else "local-import", "commit": run_git("-c", f"safe.directory={source.as_posix()}", "-C", str(source), "rev-parse", "HEAD")}
            result = promote(root, source, expected, provenance, allow_incomplete)
        else:
            failures = []
            result = None
            for url in SOURCES:
                try:
                    with tempfile.TemporaryDirectory(prefix="sync-", dir=runtime) as temporary:
                        source = Path(temporary) / "source"
                        run_git("-c", "core.autocrlf=false", "clone", "--depth", "1", url, str(source))
                        commit = run_git("-C", str(source), "rev-parse", "HEAD")
                        result = promote(root, source, expected, {"source": url, "commit": commit})
                    break
                except (BladeError, subprocess.TimeoutExpired, OSError) as error:
                    failures.append(str(error) if isinstance(error, BladeError) else "Source download failed")
            if result is None:
                raise BladeError("All official sources failed; existing snapshot retained. " + "; ".join(failures))
        write_json(state_path, {"last_check": time.time()})
        return {"status": "updated", **result}
    except Exception:
        # Throttle failed checks too; do not repeatedly hit the network in one day.
        write_json(state_path, {"last_check": time.time(), "failed": True})
        raise
    finally:
        lock.rmdir()


def decode_rpc(raw):
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for event in re.split(r"\r?\n\r?\n", text):
            data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
            if data:
                candidate = json.loads(data)
                if "result" in candidate or "error" in candidate:
                    return candidate
    raise BladeError("MCP returned an unsupported response")


class WikiClient:
    def __init__(self, headers):
        self.headers = dict(headers)
        self.headers.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
        self.counter = 0
        self.session = None

    def request(self, method, params=None, notification=False):
        self.counter += 1
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            payload["id"] = self.counter
        headers = dict(self.headers)
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        request = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.headers.get("Mcp-Session-Id"):
                    self.session = response.headers["Mcp-Session-Id"]
                if notification:
                    return None
                raw = response.read(8 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as error:
            raise BladeError(f"Official MCP HTTP {error.code}; configuration preserved") from None
        if len(raw) > 8 * 1024 * 1024:
            raise BladeError("MCP response exceeds size limit")
        data = decode_rpc(raw)
        if data.get("id") != self.counter or "error" in data or "result" not in data:
            raise BladeError("MCP request failed; configuration preserved")
        return data["result"]

    def initialize(self):
        result = self.request("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "ai-thinker-fae-blade", "version": "0.1.0"}})
        self.headers["MCP-Protocol-Version"] = result["protocolVersion"]
        self.request("notifications/initialized", notification=True)
        return result

    def tools(self):
        tools, cursor = [], None
        seen = set()
        for _ in range(100):
            result = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools
            if cursor in seen:
                raise BladeError("MCP repeated a tools pagination cursor")
            seen.add(cursor)
        raise BladeError("MCP tool pagination limit exceeded")


def config_path(client, home):
    if client == "codex":
        if home == Path.home().resolve() and os.environ.get("CODEX_HOME"):
            return Path(os.environ["CODEX_HOME"]).expanduser().resolve() / "config.toml"
        return home / ".codex/config.toml"
    if client == "claude":
        return home / ".claude.json"
    return home / ".cursor/mcp.json"


def load_config(path, client):
    if not path.exists():
        return {}, ""
    raw = path.read_text(encoding="utf-8-sig")
    try:
        data = tomllib.loads(raw) if client == "codex" else json.loads(raw)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError):
        raise BladeError("Existing MCP configuration is invalid; no changes made") from None
    if not isinstance(data, dict):
        raise BladeError("Existing MCP configuration must be an object")
    return data, raw


def find_server(data, client):
    servers = data.get("mcp_servers" if client == "codex" else "mcpServers", {})
    if not isinstance(servers, dict):
        raise BladeError("Existing MCP server list is invalid")
    for name, server in servers.items():
        if isinstance(server, dict) and str(server.get("url", "")).rstrip("/") == MCP_URL:
            if server.get("enabled") is False or server.get("disabled") is True:
                raise BladeError("Existing official MCP is disabled; ask user before enabling")
            return name, server
    if NAME in servers:
        raise BladeError("MCP name already used by another endpoint; configuration preserved")
    return None, None


def server_headers(server, client):
    headers = dict(server.get("http_headers" if client == "codex" else "headers", {}))
    for header, variable in server.get("env_http_headers", {}).items():
        if variable not in os.environ:
            raise BladeError("Existing MCP requires an unavailable environment variable")
        headers[header] = os.environ[variable]
    variable = server.get("bearer_token_env_var")
    if variable:
        if variable not in os.environ:
            raise BladeError("Existing MCP requires an unavailable bearer environment variable")
        headers["Authorization"] = "Bearer " + os.environ[variable]
    for header, value in list(headers.items()):
        def expand(match):
            if match[1] not in os.environ:
                raise BladeError("Existing MCP requires an unavailable environment variable")
            return os.environ[match[1]]
        headers[header] = re.sub(r"\$\{(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}", expand, value)
    return headers


def token_from_page(raw):
    tokens = set(re.findall(r"Bearer\s+([A-Za-z0-9._~-]{16,})", page_text(raw)))
    if len(tokens) != 1:
        raise BladeError("Cannot uniquely identify official MCP credential; ask user for their Token")
    return next(iter(tokens))


def wiki_for_existing(client, home):
    data, _ = load_config(config_path(client, home), client)
    _, server = find_server(data, client)
    if server is None:
        raise BladeError("No official MCP configuration; run mcp setup first")
    wiki = WikiClient(server_headers(server, client))
    wiki.initialize()
    return wiki


def setup_mcp(client, home):
    path = config_path(client, home)
    data, raw = load_config(path, client)
    alias, server = find_server(data, client)
    if server:
        wiki = WikiClient(server_headers(server, client))
        wiki.initialize()
        tools = wiki.tools()
        return {"status": "reused", "name": alias, "tool_count": len(tools), "config": str(path)}
    token = token_from_page(fetch(MCP_DOCS))
    wiki = WikiClient({"Authorization": "Bearer " + token})
    wiki.initialize()
    tools = wiki.tools()
    # Network validation precedes any configuration mutation.
    _, latest_raw = load_config(path, client)
    if latest_raw != raw:
        raise BladeError("MCP configuration changed during validation; retry without overwriting")
    if path.exists():
        atomic_write(path.with_name(path.name + ".blade-backup-" + str(time.time_ns())), raw, private=True)
    if client == "codex":
        new = raw.rstrip() + "\n\n[mcp_servers.ai-thinker-wiki]\nurl = " + json.dumps(MCP_URL) + "\nhttp_headers = { Authorization = " + json.dumps("Bearer " + token) + " }\n"
        tomllib.loads(new)
        atomic_write(path, new, private=True)
    else:
        data.setdefault("mcpServers", {})[NAME] = {"url": MCP_URL, "headers": {"Authorization": "Bearer " + token}}
        if client == "claude":
            data["mcpServers"][NAME]["type"] = "http"
        write_json(path, data, private=True)
    return {"status": "configured", "name": NAME, "tool_count": len(tools), "config": str(path),
        "reload_required": True, "note": "Configuration verified. Reload host to expose tools, or use wiki-tools/wiki-call now."}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Skill root (for isolated validation)")
    sub = parser.add_subparsers(dest="command", required=True)
    update = sub.add_parser("sync")
    update.add_argument("--if-due", action="store_true")
    update.add_argument("--source-dir", type=Path)
    update.add_argument("--catalog-file", type=Path)
    update.add_argument("--allow-incomplete", action="store_true", help="Initial development import only; never replaces an installed snapshot")
    sub.add_parser("validate")
    sub.add_parser("probe", help="Read-only live official MCP connection check; writes no configuration")
    for command in ("mcp", "wiki-tools", "wiki-call"):
        item = sub.add_parser(command)
        item.add_argument("--client", choices=("codex", "claude", "cursor"), required=True)
        item.add_argument("--home", type=Path, default=Path.home(), help="Explicit configuration home; useful for isolated validation")
        if command == "wiki-call":
            item.add_argument("--tool", required=True)
            item.add_argument("--arguments-json", required=True)
    args = parser.parse_args()
    try:
        if args.command == "sync":
            result = sync(args.root.resolve(), args.if_due, args.source_dir, args.catalog_file, args.allow_incomplete)
        elif args.command == "validate":
            frontmatter(args.root / "SKILL.md")
            active, _, catalog = active_snapshot(args.root.resolve())
            coverage = json.loads((args.root / "references/coverage.json").read_text(encoding="utf-8"))
            require_complete(catalog["skills"], set(catalog["official_catalog"]) - set(coverage["acknowledged_missing"]))
            missing = sorted(set(catalog["official_catalog"]) - {e["name"] for e in catalog["skills"]})
            if missing != catalog["missing"] or missing != active["missing"]:
                raise BladeError("Coverage metadata mismatch")
            result = {"status": "valid_with_missing" if missing else "valid", **active}
        elif args.command == "probe":
            wiki = WikiClient({"Authorization": "Bearer " + token_from_page(fetch(MCP_DOCS))})
            info = wiki.initialize()
            result = {"status": "connected", "server": info.get("serverInfo"),
                      "tools": [tool["name"] for tool in wiki.tools()]}
        elif args.command == "mcp":
            result = setup_mcp(args.client, args.home.resolve())
        else:
            wiki = wiki_for_existing(args.client, args.home.resolve())
            if args.command == "wiki-tools":
                result = {"tools": wiki.tools()}
            else:
                names = {tool["name"] for tool in wiki.tools()}
                if args.tool not in names:
                    raise BladeError("Tool is not advertised by the official MCP")
                arguments = json.loads(args.arguments_json)
                if not isinstance(arguments, dict):
                    raise BladeError("Tool arguments must be a JSON object")
                result = wiki.request("tools/call", {"name": args.tool, "arguments": arguments})
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (BladeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        # Do not print raw network exceptions, bodies, or configuration values.
        message = str(error) if isinstance(error, BladeError) else type(error).__name__ + ": operation failed; previous files retained"
        print(json.dumps({"status": "failed", "message": message}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
