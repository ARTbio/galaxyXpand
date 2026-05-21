#!/usr/bin/env python3
"""
galaxy_tools_export.py
======================
Generate tool_list.yml (Ephemeris) and job_tool_routing.yml from a single
Galaxy instance, optionally enriching the routing with destinations from:

  1. An existing galaxyXpand group_vars/all/tools file  (priority 1)
  2. The live TPV shared database tools.yml             (priority 2, cores only)

Pipeline:
  Galaxy /api/tools?in_panel=true   →  tool_list.yml + routing skeleton
  Galaxy /api/tools?in_panel=false  →  data managers (if --admin-key)
  group_vars/all/tools              →  per-tool destination overrides + cores_map
  TPV tools.yml (HTTPS GET)         →  static cores → destination (via cores_map)

Usage:
    python3 galaxy_tools_export.py <galaxy_url> [options]

Options:
    --env <name>             galaxyXpand environment (Conect, ARTbio, Mississippi, ...).
                             Derives default paths from the repo layout:
                               --existing-tools environments/<name>/group_vars/all/tools
                               --tool-list      environments/<name>/files/galaxy/config/<name>_tool_list.yml
                               --routing        environments/<name>/files/galaxy/config/<name>_job_tool_routing.yml
                             Explicit --tool-list / --routing / --existing-tools override.
                             The repo root is located by walking up from this script
                             looking for `ansible.cfg` + `environments/` — the script
                             can live anywhere inside the repo.
    --dest <name>            Default Slurm destination (default: cluster_1)
    --tool-list <path>       Output path for tool_list.yml
    --routing <path>         Output path for job_tool_routing.yml
    --no-revisions           Omit changeset_revision from tool_list (install latest)
    --skip-builtins          Exclude built-in Galaxy tools from routing output
    --admin-key <key>        Galaxy API key; enables data manager fetch
    --existing-tools <path>  Existing group_vars/all/tools for per-tool overrides + cores_map
    --no-tpv                 Skip TPV fetch (offline / debug)
    --tpv-url <url>          Override TPV URL (default: galaxyproject/tpv-shared-database main)

Examples:
    # Standard usage with --env (paths auto-derived from repo layout)
    python3 scripts/galaxy_tools_export.py https://usegalaxy.sorbonne-universite.fr \\
        --env Conect --admin-key MY_KEY --skip-builtins

    # Manual paths (legacy / one-off)
    python3 scripts/galaxy_tools_export.py https://usegalaxy.sorbonne-universite.fr \\
        --existing-tools environments/Conect/group_vars/all/tools \\
        --tool-list /tmp/conect_tool_list.yml \\
        --routing /tmp/conect_job_tool_routing.yml
"""

import json
import re
import sys
import urllib.request
import urllib.error
from collections import Counter, OrderedDict
from pathlib import Path


TPV_URL_DEFAULT = (
    "https://raw.githubusercontent.com/galaxyproject/"
    "tpv-shared-database/refs/heads/main/tools.yml"
)

SKIP_PREFIXES = ("CONVERTER_", "__")


# =============================================================================
# HTTP fetchers
# =============================================================================

def fetch_panel(galaxy_url: str, api_key: str = None) -> list:
    url = galaxy_url.rstrip("/") + "/api/tools?in_panel=true"
    print(f"[fetch] {url}", file=sys.stderr)
    req = urllib.request.Request(url)
    if api_key:
        req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_flat(galaxy_url: str, api_key: str) -> list:
    """Fetch all tools flat (in_panel=false); requires API key for data managers."""
    url = galaxy_url.rstrip("/") + "/api/tools?in_panel=false"
    print(f"[fetch] {url}", file=sys.stderr)
    req = urllib.request.Request(url)
    req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_tpv(url: str) -> str:
    """Fetch the TPV shared database tools.yml. Returns text or empty on failure."""
    print(f"[fetch] {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[warn]  TPV fetch failed: {e} — continuing without TPV enrichment",
              file=sys.stderr)
        return ""


# =============================================================================
# Galaxy panel parsing  (unchanged from galaxy_tools_export.py)
# =============================================================================

def short_id(full_id: str) -> str:
    """toolshed.../tool_id/version → tool_id   |   builtin → builtin"""
    parts = full_id.split("/")
    return parts[-2] if len(parts) >= 2 else full_id


