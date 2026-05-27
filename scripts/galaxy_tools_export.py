#!/usr/bin/env python3
"""
galaxy_tools_export.py
======================

Generates `tool_list.yml` (Ephemeris install file) AND enriches the galaxyXpand
`job_conf` file in place with TPV-derived destination overrides.

Workflow:
  1. Fetch Galaxy panel + data managers + installed repos
  2. Fetch TPV shared database (static cores only)
  3. Read the env's `group_vars/all/job_conf` file
  4. For each tool installed in Galaxy:
       - If already in job_conf overrides (human-authored, no `src: tpv(...)`
         tag), keep as-is. Report conflict if TPV would route differently.
       - If already in job_conf overrides AND tagged `# src: tpv(Nc)` (managed
         by a previous run), refresh from current TPV value.
       - If not in job_conf overrides AND TPV proposes a non-default
         destination, add a new entry with `# src: tpv(Nc)` tag.
  5. Rewrite ONLY the `job_tool_routing:` section of `job_conf`. Everything
     else (`job_default_destination`, `job_destinations`, `job_limits_*`,
     comments, blank lines) is preserved verbatim.
  6. Write `tool_list.yml` (Ephemeris format).
  7. Audit: report orphan overrides, invalid destinations, and ghost repos
     (installed in DB but not exposed in the panel).

This script is an ADMIN TOOL, not a deployment dependency. Run it when you want
TPV enrichment or audits. Manual edits to `job_conf` between runs are safe:
the script reads what you wrote and never touches anything outside the routing
block.

Usage:
    python3 scripts/galaxy_tools_export.py <galaxy_url> [options]

Options:
    --env <name>          galaxyXpand environment (auto-derives all paths).
                          Repo root is detected by walking up to find
                          `ansible.cfg` + `environments/`.
    --job-conf <path>     Path to a `job_conf` file (overrides --env derivation).
    --tool-list <path>    Output path for `tool_list.yml` (overrides --env).
    --dest <name>         Force effective default destination. Default:
                          `job_default_destination` from job_conf, or
                          'cluster_1' if no job-conf.
    --admin-key <key>     Galaxy API key (enables data manager fetch and
                          ghost-repo audit).
    --no-revisions        Omit changeset_revision from tool_list (install
                          latest).
    --skip-builtins       Skip built-in Galaxy tools from routing/audit.
    --no-tpv              Skip TPV fetch.
    --tpv-url <url>       Override TPV URL.
    --dry-run             Parse and audit but write nothing.

Example:
    python3 scripts/galaxy_tools_export.py https://usegalaxy.example.org \\
        --env Conect --admin-key MY_KEY --no-revisions --skip-builtins
"""

import difflib
import json
import re
import sys
import urllib.error
import urllib.request
from collections import OrderedDict
from pathlib import Path


TPV_URL_DEFAULT = (
    "https://raw.githubusercontent.com/galaxyproject/"
    "tpv-shared-database/refs/heads/main/tools.yml"
)
SKIP_PREFIXES = ("CONVERTER_", "__")


# ═════════════════════════════════════════════════════════════════════════════
# HTTP
# ═════════════════════════════════════════════════════════════════════════════

def _fetch_json(url, admin_key=None, timeout=30):
    req = urllib.request.Request(url)
    if admin_key:
        req.add_header("x-api-key", admin_key)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _fetch_text(url, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


class GalaxyClient:
    """Thin wrapper around Galaxy HTTP endpoints used by this script."""

    def __init__(self, base_url, admin_key=None):
        self.base = base_url.rstrip("/")
        self.admin_key = admin_key

    def panel(self):
        url = f"{self.base}/api/tools?in_panel=true"
        print(f"[fetch] {url}", file=sys.stderr)
        return _fetch_json(url)

    def flat(self):
        if not self.admin_key:
            return None
        url = f"{self.base}/api/tools?in_panel=false"
        print(f"[fetch] {url}", file=sys.stderr)
        return _fetch_json(url, self.admin_key)

    def installed_repos(self):
        if not self.admin_key:
            return []
        url = f"{self.base}/api/tool_shed_repositories"
        print(f"[fetch] {url}", file=sys.stderr)
        try:
            return _fetch_json(url, self.admin_key)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"[warn]  installed repos fetch failed: {e}", file=sys.stderr)
            return []


