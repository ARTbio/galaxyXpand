#!/usr/bin/env python3
"""
enrich_routing.py
=================
Enrich a job_tool_routing draft (all cluster_1) with non-default destinations
from two sources, in priority order:

  1. Existing galaxyXpand group_vars/all/tools  (admin-curated, highest trust)
  2. TPV shared database tools.yml              (community, cores only, no mem)

Usage:
    python3 enrich_routing.py \\
        --draft  usegalaxy_job_routing_draft.yml \\
        --tools  environments/Conect/group_vars/all/tools \\
        --tpv    tpv-tools.yml \\
        --out    conect_job_tool_routing.yml \\
        --default-dest cluster_1

TPV cores → destination mapping is derived automatically from the destinations
declared in the --tools file (ntasks field).  You can override with --cores-map.
"""

import re
import sys
from pathlib import Path
from collections import OrderedDict


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv):
    args = {
        "draft":        None,
        "tools":        None,
        "tpv":          None,
        "out":          "conect_job_tool_routing.yml",
        "default_dest": "cluster_1",
    }
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--draft":        args["draft"] = argv[i+1]; i += 2
        elif a == "--tools":      args["tools"] = argv[i+1]; i += 2
        elif a == "--tpv":        args["tpv"]   = argv[i+1]; i += 2
        elif a == "--out":        args["out"]   = argv[i+1]; i += 2
        elif a == "--default-dest": args["default_dest"] = argv[i+1]; i += 2
        else: i += 1
    return args


# ---------------------------------------------------------------------------
# Parse existing tools file  (group_vars/all/tools)
# Extracts: {short_id: destination}  for all non-default-dest entries
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Parse TPV tools.yml
# Extracts: {short_id: cores}  — skipping dynamic expressions, keeping static ints
# ---------------------------------------------------------------------------

def short_id_from_full(full_id: str) -> str:
    """toolshed.../repo/tool_id/.* → tool_id"""
    # Remove trailing /.*
    clean = full_id.rstrip(".*").rstrip("/")
    parts = clean.split("/")
    return parts[-1] if parts else full_id


def parse_tpv(path: str) -> dict:
    """Return {short_id: cores} for tools with a static integer cores value."""
    tpv = {}
    current_id = None
    with open(path) as f:
        for line in f:
            # Tool key line: starts without indentation, ends with ":"
            # Two formats:
            #   "  toolshed.g2.bx.psu.edu/repos/devteam/bwa/bwa_mem/.*:"
            #   "  .*bwa_mem_index_builder_data_manager.*:"
            m_tool    = re.match(r'^  (toolshed\S+):\s*$', line)
            m_wildcard = re.match(r'^  \.\*(\w+)\.\*:\s*$', line)
            m_cores   = re.match(r'^\s+cores:\s+(\S+)', line)

            if m_tool:
                current_id = short_id_from_full(m_tool.group(1))
            elif m_wildcard:
                current_id = m_wildcard.group(1)
            elif m_cores and current_id:
                raw = m_cores.group(1).strip()
                # Only keep static integers — skip Python expressions
                try:
                    cores = int(raw)
                    tpv[current_id] = cores
                except ValueError:
                    pass  # dynamic expression, skip
                # Don't reset current_id: a tool can have cores + mem + env
            elif line and not line.startswith(" ") and not line.startswith("#"):
                current_id = None

    return tpv


# ---------------------------------------------------------------------------
# Build cores → destination mapping from existing tools file destinations
# ---------------------------------------------------------------------------

def build_cores_map(tools_path: str) -> dict:
    """
    Parse job_destinations from tools file and build a cores→dest mapping.
    For each destination with ntasks: N, map cores <= N to that destination.
    Returns sorted list of (max_cores, dest_name) for threshold lookup.
    """
    destinations = {}  # name → ntasks
    current_dest = None
    with open(tools_path) as f:
        in_destinations = False
        for line in f:
            if re.match(r'^job_destinations:', line):
                in_destinations = True
                continue
            if in_destinations:
                # Top-level key under job_destinations (dest name)
                m_dest = re.match(r'^  (\w+):', line)
                if m_dest:
                    current_dest = m_dest.group(1)
                    continue
                # ntasks under current dest
                m_ntasks = re.match(r'^    ntasks:\s+(\d+)', line)
                if m_ntasks and current_dest:
                    destinations[current_dest] = int(m_ntasks.group(1))
                # Stop at next top-level key
                if line and not line.startswith(" ") and not line.startswith("#"):
                    in_destinations = False

    # Build sorted thresholds: [(ntasks, dest_name), ...]
    # Exclude special destinations without ntasks semantics (java_cluster etc)
    cluster_dests = sorted(
        [(n, d) for d, n in destinations.items() if re.match(r'^cluster_\d+$', d)],
        key=lambda x: x[0]
    )
    return cluster_dests  # e.g. [(1,'cluster_1'),(2,'cluster_2'),(4,'cluster_4'),...]