def is_user_tool(full_id: str) -> bool:
    return not any(full_id.startswith(p) for p in SKIP_PREFIXES)


def is_data_manager(tool: dict) -> bool:
    tsr = tool.get("tool_shed_repository")
    return tsr is not None and "data_manager" in tsr.get("name", "").lower()


def parse_panel(panel: list, skip_builtins: bool = False):
    toolshed_tools = OrderedDict()
    routing_tools  = []
    seen_sids      = set()

    for section in panel:
        if not isinstance(section, dict):
            continue
        section_name = section.get("name", "")
        section_id   = section.get("id", "")

        for elem in section.get("elems", []):
            if not isinstance(elem, dict):
                continue
            if elem.get("model_class") != "Tool":
                continue

            full = elem.get("id", "")
            if not is_user_tool(full):
                continue

            sid = short_id(full)
            tsr = elem.get("tool_shed_repository")

            if tsr:
                key = (tsr["name"], tsr["owner"], tsr["tool_shed"])
                if key not in toolshed_tools:
                    toolshed_tools[key] = {
                        "name":         tsr["name"],
                        "owner":        tsr["owner"],
                        "tool_shed":    tsr["tool_shed"],
                        "revisions":    set(),
                        "section_id":   section_id,
                        "section_name": section_name,
                    }
                rev = tsr.get("changeset_revision")
                if rev:
                    toolshed_tools[key]["revisions"].add(rev)

            if skip_builtins and not tsr:
                continue
            if sid not in seen_sids:
                seen_sids.add(sid)
                routing_tools.append({
                    "id":          sid,
                    "repo_name":   tsr["name"] if tsr else "",
                    "section":     section_name,
                    "destination": "",
                    "source":      "",
                })

    return list(toolshed_tools.values()), routing_tools


def parse_data_managers(flat: list):
    dm_tools   = OrderedDict()
    dm_routing = []
    seen_sids  = set()

    for tool in flat:
        if not isinstance(tool, dict):
            continue
        if not is_data_manager(tool):
            continue

        tsr = tool.get("tool_shed_repository")
        if not tsr:
            continue
        full = tool.get("id", "")
        sid  = short_id(full)

        key = (tsr["name"], tsr["owner"], tsr["tool_shed"])
        if key not in dm_tools:
            dm_tools[key] = {
                "name":         tsr["name"],
                "owner":        tsr["owner"],
                "tool_shed":    tsr["tool_shed"],
                "revisions":    set(),
                "section_id":   "",
                "section_name": "",
            }
        rev = tsr.get("changeset_revision")
        if rev:
            dm_tools[key]["revisions"].add(rev)

        if sid not in seen_sids:
            seen_sids.add(sid)
            dm_routing.append({
                "id":          sid,
                "repo_name":   tsr["name"],
                "section":     "Data Managers",
                "destination": "",
                "source":      "",
            })

    return list(dm_tools.values()), dm_routing


# =============================================================================
# Existing group_vars/all/tools parsing  (from enrich_routing.py)
# =============================================================================

def parse_existing_tools(path: str, default_dest: str) -> dict:
    """Return {short_id: destination} for tools with explicit non-default destination."""
    routing = {}
    current_id = None
    with open(path) as f:
        for line in f:
            m_id   = re.match(r'\s*-\s+id:\s+"?([^"#\n]+)"?', line)
            m_dest = re.match(r'\s+destination:\s+"?([^"#\n]+)"?', line)
            if m_id:
                current_id = m_id.group(1).strip()
            elif m_dest and current_id:
                dest = m_dest.group(1).strip()
                if dest != default_dest:
                    routing[current_id] = dest
                current_id = None
    return routing


def build_cores_map(tools_path: str) -> list:
    """
    Parse job_destinations from tools file: returns sorted [(ntasks, dest_name), ...]
    for cluster_N destinations only (excludes special targets like java_cluster).
    """
    destinations = {}
    current_dest = None
    in_destinations = False
    with open(tools_path) as f:
        for line in f:
            if re.match(r'^job_destinations:', line):
                in_destinations = True
                continue
            if in_destinations:
                m_dest = re.match(r'^  (\w+):', line)
                if m_dest:
                    current_dest = m_dest.group(1)
                    continue
                m_ntasks = re.match(r'^    ntasks:\s+(\d+)', line)
                if m_ntasks and current_dest:
                    destinations[current_dest] = int(m_ntasks.group(1))
                if line and not line.startswith(" ") and not line.startswith("#"):
                    in_destinations = False

    return sorted(
        [(n, d) for d, n in destinations.items() if re.match(r'^cluster_\d+$', d)],
        key=lambda x: x[0],
    )