# ═════════════════════════════════════════════════════════════════════════════
# Galaxy panel parsing
# ═════════════════════════════════════════════════════════════════════════════

def _short_id(full_id):
    parts = full_id.split("/")
    return parts[-2] if len(parts) >= 2 else full_id


def _is_user_tool(full_id):
    return not any(full_id.startswith(p) for p in SKIP_PREFIXES)


def _is_data_manager(tool):
    tsr = tool.get("tool_shed_repository")
    return tsr is not None and "data_manager" in tsr.get("name", "").lower()


def parse_galaxy_panel(panel, flat=None, skip_builtins=False):
    """
    Returns a dict with:
      tool_ids          : set of all tool IDs exposed (panel + data managers)
      tool_ids_lower    : {lower_id: original_id}
      panel_repos       : list of repo dicts for tool_list.yml (panel)
      dm_repos          : list of repo dicts for tool_list.yml (data managers)
      exposed_repo_keys : set of (owner, name) for any exposed repo
    """
    panel_repos = OrderedDict()
    tools = []
    seen = set()

    for section in panel:
        if not isinstance(section, dict):
            continue
        sname = section.get("name", "")
        sid = section.get("id", "")
        for elem in section.get("elems", []):
            if not isinstance(elem, dict) or elem.get("model_class") != "Tool":
                continue
            full = elem.get("id", "")
            if not _is_user_tool(full):
                continue
            tid = _short_id(full)
            tsr = elem.get("tool_shed_repository")

            if tsr:
                key = (tsr["name"], tsr["owner"], tsr["tool_shed"])
                if key not in panel_repos:
                    panel_repos[key] = {
                        "name": tsr["name"],
                        "owner": tsr["owner"],
                        "tool_shed": tsr["tool_shed"],
                        "revisions": set(),
                        "section_id": sid,
                        "section_name": sname,
                    }
                rev = tsr.get("changeset_revision")
                if rev:
                    panel_repos[key]["revisions"].add(rev)

            if skip_builtins and not tsr:
                continue
            if tid not in seen:
                seen.add(tid)
                tools.append(tid)

    dm_repos = OrderedDict()
    if flat:
        for tool in flat:
            if not isinstance(tool, dict) or not _is_data_manager(tool):
                continue
            tsr = tool.get("tool_shed_repository")
            if not tsr:
                continue
            tid = _short_id(tool.get("id", ""))
            key = (tsr["name"], tsr["owner"], tsr["tool_shed"])
            if key not in dm_repos:
                dm_repos[key] = {
                    "name": tsr["name"],
                    "owner": tsr["owner"],
                    "tool_shed": tsr["tool_shed"],
                    "revisions": set(),
                }
            rev = tsr.get("changeset_revision")
            if rev:
                dm_repos[key]["revisions"].add(rev)
            if tid not in seen:
                seen.add(tid)
                tools.append(tid)

    panel_repos_list = list(panel_repos.values())
    dm_repos_list = list(dm_repos.values())
    exposed_repo_keys = (
        {(r["owner"], r["name"]) for r in panel_repos_list}
        | {(r["owner"], r["name"]) for r in dm_repos_list}
    )

    return {
        "tool_ids": set(tools),
        "tool_ids_lower": {tid.lower(): tid for tid in tools},
        "panel_repos": panel_repos_list,
        "dm_repos": dm_repos_list,
        "exposed_repo_keys": exposed_repo_keys,
    }


# ═════════════════════════════════════════════════════════════════════════════
# TPV parsing
# ═════════════════════════════════════════════════════════════════════════════

def parse_tpv_text(text):
    """{short_id: int_cores} for tools with a static integer cores value."""
    if not text:
        return {}
    tpv = {}
    current = None
    for line in text.splitlines():
        m_tool = re.match(r'^  (toolshed\S+):\s*$', line)
        m_wild = re.match(r'^  \.\*(\w+)\.\*:\s*$', line)
        m_cores = re.match(r'^\s+cores:\s+(\S+)', line)
        if m_tool:
            clean = m_tool.group(1).rstrip(".*").rstrip("/")
            current = clean.split("/")[-1]
        elif m_wild:
            current = m_wild.group(1)
        elif m_cores and current:
            try:
                tpv[current] = int(m_cores.group(1).strip())
            except ValueError:
                pass
        elif line and not line.startswith(" ") and not line.startswith("#"):
            current = None
    return tpv