def cores_to_dest(cores: int, cores_map: list, default_dest: str) -> str:
    """Find the largest cluster destination with ntasks <= cores (round down)."""
    best = default_dest
    for max_c, dest in cores_map:
        if max_c <= cores:
            best = dest
    return best


# ---------------------------------------------------------------------------
# Parse draft routing
# ---------------------------------------------------------------------------

def parse_draft(path: str):
    """
    Returns list of dicts:
      {id, destination, repo_name, section, line_orig}
    """
    tools = []
    current_section = ""
    with open(path) as f:
        for line in f:
            m_section = re.match(r'\s*#\s*---\s*(.+?)\s*---', line)
            m_id      = re.match(r'\s*-\s+id:\s+"?([^"#\n]+)"?', line)
            m_dest    = re.match(r'\s+destination:\s+"?([^"#\n]+)"?', line)
            m_repo    = re.search(r'#\s*repo:\s*(\S+)', line)

            if m_section:
                current_section = m_section.group(1)
            elif m_id:
                tools.append({
                    "id":          m_id.group(1).strip(),
                    "destination": "cluster_1",
                    "repo_name":   "",
                    "section":     current_section,
                })
            elif m_dest and tools:
                tools[-1]["destination"] = m_dest.group(1).strip()
                if m_repo:
                    tools[-1]["repo_name"] = m_repo.group(1)
            elif m_repo and tools and not m_dest:
                tools[-1]["repo_name"] = m_repo.group(1)
    return tools


# ---------------------------------------------------------------------------
# Enrich
# ---------------------------------------------------------------------------

def enrich(tools, existing, tpv_cores, cores_map, default_dest):
    """
    For each tool in draft, determine best destination.
    Returns list of (tool_dict, source) where source ∈ {existing, tpv, default}
    """
    result = []
    for t in tools:
        sid = t["id"]
        if sid in existing:
            dest   = existing[sid]
            source = "existing"
        elif sid in tpv_cores:
            dest   = cores_to_dest(tpv_cores[sid], cores_map, default_dest)
            source = f"tpv({tpv_cores[sid]}c)"
            if dest == default_dest:
                source = "default"
        else:
            dest   = default_dest
            source = "default"
        result.append({**t, "destination": dest, "source": source})
    return result


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render(tools, default_dest):
    lines = [
        "# job_tool_routing enriched by enrich_routing.py",
        "# Sources: existing tools file (priority 1) | TPV cores (priority 2)",
        "# 'default' = cluster_1, no override found",
        "job_tool_routing:",
    ]
    current_section = None
    for t in tools:
        if t["section"] != current_section:
            current_section = t["section"]
            lines.append("")
            lines.append(f"  # --- {current_section} ---")

        dest   = t["destination"]
        source = t["source"]
        repo   = t["repo_name"]

        comment_parts = []
        if repo:
            comment_parts.append(f"repo: {repo}")
        if source != "default":
            comment_parts.append(f"src: {source}")

        comment = ("  # " + "  ".join(comment_parts)) if comment_parts else ""
        lines.append(f'  - id: "{t["id"]}"')
        lines.append(f'    destination: "{dest}"{comment}')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args(sys.argv)
    if not all([args["draft"], args["tools"], args["tpv"]]):
        print(__doc__)
        sys.exit(1)

    print(f"[read]  draft   : {args['draft']}", file=sys.stderr)
    print(f"[read]  tools   : {args['tools']}", file=sys.stderr)
    print(f"[read]  tpv     : {args['tpv']}", file=sys.stderr)

    existing  = parse_existing_tools(args["tools"], args["default_dest"])
    tpv_cores = parse_tpv(args["tpv"])
    cores_map = build_cores_map(args["tools"])
    draft     = parse_draft(args["draft"])

    print(f"[parse] existing overrides : {len(existing)}", file=sys.stderr)
    print(f"[parse] tpv tools with cores: {len(tpv_cores)}", file=sys.stderr)
    print(f"[parse] cores_map : {cores_map}", file=sys.stderr)

    enriched = enrich(draft, existing, tpv_cores, cores_map, args["default_dest"])

    # Stats
    from collections import Counter
    stats = Counter(t["source"].split("(")[0] for t in enriched)
    print(f"[enrich] existing={stats['existing']}  tpv={stats['tpv']}  default={stats['default']}",
          file=sys.stderr)

    output = render(enriched, args["default_dest"])
    Path(args["out"]).write_text(output)
    print(f"[write] {args['out']}", file=sys.stderr)


if __name__ == "__main__":
    main()
