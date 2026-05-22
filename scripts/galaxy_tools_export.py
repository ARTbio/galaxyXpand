#!/usr/bin/env python3
"""
galaxy_tools_export.py
======================
Generate tool_list.yml (Ephemeris) and the Ansible variable file tools (containing
`job_tool_routing:`) from a single Galaxy instance, optionally enriching with:

  1. An existing galaxyXpand group_vars/all/job_conf file  (priority 1)
  2. The live TPV shared database tools.yml                (priority 2, cores only)

Pipeline:
  Galaxy /api/tools?in_panel=true   →  tool_list.yml + routing skeleton
  Galaxy /api/tools?in_panel=false  →  data managers (if --admin-key)
  group_vars/all/job_conf           →  per-tool destination overrides + cores_map
                                        + job_default_destination + valid destinations
  TPV tools.yml (HTTPS GET)         →  static cores → destination (via cores_map)

Output files (with --env):
  environments/<env>/files/galaxy/config/tool_list.yml
  environments/<env>/group_vars/all/tools                  (Ansible var, not a Galaxy file)

Usage:
    python3 galaxy_tools_export.py <galaxy_url> [options]

Options:
    --env <name>             galaxyXpand environment (Conect, ARTbio, Mississippi, ...).
                             Derives default paths from the repo layout:
                               --job-conf  environments/<name>/group_vars/all/job_conf
                               --tool-list environments/<name>/files/galaxy/config/tool_list.yml
                               --routing   environments/<name>/group_vars/all/tools
                             Explicit --tool-list / --routing / --job-conf override.
                             The repo root is located by walking up from this script
                             looking for `ansible.cfg` + `environments/` — the script
                             can live anywhere inside the repo.
    --dest <name>            Force the effective default destination.
                             Default: read job_default_destination from --job-conf,
                             or 'cluster_1' if no job-conf.
                             Tools resolving to this default are NOT emitted in the
                             routing output (they inherit job_default_destination at
                             runtime). Use --include-defaults to override.
    --include-defaults       Emit ALL tools in the routing output, including those
                             resolving to the default destination. Useful for the
                             very first generation of a new environment.
    --tool-list <path>       Output path for tool_list.yml
    --routing <path>         Output path for the routing var file (typically `tools`)
    --no-revisions           Omit changeset_revision from tool_list (install latest)
    --skip-builtins          Exclude built-in Galaxy tools from routing output
    --admin-key <key>        Galaxy API key; enables data manager fetch
    --job-conf <path>        Existing group_vars/all/job_conf for overrides + cores_map
    --no-tpv                 Skip TPV fetch (offline / debug)
    --tpv-url <url>          Override TPV URL (default: galaxyproject/tpv-shared-database main)

Examples:
    # Standard usage — paths auto-derived
    python3 scripts/galaxy_tools_export.py https://usegalaxy.sorbonne-universite.fr \\
        --env Conect --admin-key MY_KEY --skip-builtins

    # First generation of a new env (no overrides exist yet → emit everything)
    python3 scripts/galaxy_tools_export.py https://usegalaxy.example.org \\
        --env NewEnv --include-defaults
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
# Existing group_vars/all/tools parsing — single-pass, extracts everything
# =============================================================================

def parse_existing_config(path: str):
    """
    Single-pass parser for environments/<env>/group_vars/all/tools. Returns:
      - file_default_dest : str | None  (from `job_default_destination:`)
      - valid_dests       : set         (all destination names in `job_destinations:`)
      - cores_map         : list        (sorted [(ntasks, name)] for cluster_N only)
      - overrides_raw     : dict        ({id: destination} — all entries, unfiltered)

    Filtering of overrides against the effective default is done at the caller
    level, since the effective default may come from --dest or this file.
    """
    file_default_dest = None
    valid_dests       = set()
    destinations_ntasks = {}   # name → ntasks (for cores_map)
    overrides_raw     = {}

    current_dest = None
    current_id   = None
    in_destinations = False

    with open(path) as f:
        for line in f:
            # job_default_destination (top-level)
            m_default = re.match(r'^job_default_destination:\s+"?([^"#\n]+?)"?\s*(?:#.*)?$', line)
            if m_default:
                file_default_dest = m_default.group(1).strip()
                continue

            # job_destinations section opener
            if re.match(r'^job_destinations:', line):
                in_destinations = True
                current_dest = None
                continue

            if in_destinations:
                m_dest_name = re.match(r'^  (\w+):\s*$', line)
                if m_dest_name:
                    current_dest = m_dest_name.group(1)
                    valid_dests.add(current_dest)
                    continue
                m_ntasks = re.match(r'^    ntasks:\s+(\d+)', line)
                if m_ntasks and current_dest:
                    destinations_ntasks[current_dest] = int(m_ntasks.group(1))
                    continue
                # Exit job_destinations block at next non-indented non-comment line
                if line and not line.startswith(" ") and not line.startswith("#"):
                    in_destinations = False
                    # fall through — this same line may be a new top-level key

            # Tool overrides (job_tool_routing entries; can appear anywhere)
            m_id   = re.match(r'\s*-\s+id:\s+"?([^"#\n]+?)"?\s*(?:#.*)?$', line)
            m_dest = re.match(r'\s+destination:\s+"?([^"#\n]+?)"?\s*(?:#.*)?$', line)
            if m_id:
                current_id = m_id.group(1).strip()
            elif m_dest and current_id:
                overrides_raw[current_id] = m_dest.group(1).strip()
                current_id = None

    cores_map = sorted(
        [(n, d) for d, n in destinations_ntasks.items() if re.match(r'^cluster_\d+$', d)],
        key=lambda x: x[0],
    )
    return file_default_dest, valid_dests, cores_map, overrides_raw


def filter_overrides(overrides_raw: dict, default_dest: str) -> dict:
    """Drop entries whose destination equals the effective default."""
    return {sid: d for sid, d in overrides_raw.items() if d != default_dest}


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

    return "\n".join(lines) + "\n"


def render_routing(tools: list, default_dest: str,
                   used_existing: bool, used_tpv: bool,
                   include_defaults: bool = False) -> str:
    header = [
        "# job_tool_routing generated by galaxy_tools_export.py",
        f"# Effective default destination (skipped from emission): {default_dest}",
    ]
    if used_existing:
        header.append("# Source priority 1: group_vars/all/job_conf (per-tool override)")
    if used_tpv:
        header.append("# Source priority 2: TPV shared database (static cores → destination)")
    if include_defaults:
        header.append("# --include-defaults: emitting ALL tools (review before commit)")
    else:
        header.append("# Only tools with explicit overrides are emitted; others inherit "
                      "job_default_destination.")
    header.append("job_tool_routing:")

    # Filter tools: drop those falling on the default unless --include-defaults
    visible = tools if include_defaults else [t for t in tools if t["source"] != "default"]

    lines = list(header)
    current_section = None
    for t in visible:
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

    return "\n".join(lines) + "\n"


# =============================================================================
# CLI / Main
# =============================================================================

def parse_args(argv):
    args = {
        "galaxy_url":       None,
        "env":              None,
        "dest":             None,   # auto-detected from job-conf if None
        "tool_list_path":   None,
        "routing_path":     None,
        "no_revisions":     False,
        "skip_builtins":    False,
        "admin_key":        None,
        "job_conf":         None,
        "no_tpv":           False,
        "tpv_url":          TPV_URL_DEFAULT,
        "include_defaults": False,
    }
    i = 1
    while i < len(argv):
        a = argv[i]
        if   a == "--dest":              args["dest"] = argv[i+1]; i += 2
        elif a == "--env":               args["env"] = argv[i+1]; i += 2
        elif a == "--tool-list":         args["tool_list_path"] = argv[i+1]; i += 2
        elif a == "--routing":           args["routing_path"] = argv[i+1]; i += 2
        elif a == "--no-revisions":      args["no_revisions"] = True; i += 1
        elif a == "--skip-builtins":     args["skip_builtins"] = True; i += 1
        elif a == "--admin-key":         args["admin_key"] = argv[i+1]; i += 2
        elif a == "--job-conf":          args["job_conf"] = argv[i+1]; i += 2
        elif a == "--no-tpv":            args["no_tpv"] = True; i += 1
        elif a == "--tpv-url":           args["tpv_url"] = argv[i+1]; i += 2
        elif a == "--include-defaults":  args["include_defaults"] = True; i += 1
        elif not a.startswith("--"):     args["galaxy_url"] = a; i += 1
        else:                            i += 1
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
      - an expected output directory does not exist (we never create dirs in a git repo)

    Explicit --tool-list / --routing / --job-conf always win over derivation.

    New convention (post-refactor):
      tool_list  → files/galaxy/config/tool_list.yml         (Galaxy input)
      routing    → group_vars/all/tools                      (Ansible var, generated)
      job-conf   → group_vars/all/job_conf                   (Ansible var, human-edited)
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

    config_dir     = env_dir / "files" / "galaxy" / "config"
    group_vars_dir = env_dir / "group_vars" / "all"
    gv_job_conf    = group_vars_dir / "job_conf"

    needs_tool_list = args["tool_list_path"] is None
    needs_routing   = args["routing_path"]   is None

    if needs_tool_list and not config_dir.is_dir():
        print(f"[error] expected output directory does not exist: {config_dir}",
              file=sys.stderr)
        print(f"[error] create it (and git add) before re-running with --env {env}",
              file=sys.stderr)
        print(f"[error] or pass --tool-list explicitly to bypass",
              file=sys.stderr)
        sys.exit(2)
    if needs_routing and not group_vars_dir.is_dir():
        print(f"[error] expected output directory does not exist: {group_vars_dir}",
              file=sys.stderr)
        print(f"[error] create it (and git add) before re-running with --env {env}",
              file=sys.stderr)
        print(f"[error] or pass --routing explicitly to bypass",
              file=sys.stderr)
        sys.exit(2)

    if args["tool_list_path"] is None:
        args["tool_list_path"] = str(config_dir / "tool_list.yml")
    if args["routing_path"] is None:
        args["routing_path"] = str(group_vars_dir / "tools")

    if args["job_conf"] is None:
        if gv_job_conf.is_file():
            args["job_conf"] = str(gv_job_conf)
        else:
            print(f"[info]  --env {env}: no {gv_job_conf.relative_to(repo)} "
                  f"→ skipping job-conf enrichment", file=sys.stderr)


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
        if args["job_conf"]:
            print(f"[env]   {args['env']} → job-conf={args['job_conf']}",
                  file=sys.stderr)

    # Apply fallback defaults if no --env and user didn't specify
    if args["tool_list_path"] is None:
        args["tool_list_path"] = "tool_list.yml"
    if args["routing_path"] is None:
        args["routing_path"] = "tools"

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

    # ── 3. Existing group_vars/all/job_conf (priority 1) ─────────────────────
    overrides     = {}
    cores_map     = []
    valid_dests   = set()
    file_default  = None
    used_existing = False
    if args["job_conf"]:
        print(f"[read]  job-conf: {args['job_conf']}", file=sys.stderr)
        file_default, valid_dests, cores_map, overrides_raw = \
            parse_existing_config(args["job_conf"])
        used_existing = bool(overrides_raw)
        print(f"[parse] job_default_destination: {file_default!r}", file=sys.stderr)
        print(f"[parse] job_destinations declared: {sorted(valid_dests)}", file=sys.stderr)
        print(f"[parse] cores_map: {cores_map}", file=sys.stderr)
        print(f"[parse] raw overrides parsed: {len(overrides_raw)}", file=sys.stderr)
    else:
        overrides_raw = {}
        print("[info]  no --job-conf → no per-tool overrides, no cores_map",
              file=sys.stderr)

    # ── 3bis. Resolve the effective default destination ──────────────────────
    # Priority: explicit --dest > job_conf's job_default_destination > 'cluster_1'
    if args["dest"]:
        effective_default = args["dest"]
        default_origin    = "--dest"
    elif file_default:
        effective_default = file_default
        default_origin    = "job-conf file"
    else:
        effective_default = "cluster_1"
        default_origin    = "fallback"
    print(f"[default] effective_default = {effective_default!r}  (from {default_origin})",
          file=sys.stderr)

    overrides = filter_overrides(overrides_raw, effective_default)
    if used_existing:
        print(f"[parse] overrides after dropping ones equal to default: {len(overrides)}",
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
    enrich_routing(all_routing, overrides, tpv_cores, cores_map, effective_default)
    stats = Counter(t["source"].split("(")[0] for t in all_routing)
    print(f"[enrich] existing={stats.get('existing', 0)}  "
          f"tpv={stats.get('tpv', 0)}  "
          f"default={stats.get('default', 0)} (dropped from output "
          f"unless --include-defaults)", file=sys.stderr)

    # ── 5bis. Validate emitted destinations against declared job_destinations ─
    if valid_dests:
        emitted_dests = {t["destination"] for t in all_routing
                         if t["source"] != "default" or args["include_defaults"]}
        unknown = emitted_dests - valid_dests
        if unknown:
            print(f"[warn]  emitted destination(s) NOT declared in job_destinations: "
                  f"{sorted(unknown)}", file=sys.stderr)
            print(f"[warn]  declared in {args['job_conf']}: {sorted(valid_dests)}",
                  file=sys.stderr)

    # ── 6. Write outputs ─────────────────────────────────────────────────────
    tool_list_text = render_tool_list(repos, dm_repos, not args["no_revisions"])
    routing_text   = render_routing(all_routing, effective_default,
                                    used_existing, used_tpv,
                                    include_defaults=args["include_defaults"])

    Path(args["tool_list_path"]).write_text(tool_list_text)
    Path(args["routing_path"]).write_text(routing_text)

    print(f"[write] {args['tool_list_path']}", file=sys.stderr)
    print(f"[write] {args['routing_path']}", file=sys.stderr)


if __name__ == "__main__":
    main()