def fetch_tpv(url):
    print(f"[fetch] {url}", file=sys.stderr)
    try:
        return parse_tpv_text(_fetch_text(url))
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[warn]  TPV fetch failed: {e}", file=sys.stderr)
        return {}


# ═════════════════════════════════════════════════════════════════════════════
# job_conf I/O
# ═════════════════════════════════════════════════════════════════════════════

class JobConf:
    """
    Surgical editor for galaxyXpand `job_conf` files.

    Splits the file into three text segments:
      - prefix:        everything before `job_tool_routing:`
      - routing_text:  the routing block itself (parsed into self.overrides)
      - suffix:        everything after the routing block (anything appearing
                       after job_tool_routing's last entry)

    On write(), prefix and suffix are emitted verbatim. Only the routing block
    is regenerated from the new overrides dict.

    Parsed metadata for read-only consumers:
      default_dest, valid_dests, dest_ntasks, cores_map, overrides
    """

    _ROUTING_RE   = re.compile(r'^job_tool_routing\s*:')
    _TOP_KEY_RE   = re.compile(r'^[a-zA-Z][\w]*\s*:')
    _DEFAULT_RE   = re.compile(r'^job_default_destination:\s+"?([^"#\n]+?)"?\s*(?:#.*)?$')
    _DEST_NAME_RE = re.compile(r'^  (\w+):\s*$')
    _NTASKS_RE    = re.compile(r'^    ntasks:\s+(\d+)')
    _ID_RE        = re.compile(r'^\s*-\s+id:\s+"?([^"#\n]+?)"?\s*(?:#.*)?$')
    _DEST_RE      = re.compile(r'^\s+destination:\s+"?([^"#\n]+?)"?\s*(?:#\s*(.*))?$')
    _TPV_TAG_RE   = re.compile(r'src:\s*tpv\((\d+)c\)')

    def __init__(self, path):
        self.path = Path(path)
        text = self.path.read_text()
        self.prefix, self.routing_text, self.suffix = self._split(text)
        self.default_dest = self._find_default(self.prefix)
        self.valid_dests, self.dest_ntasks = self._parse_destinations(self.prefix)
        self.overrides = self._parse_overrides(self.routing_text)

    @classmethod
    def _split(cls, text):
        lines = text.splitlines(keepends=True)
        start = next((i for i, l in enumerate(lines) if cls._ROUTING_RE.match(l)), None)
        if start is None:
            # No routing block — entire file is prefix
            prefix = text if text.endswith("\n") else text + "\n"
            return prefix, "", ""
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if cls._TOP_KEY_RE.match(lines[i]):
                end = i
                break
        return "".join(lines[:start]), "".join(lines[start:end]), "".join(lines[end:])

    @classmethod
    def _find_default(cls, prefix):
        for line in prefix.splitlines():
            m = cls._DEFAULT_RE.match(line)
            if m:
                return m.group(1).strip()
        return None

    @classmethod
    def _parse_destinations(cls, prefix):
        valid = set()
        ntasks = {}
        in_block = False
        current = None
        for line in prefix.splitlines():
            if re.match(r'^job_destinations:', line):
                in_block = True
                continue
            if not in_block:
                continue
            m_name = cls._DEST_NAME_RE.match(line)
            if m_name:
                current = m_name.group(1)
                valid.add(current)
                continue
            m_n = cls._NTASKS_RE.match(line)
            if m_n and current:
                ntasks[current] = int(m_n.group(1))
                continue
            if line and not line.startswith(" ") and not line.startswith("#"):
                in_block = False
        return valid, ntasks

    @classmethod
    def _parse_overrides(cls, routing_text):
        out = OrderedDict()
        current_id = None
        for line in routing_text.splitlines():
            m_id = cls._ID_RE.match(line)
            if m_id:
                current_id = m_id.group(1).strip()
                continue
            m_dest = cls._DEST_RE.match(line)
            if m_dest and current_id:
                dest = m_dest.group(1).strip()
                comment = m_dest.group(2) or ""
                tpv_m = cls._TPV_TAG_RE.search(comment)
                src_tpv = int(tpv_m.group(1)) if tpv_m else None
                out[current_id] = {"dest": dest, "src_tpv_cores": src_tpv}
                current_id = None
        return out

    @property
    def cores_map(self):
        """Sorted [(ntasks, cluster_N), ...] for routing TPV cores values."""
        return sorted(
            [(n, d) for d, n in self.dest_ntasks.items()
             if re.match(r'^cluster_\d+$', d)],
            key=lambda x: x[0],
        )

    @staticmethod
    def render_routing(overrides):
        """Build the new job_tool_routing block. Entries are alphabetically sorted."""
        lines = ["job_tool_routing:\n"]
        for tid in sorted(overrides.keys()):
            entry = overrides[tid]
            tail = ""
            if entry.get("src_tpv_cores"):
                tail = f'  # src: tpv({entry["src_tpv_cores"]}c)'
            lines.append(f'  - id: "{tid}"\n')
            lines.append(f'    destination: "{entry["dest"]}"{tail}\n')
        return "".join(lines)

    def write(self, new_overrides):
        body = self.prefix
        if body and not body.endswith("\n"):
            body += "\n"
        # Ensure one blank line between prefix content and routing block
        if not body.endswith("\n\n"):
            body += "\n"
        body += self.render_routing(new_overrides)
        if self.suffix:
            if not self.suffix.startswith("\n"):
                body += "\n"
            body += self.suffix
        self.path.write_text(body)