# =============================================================================
# TPV parsing  (adapted from enrich_routing.py to work on text, not file)
# =============================================================================

def short_id_from_tpv_full(full_id: str) -> str:
    """toolshed.g2.bx.psu.edu/repos/owner/repo/tool_id/.* → tool_id"""
    clean = full_id.rstrip(".*").rstrip("/")
    parts = clean.split("/")
    return parts[-1] if parts else full_id


def parse_tpv_text(text: str) -> dict:
    """Return {short_id: cores} for tools with a static integer cores value."""
    if not text:
        return {}

    tpv = {}
    current_id = None
    for line in text.splitlines(keepends=False):
        # Re-add trailing newline marker not needed; we match on content
        m_tool     = re.match(r'^  (toolshed\S+):\s*$', line)
        m_wildcard = re.match(r'^  \.\*(\w+)\.\*:\s*$', line)
        m_cores    = re.match(r'^\s+cores:\s+(\S+)', line)

        if m_tool:
            current_id = short_id_from_tpv_full(m_tool.group(1))
        elif m_wildcard:
            current_id = m_wildcard.group(1)
        elif m_cores and current_id:
            raw = m_cores.group(1).strip()
            try:
                tpv[current_id] = int(raw)
            except ValueError:
                pass  # dynamic Python expression — skip
        elif line and not line.startswith(" ") and not line.startswith("#"):
            current_id = None

    return tpv


def cores_to_dest(cores: int, cores_map: list, default_dest: str) -> str:
    """Largest cluster_N with ntasks <= cores, fallback to default."""
    best = default_dest
    for max_c, dest in cores_map:
        if max_c <= cores:
            best = dest
    return best


# =============================================================================
# Enrichment
# =============================================================================

def enrich_routing(tools: list, existing: dict, tpv_cores: dict,
                   cores_map: list, default_dest: str) -> list:
    """Annotate each tool with destination + source. Mutates in place, returns tools."""
    for t in tools:
        sid = t["id"]
        if sid in existing:
            t["destination"] = existing[sid]
            t["source"]      = "existing"
        elif sid in tpv_cores and cores_map:
            dest = cores_to_dest(tpv_cores[sid], cores_map, default_dest)
            t["destination"] = dest
            t["source"]      = f"tpv({tpv_cores[sid]}c)" if dest != default_dest else "default"
        else:
            t["destination"] = default_dest
            t["source"]      = "default"
    return tools


# =============================================================================
# Rendering
# =============================================================================

def render_tool_list(repos: list, dm_repos: list, include_revisions: bool) -> str:
    lines = [
        "# Tool list generated by galaxy_tools_export.py",
        "# Install with: shed-tools install -g <url> -a <key> -t tool_list.yml",
        "tools:",
    ]

    current_section = None
    for r in repos:
        if r["section_id"] != current_section:
            current_section = r["section_id"]
            lines.append("")
            lines.append(f"  # panel section: {current_section}")
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

    return "\n".join(lines)


def render_routing(tools: list, default_dest: str,
                   used_existing: bool, used_tpv: bool) -> str:
    header = [
        "# job_tool_routing generated by galaxy_tools_export.py",
        f"# Default destination: {default_dest}",
    ]
    if used_existing:
        header.append("# Source priority 1: existing group_vars/all/tools (per-tool override)")
    if used_tpv:
        header.append("# Source priority 2: TPV shared database (static cores → destination)")
    header.append("# Review before commit.")
    header.append("job_tool_routing:")

    lines = list(header)
    current_section = None
    for t in tools:
        if t["section"] != current_section:
            current_section = t["section"]
            lines.append("")
            lines.append(f"  # --- {current_section} ---")

        comment_parts = []
        if t["repo_name"]:
            comment_parts.append(f"repo: {t['repo_name']}")
        if t["source"] and t["source"] != "default":
            comment_parts.append(f"src: {t['source']}")
        comment = ("  # " + "  ".join(comment_parts)) if comment_parts else ""

        lines.append(f'  - id: "{t["id"]}"')
        lines.append(f'    destination: "{t["destination"]}"{comment}')

    return "\n".join(lines)