# ═════════════════════════════════════════════════════════════════════════════
# Enrichment
# ═════════════════════════════════════════════════════════════════════════════

def _cores_to_dest(cores, cores_map, default):
    """Largest cluster_N with ntasks <= cores; default if none fits."""
    best = default
    for max_c, dest in cores_map:
        if max_c <= cores:
            best = dest
    return best


def enrich(jobconf, galaxy_state, tpv_cores, default_dest):
    """
    Produce the new overrides dict and report conflicts.

    Rules:
      - Existing override tagged `src: tpv(Nc)`: refresh from current TPV value.
        If new TPV value maps to default, the entry is dropped (no point
        keeping a trivial override).
        If TPV no longer knows the tool, demote to a "human" entry (keep value).
      - Existing override NOT tagged: keep verbatim (human-authored). Report
        a conflict if TPV would route it differently.
      - Tool installed but no override yet: if TPV maps it to a non-default
        destination, add a new `src: tpv(Nc)`-tagged entry.

    Returns (new_overrides, conflicts).
      conflicts is a list of (id, human_dest, tpv_suggested_dest, tpv_cores).
    """
    galaxy_ids = galaxy_state["tool_ids"]
    cores_map = jobconf.cores_map
    new_overrides = OrderedDict()
    conflicts = []

    for tid, entry in jobconf.overrides.items():
        if entry["src_tpv_cores"] is not None:
            # Auto-managed TPV entry — refresh
            if tid in tpv_cores:
                new_cores = tpv_cores[tid]
                new_dest = _cores_to_dest(new_cores, cores_map, default_dest)
                if new_dest != default_dest:
                    new_overrides[tid] = {"dest": new_dest, "src_tpv_cores": new_cores}
                # else: TPV now routes this tool to default → drop the override
            else:
                # TPV no longer knows it — demote to human (preserve last value)
                new_overrides[tid] = {"dest": entry["dest"], "src_tpv_cores": None}
        else:
            # Human override — preserve as-is
            new_overrides[tid] = {"dest": entry["dest"], "src_tpv_cores": None}
            # Detect divergence between human decision and current TPV value
            if tid in tpv_cores and tid in galaxy_ids:
                tpv_dest = _cores_to_dest(tpv_cores[tid], cores_map, default_dest)
                if tpv_dest != entry["dest"]:
                    conflicts.append((tid, entry["dest"], tpv_dest, tpv_cores[tid]))

    # Add brand-new TPV suggestions for tools not yet covered
    for tid, cores in tpv_cores.items():
        if tid in new_overrides or tid not in galaxy_ids:
            continue
        dest = _cores_to_dest(cores, cores_map, default_dest)
        if dest == default_dest:
            continue  # would route to default — no point emitting
        new_overrides[tid] = {"dest": dest, "src_tpv_cores": cores}

    return new_overrides, conflicts