# =============================================================================
# CLI / Main
# =============================================================================

def parse_args(argv):
    args = {
        "galaxy_url":     None,
        "env":            None,
        "dest":           "cluster_1",
        "tool_list_path": None,   # filled later (env-derived or default)
        "routing_path":   None,   # filled later (env-derived or default)
        "no_revisions":   False,
        "skip_builtins":  False,
        "admin_key":      None,
        "existing_tools": None,
        "no_tpv":         False,
        "tpv_url":        TPV_URL_DEFAULT,
    }
    i = 1
    while i < len(argv):
        a = argv[i]
        if   a == "--dest":            args["dest"] = argv[i+1]; i += 2
        elif a == "--env":             args["env"] = argv[i+1]; i += 2
        elif a == "--tool-list":       args["tool_list_path"] = argv[i+1]; i += 2
        elif a == "--routing":         args["routing_path"] = argv[i+1]; i += 2
        elif a == "--no-revisions":    args["no_revisions"] = True; i += 1
        elif a == "--skip-builtins":   args["skip_builtins"] = True; i += 1
        elif a == "--admin-key":       args["admin_key"] = argv[i+1]; i += 2
        elif a == "--existing-tools":  args["existing_tools"] = argv[i+1]; i += 2
        elif a == "--no-tpv":          args["no_tpv"] = True; i += 1
        elif a == "--tpv-url":         args["tpv_url"] = argv[i+1]; i += 2
        elif not a.startswith("--"):   args["galaxy_url"] = a; i += 1
        else:                          i += 1
    return args


def find_repo_root() -> Path:
    """
    Locate the galaxyXpand repo root by walking up from this script's location
    until we find a directory containing BOTH `ansible.cfg` and `environments/`.
    Tolerates the script being moved anywhere inside the repo (scripts/, bin/,
    root, etc.) and fails fast with a clear message if not found.

    The double marker avoids false positives if a parent directory happens to
    be another Ansible repo or just contains an environments/ folder.
    """
    start = Path(__file__).resolve().parent
    for candidate in [start, *start.parents]:
        if ((candidate / "ansible.cfg").is_file()
                and (candidate / "environments").is_dir()):
            return candidate
    print(f"[error] could not locate galaxyXpand repo root", file=sys.stderr)
    print(f"[error] walked up from {start} without finding a directory",
          file=sys.stderr)
    print(f"[error] containing both 'ansible.cfg' and 'environments/'",
          file=sys.stderr)
    sys.exit(2)


def derive_env_paths(env: str, args: dict) -> None:
    """
    Populate args paths from the galaxyXpand repo layout based on --env <name>.
    Fails fast with a clean message if:
      - the environment directory does not exist (lists available envs)
      - the output config directory does not exist (we never create dirs in a git repo)

    Explicit --tool-list / --routing / --existing-tools always win over derivation.
    """
    repo = find_repo_root()
    envs_dir = repo / "environments"
    env_dir  = envs_dir / env

    if not env_dir.is_dir():
        if envs_dir.is_dir():
            available = sorted(
                p.name for p in envs_dir.iterdir()
                if p.is_dir() and not p.name.startswith("000_")
            )
            print(f"[error] environment '{env}' not found under {envs_dir}",
                  file=sys.stderr)
            print(f"[error] available environments: {', '.join(available)}",
                  file=sys.stderr)
        else:
            print(f"[error] no 'environments/' directory found at {envs_dir}",
                  file=sys.stderr)
            print(f"[error] is this script running from inside the galaxyXpand repo?",
                  file=sys.stderr)
        sys.exit(2)

    prefix     = env.lower()
    config_dir = env_dir / "files" / "galaxy" / "config"
    gv_tools   = env_dir / "group_vars" / "all" / "tools"

    needs_outputs = (args["tool_list_path"] is None) or (args["routing_path"] is None)
    if needs_outputs and not config_dir.is_dir():
        print(f"[error] expected output directory does not exist: {config_dir}",
              file=sys.stderr)
        print(f"[error] create it (and git add) before re-running with --env {env}",
              file=sys.stderr)
        print(f"[error] or pass --tool-list / --routing explicitly to bypass",
              file=sys.stderr)
        sys.exit(2)

    if args["tool_list_path"] is None:
        args["tool_list_path"] = str(config_dir / f"{prefix}_tool_list.yml")
    if args["routing_path"] is None:
        args["routing_path"] = str(config_dir / f"{prefix}_job_tool_routing.yml")

    if args["existing_tools"] is None:
        if gv_tools.is_file():
            args["existing_tools"] = str(gv_tools)
        else:
            print(f"[info]  --env {env}: no {gv_tools.relative_to(repo)} "
                  f"→ skipping existing-tools enrichment", file=sys.stderr)