# ═════════════════════════════════════════════════════════════════════════════
# Audit
# ═════════════════════════════════════════════════════════════════════════════

def audit_orphans(overrides, galaxy_state):
    """
    Human overrides whose tool ID is not present in Galaxy panel (case-sensitive).
    Auto-managed TPV entries are skipped (enrich() only emits them for known tools).
    Returns sorted [(id, suggestion_label), ...].
    """
    gids = galaxy_state["tool_ids"]
    gids_lower = galaxy_state["tool_ids_lower"]
    gids_lower_list = list(gids_lower.keys())

    results = []
    for tid, entry in overrides.items():
        if entry["src_tpv_cores"] is not None:
            continue
        if tid in gids:
            continue
        if tid.lower() in gids_lower:
            real = gids_lower[tid.lower()]
            label = f"CASE MISMATCH with installed {real!r}"
        else:
            matches = difflib.get_close_matches(tid.lower(), gids_lower_list, n=2, cutoff=0.5)
            real_matches = [gids_lower[m] for m in matches]
            label = f"closest: {real_matches}" if real_matches else "no close match"
        results.append((tid, label))
    return sorted(results)


def audit_ghosts(installed_repos, galaxy_state):
    """Installed-in-DB repos with no tool exposed in the panel."""
    exposed = galaxy_state["exposed_repo_keys"]
    out = []
    for r in installed_repos:
        if not isinstance(r, dict):
            continue
        if r.get("status") != "Installed":
            continue
        if r.get("uninstalled") or r.get("deleted"):
            continue
        key = (r.get("owner", ""), r.get("name", ""))
        if key not in exposed:
            out.append(f"{key[0]}/{key[1]}")
    return sorted(set(out))


def audit_invalid_dests(overrides, valid_dests):
    if not valid_dests:
        return set()
    emitted = {entry["dest"] for entry in overrides.values()}
    return emitted - valid_dests


# ═════════════════════════════════════════════════════════════════════════════
# tool_list.yml generation
# ═════════════════════════════════════════════════════════════════════════════

def render_tool_list(panel_repos, dm_repos, include_revisions):
    lines = [
        "# Tool list generated by galaxy_tools_export.py",
        "# Install with: shed-tools install -g <url> -a <key> -t tool_list.yml",
        "tools:",
    ]
    section = None
    for r in panel_repos:
        if r["section_id"] != section:
            section = r["section_id"]
            lines.append("")
            lines.append(f"  # panel section: {section}")
        lines.append(f"  - name: {r['name']}")
        lines.append(f"    owner: {r['owner']}")
        lines.append(f"    tool_panel_section_id: {r['section_id']}")
        lines.append(f"    tool_panel_section_label: {r['section_name']}")
        lines.append(f"    tool_shed: {r['tool_shed']}")
        if include_revisions and r["revisions"]:
            lines.append(f"    revisions:")
            for rev in sorted(r["revisions"]):
                lines.append(f"      - {rev}")
    if dm_repos:
        lines.append("")
        lines.append("  # --- Data Managers ---")
        for r in dm_repos:
            lines.append(f"  - name: {r['name']}")
            lines.append(f"    owner: {r['owner']}")
            lines.append(f"    tool_shed: {r['tool_shed']}")
            if include_revisions and r["revisions"]:
                lines.append(f"    revisions:")
                for rev in sorted(r["revisions"]):
                    lines.append(f"      - {rev}")
    return "\n".join(lines) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# Repo root resolution and CLI
# ═════════════════════════════════════════════════════════════════════════════

def find_repo_root():
    """Walk up to find a directory containing both `ansible.cfg` and `environments/`."""
    start = Path(__file__).resolve().parent
    for c in [start, *start.parents]:
        if (c / "ansible.cfg").is_file() and (c / "environments").is_dir():
            return c
    print(f"[error] could not locate galaxyXpand repo root from {start}", file=sys.stderr)
    print(f"[error] need an ancestor containing both 'ansible.cfg' and 'environments/'",
          file=sys.stderr)
    sys.exit(2)