def main():
    args = parse_args(sys.argv)
    if not args["galaxy_url"]:
        print(__doc__)
        sys.exit(1)

    # ── 0. Resolve paths from --env if requested ─────────────────────────────
    if args["env"]:
        derive_env_paths(args["env"], args)
        print(f"[env]   {args['env']} → tool-list={args['tool_list_path']}",
              file=sys.stderr)
        print(f"[env]   {args['env']} → routing  ={args['routing_path']}",
              file=sys.stderr)
        if args["existing_tools"]:
            print(f"[env]   {args['env']} → existing={args['existing_tools']}",
                  file=sys.stderr)

    # Apply fallback defaults if no --env and user didn't specify
    if args["tool_list_path"] is None:
        args["tool_list_path"] = "tool_list.yml"
    if args["routing_path"] is None:
        args["routing_path"] = "job_tool_routing.yml"

    # ── 1. Fetch Galaxy panel ────────────────────────────────────────────────
    panel = fetch_panel(args["galaxy_url"])
    repos, routing = parse_panel(panel, skip_builtins=args["skip_builtins"])
    print(f"[parse] {len(repos)} unique repos  |  {len(routing)} unique tool IDs",
          file=sys.stderr)

    # ── 2. Fetch data managers (admin only) ──────────────────────────────────
    dm_repos, dm_routing = [], []
    if args["admin_key"]:
        flat = fetch_flat(args["galaxy_url"], args["admin_key"])
        dm_repos, dm_routing = parse_data_managers(flat)
        print(f"[parse] {len(dm_repos)} data manager repos", file=sys.stderr)

    all_routing = routing + dm_routing

    # ── 3. Existing group_vars/all/tools (priority 1) ────────────────────────
    existing  = {}
    cores_map = []
    used_existing = False
    if args["existing_tools"]:
        print(f"[read]  existing tools: {args['existing_tools']}", file=sys.stderr)
        existing  = parse_existing_tools(args["existing_tools"], args["dest"])
        cores_map = build_cores_map(args["existing_tools"])
        used_existing = True
        print(f"[parse] existing overrides: {len(existing)}", file=sys.stderr)
        print(f"[parse] cores_map: {cores_map}", file=sys.stderr)
    else:
        print("[info]  no --existing-tools → no per-tool overrides, no cores_map",
              file=sys.stderr)

    # ── 4. TPV (priority 2) — only useful if cores_map is available ──────────
    tpv_cores = {}
    used_tpv  = False
    if args["no_tpv"]:
        print("[info]  --no-tpv → skipping TPV fetch", file=sys.stderr)
    elif not cores_map:
        print("[info]  no cores_map → skipping TPV fetch (would have no effect)",
              file=sys.stderr)
    else:
        tpv_text  = fetch_tpv(args["tpv_url"])
        tpv_cores = parse_tpv_text(tpv_text)
        used_tpv  = bool(tpv_cores)
        print(f"[parse] TPV tools with static cores: {len(tpv_cores)}", file=sys.stderr)

    # ── 5. Enrich routing ────────────────────────────────────────────────────
    enrich_routing(all_routing, existing, tpv_cores, cores_map, args["dest"])
    stats = Counter(t["source"].split("(")[0] for t in all_routing)
    print(f"[enrich] existing={stats.get('existing', 0)}  "
          f"tpv={stats.get('tpv', 0)}  "
          f"default={stats.get('default', 0)}", file=sys.stderr)

    # ── 6. Write outputs ─────────────────────────────────────────────────────
    tool_list_text = render_tool_list(repos, dm_repos, not args["no_revisions"])
    routing_text   = render_routing(all_routing, args["dest"], used_existing, used_tpv)

    Path(args["tool_list_path"]).write_text(tool_list_text)
    Path(args["routing_path"]).write_text(routing_text)

    print(f"[write] {args['tool_list_path']}", file=sys.stderr)
    print(f"[write] {args['routing_path']}", file=sys.stderr)


if __name__ == "__main__":
    main()