def derive_env_paths(env, args):
    repo = find_repo_root()
    envs_dir = repo / "environments"
    env_dir = envs_dir / env
    if not env_dir.is_dir():
        if envs_dir.is_dir():
            avail = sorted(
                p.name for p in envs_dir.iterdir()
                if p.is_dir() and not p.name.startswith("000_")
            )
            print(f"[error] environment '{env}' not found under {envs_dir}", file=sys.stderr)
            print(f"[error] available: {', '.join(avail)}", file=sys.stderr)
        else:
            print(f"[error] no 'environments/' at {envs_dir}", file=sys.stderr)
        sys.exit(2)

    config_dir = env_dir / "files" / "galaxy" / "config"
    gv_job_conf = env_dir / "group_vars" / "all" / "job_conf"

    if args["tool_list_path"] is None and not config_dir.is_dir():
        print(f"[error] expected output directory does not exist: {config_dir}", file=sys.stderr)
        print(f"[error] create it (and git add) before re-running with --env {env}",
              file=sys.stderr)
        sys.exit(2)

    if args["job_conf"] is None:
        if gv_job_conf.is_file():
            args["job_conf"] = str(gv_job_conf)
        else:
            print(f"[info]  --env {env}: no {gv_job_conf.relative_to(repo)} "
                  f"→ tool_list.yml only, no enrichment", file=sys.stderr)

    if args["tool_list_path"] is None:
        args["tool_list_path"] = str(config_dir / "tool_list.yml")


def parse_args(argv):
    args = {
        "galaxy_url":     None,
        "env":            None,
        "dest":           None,
        "tool_list_path": None,
        "no_revisions":   False,
        "skip_builtins":  False,
        "admin_key":      None,
        "job_conf":       None,
        "no_tpv":         False,
        "tpv_url":        TPV_URL_DEFAULT,
        "dry_run":        False,
    }
    i = 1
    while i < len(argv):
        a = argv[i]
        if   a == "--dest":          args["dest"] = argv[i+1]; i += 2
        elif a == "--env":           args["env"] = argv[i+1]; i += 2
        elif a == "--tool-list":     args["tool_list_path"] = argv[i+1]; i += 2
        elif a == "--no-revisions":  args["no_revisions"] = True; i += 1
        elif a == "--skip-builtins": args["skip_builtins"] = True; i += 1
        elif a == "--admin-key":     args["admin_key"] = argv[i+1]; i += 2
        elif a == "--job-conf":      args["job_conf"] = argv[i+1]; i += 2
        elif a == "--no-tpv":        args["no_tpv"] = True; i += 1
        elif a == "--tpv-url":       args["tpv_url"] = argv[i+1]; i += 2
        elif a == "--dry-run":       args["dry_run"] = True; i += 1
        elif not a.startswith("--"): args["galaxy_url"] = a; i += 1
        else:                        i += 1
    return args


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════

def main():
    args = parse_args(sys.argv)
    if not args["galaxy_url"]:
        print(__doc__)
        sys.exit(1)

    if args["env"]:
        derive_env_paths(args["env"], args)
        print(f"[env]   {args['env']} → tool-list = {args['tool_list_path']}", file=sys.stderr)
        if args["job_conf"]:
            print(f"[env]   {args['env']} → job-conf  = {args['job_conf']}", file=sys.stderr)
    if args["tool_list_path"] is None:
        args["tool_list_path"] = "tool_list.yml"

    # ── Galaxy ───────────────────────────────────────────────────────────────
    client = GalaxyClient(args["galaxy_url"], args["admin_key"])
    panel = client.panel()
    flat = client.flat()
    installed = client.installed_repos()
    state = parse_galaxy_panel(panel, flat, skip_builtins=args["skip_builtins"])
    print(f"[parse] {len(state['panel_repos'])} panel repos | "
          f"{len(state['tool_ids'])} tool IDs | {len(state['dm_repos'])} DM repos",
          file=sys.stderr)

    # ── job_conf ─────────────────────────────────────────────────────────────
    jobconf = None
    default_dest = args["dest"] or "cluster_1"
    default_origin = "--dest" if args["dest"] else "fallback"
    if args["job_conf"]:
        jobconf = JobConf(args["job_conf"])
        print(f"[parse] job_default_destination={jobconf.default_dest!r}", file=sys.stderr)
        print(f"[parse] job_destinations declared={sorted(jobconf.valid_dests)}", file=sys.stderr)
        print(f"[parse] cores_map={jobconf.cores_map}", file=sys.stderr)
        n_human = sum(1 for e in jobconf.overrides.values() if e["src_tpv_cores"] is None)
        n_tpv = sum(1 for e in jobconf.overrides.values() if e["src_tpv_cores"] is not None)
        print(f"[parse] existing overrides: {len(jobconf.overrides)} "
              f"(human={n_human}, tpv-tagged={n_tpv})", file=sys.stderr)
        if not args["dest"] and jobconf.default_dest:
            default_dest = jobconf.default_dest
            default_origin = "job-conf"
    print(f"[default] effective={default_dest!r} (from {default_origin})", file=sys.stderr)

    # ── TPV ──────────────────────────────────────────────────────────────────
    tpv_cores = {}
    if args["no_tpv"]:
        print("[info]  --no-tpv → skipping TPV", file=sys.stderr)
    elif not jobconf:
        print("[info]  no --job-conf → skipping TPV (no enrichment target)", file=sys.stderr)
    elif not jobconf.cores_map:
        print("[info]  empty cores_map → skipping TPV (no routing target)", file=sys.stderr)
    else:
        tpv_cores = fetch_tpv(args["tpv_url"])
        print(f"[parse] TPV tools with static cores: {len(tpv_cores)}", file=sys.stderr)

    # ── Enrich + audit + write job_conf ──────────────────────────────────────
    if jobconf:
        new_ov, conflicts = enrich(jobconf, state, tpv_cores, default_dest)

        n_human = sum(1 for e in new_ov.values() if e["src_tpv_cores"] is None)
        n_tpv = sum(1 for e in new_ov.values() if e["src_tpv_cores"] is not None)
        added = set(new_ov.keys()) - set(jobconf.overrides.keys())
        dropped = set(jobconf.overrides.keys()) - set(new_ov.keys())
        print(f"[enrich] human={n_human}  tpv={n_tpv}  "
              f"added={len(added)}  dropped={len(dropped)}", file=sys.stderr)

        if conflicts:
            print(f"[warn]  {len(conflicts)} conflict(s) between human override and TPV "
                  f"(human kept):", file=sys.stderr)
            for tid, hdest, tdest, c in sorted(conflicts):
                print(f"[warn]    - {tid!r}: human={hdest!r}, "
                      f"TPV suggests {tdest!r} (cores={c})", file=sys.stderr)

        invalid = audit_invalid_dests(new_ov, jobconf.valid_dests)
        if invalid:
            print(f"[warn]  destination(s) NOT declared in job_destinations: "
                  f"{sorted(invalid)}", file=sys.stderr)

        orphans = audit_orphans(new_ov, state)
        if orphans:
            print(f"[warn]  {len(orphans)} override(s) reference tool IDs absent from panel "
                  f"(silently ignored at runtime):", file=sys.stderr)
            for tid, label in orphans:
                print(f"[warn]    - {tid!r}: {label}", file=sys.stderr)

        if args["dry_run"]:
            print(f"[dry-run] would update {jobconf.path}", file=sys.stderr)
        else:
            jobconf.write(new_ov)
            print(f"[write] {jobconf.path}", file=sys.stderr)

    # ── Ghosts (requires admin key) ──────────────────────────────────────────
    if args["admin_key"]:
        ghosts = audit_ghosts(installed, state)
        if ghosts:
            print(f"[warn]  {len(ghosts)} repo(s) installed in DB but not exposed in panel:",
                  file=sys.stderr)
            for g in ghosts:
                print(f"[warn]    - {g}", file=sys.stderr)
            print(f"[warn]  fix in admin UI or via API DELETE on tool_shed_repositories",
                  file=sys.stderr)

    # ── tool_list.yml ────────────────────────────────────────────────────────
    text = render_tool_list(state["panel_repos"], state["dm_repos"],
                            include_revisions=not args["no_revisions"])
    if args["dry_run"]:
        print(f"[dry-run] would write {args['tool_list_path']}", file=sys.stderr)
    else:
        Path(args["tool_list_path"]).write_text(text)
        print(f"[write] {args['tool_list_path']}", file=sys.stderr)


if __name__ == "__main__":
    main()
