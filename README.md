# GalaxyXpand

**GalaxyXpand** is an Ansible playbook for automated [Galaxy](https://galaxyproject.org/) server deployment on Ubuntu. Developed by the [ARTbio platform](https://artbio.fr/), it is the modern successor to *GalaxyKickStart* and deploys production-ready Galaxy instances on cloud environments (GCE, OVH, AWS) or bare-metal servers.

---

## OS Compatibility

| Target OS | Galaxy Version | Branch / Tag |
|-----------|---------------|--------------|
| **Ubuntu 24.04 LTS** | `release_26.0` (current default) | `main` |
| **Ubuntu 20.04 LTS** | ≤ 24.1 | `final/release_24.1_ubuntu20.04-final` |

> For Ubuntu 20.04: `git checkout release_24.1_ubuntu20.04-final`

The deployed Galaxy version is controlled by `galaxy_commit_id` (see *Key Variables*); you can pin an older release on `main` if needed.

---

## Requirements

On the **control node** (Ubuntu 24.04 recommended):

```bash
sudo apt update && sudo apt install ansible -y
```

Optional Python tooling (only for the admin scripts, e.g. tool-list generation):

```bash
pip install -r requirements.txt
```

---

## Ansible Vault

Secrets (passwords, tokens) are encrypted with `ansible-vault`. The `.vault_pass`
file lives at the repository root and is listed in `.gitignore` — never commit it.

Before any `ansible-playbook` command:

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass
```

---

## Quick Start

```bash
# 1. Clone and install role dependencies
git clone https://github.com/ARTbio/galaxyXpand.git
cd galaxyXpand
ansible-galaxy install -r requirements.yml -p roles/

# 2. Deploy Galaxy
ansible-playbook -i environments/dev_gce/hosts playbook.yml

# 3. Install tools (optional)
ansible-playbook -i environments/dev_gce/hosts install_tools.yml
```

---

## Architecture

### Playbooks

| File | Purpose |
|------|---------|
| `playbook.yml` | Main deployment: PostgreSQL, Galaxy, Slurm, nginx |
| `install_tools.yml` | Install Galaxy tools from a tool list YAML |
| `reinitialize_slurm.yml` | Reset Slurm state (useful after node restart / VM resume) |
| `showvars.yml` | Dump all computed variables for an environment (debug) |

### Environments

Each environment lives under `environments/<name>/` and contains:

```
environments/
├── 000_cross_env_vars          # Global defaults shared by all environments
└── <env_name>/
    ├── hosts                   # Ansible inventory
    ├── group_vars/all/
    │   ├── 000_cross_env_vars  # Symlink → ../../000_cross_env_vars (REQUIRED)
    │   ├── galaxy              # Galaxy overrides + galaxy_config_templates wiring
    │   ├── job_conf            # Job destinations, limits and per-tool routing
    │   └── nginx               # nginx overrides (if managed by galaxyXpand)
    ├── files/                  # Static files served into Galaxy (logos, tool lists)
    └── templates/              # Per-env Jinja2 templates (welcome page, nginx vhost)
```

> **Critical:** The symlink `environments/<env>/group_vars/all/000_cross_env_vars → ../../000_cross_env_vars`
is mandatory in every environment. Without it, the recursive `combine()` in the
pre-task enters an infinite loop causing OOM (31 GB observed on ansible-core 2.16).

### Configuration merge strategy

`galaxy_config` uses a **recursive deep merge**: the playbook merges `common_galaxy_config`
(defined in `000_cross_env_vars`) with the environment-specific `galaxy_config`.
You only need to define the keys you want to override — everything else is inherited.

---

## Key Variables

All defaults are defined in `environments/000_cross_env_vars`. Override
per-environment in `group_vars/all/galaxy`.

### Deployment flags

| Variable | Default | Description |
|----------|---------|-------------|
| `galaxy_commit_id` | `release_26.0` | Galaxy Git branch or tag to deploy |
| `install_slurm` | `true` | Install and configure Slurm |
| `install_uptime` | `false` | Install Uptime monitoring |
| `galaxyxpand_manage_nginx` | `true` | Set to `false` to disable nginx management (external proxy) |

### Conda / Miniforge

| Variable | Default | Description |
|----------|---------|-------------|
| `miniconda_distribution` | `miniforge` | Use Miniforge (avoids Anaconda licence issues) |
| `miniconda_installer_version` | `latest` | Miniforge installer version |
| `miniconda_version` | `latest` | Post-install conda/mamba update target |
| `miniconda_base_env_packages` | `[]` | Packages injected into the base env — keep empty to protect the base Python |
| `miniconda_prefix` | `{{ galaxy_tool_dependency_dir }}/_conda` | Conda installation path |
| `miniconda_channels` | `[conda-forge, bioconda, default]` | Channel priority for tool dependency resolution |

> `miniconda_installer_version` and `miniconda_version` serve different purposes:
the former controls which installer `.sh` is downloaded; the latter controls
`conda update` after installation. Both can safely be set to `latest`.

### Galaxy paths

| Variable | Default |
|----------|---------|
| `galaxy_root` | `/home/galaxy` |
| `galaxy_server_dir` | `{{ galaxy_root }}/galaxy` |
| `galaxy_tool_dependency_dir` | `{{ galaxy_root }}/tool_dependencies` |
| `galaxy_venv_dir` | `/home/galaxy/galaxy/.venv` |

> When creating a new environment, always define `galaxy_tool_dependency_dir` and
`galaxy_root` explicitly. `miniconda_prefix` depends on `galaxy_tool_dependency_dir`
which must be resolved before the roles run.

### Slurm

Resources are computed dynamically via Jinja2:

```yaml
slurm_nodes:
  - name: "{{ ansible_hostname }}"
    CPUs: "{{ ansible_processor_vcpus }}"
    RealMemory: "{{ (ansible_memtotal_mb | int * 0.95) | round(0,'floor') | int }}"
    State: UNKNOWN

slurm_partitions:
  - name: debug
    Default: YES
    Nodes: "{{ ansible_hostname }}"
    State: UP
    DefMemPerCPU: "{{ ((ansible_memtotal_mb|int)*0.9 / (ansible_processor_vcpus|int)) | round(0,'floor') | int }}"
```

### Slurm-DRMAA

The playbook installs `slurm-drmaa1` from the [natefoo PPA](https://launchpad.net/~natefoo/+archive/ubuntu/slurm-drmaa),
which provides Ubuntu-release-aware packages. The correct version is selected automatically via
`default_release: "{{ ansible_distribution_release }}"`.

> On servers **migrated** from Ubuntu 20.04 to 24.04, `slurm-drmaa1` may survive
the upgrade in its old 20.04 build, causing silent DRMAA submission failures.
In this case, reinstall manually: `apt install slurm-drmaa1`.

### nginx

By default, galaxyXpand installs and manages nginx. To use an external proxy
(e.g., a dedicated nginx role, NPM, Traefik):

```yaml
# group_vars/all/nginx
galaxyxpand_manage_nginx: false
```

This disables both the `galaxyproject.nginx` role and the `Overwrite nginx.conf`
post-task.

---

## Job Configuration

Galaxy's `job_conf.yml` is **not** a static file. It is rendered from the shared
template `templates/job_conf.yml.j2`, driven by variables you define per
environment in `group_vars/all/job_conf`. The template is wired into Galaxy
through `galaxy_config_templates` in each environment's `group_vars/all/galaxy`:

```yaml
galaxy_config_templates:
  - src: "{{ playbook_dir }}/templates/job_conf.yml.j2"
    dest: "{{ galaxy_config_dir }}/job_conf.yml"
```

You therefore describe *what you want* (destinations, limits, tool routing) as
data, and let the template produce a valid `job_conf.yml`.

### Variables (`group_vars/all/job_conf`)

| Variable | Description |
|----------|-------------|
| `job_default_destination` | Destination used by tools without an explicit route |
| `job_destinations` | Map of named destinations (see below) |
| `job_limits_anonymous` | Concurrent jobs allowed for anonymous users |
| `job_limits_registered` | Concurrent jobs allowed for registered users |
| `job_limits_environment_total` | *(optional)* Per-destination total concurrency caps |
| `job_limits_environment_user` | *(optional)* Per-destination per-user concurrency caps |
| `job_tool_routing` | Per-tool (or per-tool-class) destination overrides |

Each entry in `job_destinations` accepts:

- `runner`: `slurm` (default) or `local_runner`.
- For Slurm destinations: `ntasks` (CPU cores; default `1`), optional `mem` (MB),
  and an optional `env` list of `{name, value}` pairs (e.g. `_JAVA_OPTIONS`).
- For `local_runner` destinations: optional `tmp_dir: true`.

All Slurm destinations submit to the `debug` partition; they differ only by their
resource request (`--ntasks`, `--mem`). Consequently, the single requirement is
that a `debug` partition exists in `slurm_partitions` — which is the default
(see *Slurm* above). Job-handler assignment is fixed to `db-skip-locked` by the
template, so renaming handler pools never breaks job pickup.

### Example (`group_vars/all/job_conf`)

```yaml
job_default_destination: cluster_1

job_destinations:
  cluster_1:
    ntasks: 1
  cluster_8:
    ntasks: 8
  java_cluster:
    ntasks: 1
    mem: 40960
    env:
      - name: '_JAVA_OPTIONS'
        value: '-Xmx32g -Xms1g -Djava.io.tmpdir=/tmp'
  local_env:
    runner: local_runner
    tmp_dir: true

job_limits_anonymous: 1
job_limits_registered: 64

job_tool_routing:
  - id: "bowtie2"
    destination: "cluster_8"
  - id: "fastqc"
    destination: "java_cluster"
```

---

## Admin Tooling

### `scripts/galaxy_tools_export.py`

An **admin tool** (not a deployment dependency, pure Python 3 standard library)
that does two things against a running Galaxy:

1. Generates an Ephemeris-format `tool_list.yml` from the tools installed and
   exposed in the Galaxy panel.
2. Enriches the environment's `job_conf` routing with destinations derived from
   the shared [TPV database](https://github.com/galaxyproject/tpv-shared-database).

It rewrites **only** the `job_tool_routing:` block. Human-authored entries
(untagged) are preserved as-is; entries it manages are tagged `# src: tpv(Nc)`
and refreshed on each run. Everything else in `job_conf` (destinations, limits,
comments, blank lines) is left verbatim. It also audits orphan overrides,
invalid destinations, and "ghost" repositories (installed but not exposed).

```bash
python3 scripts/galaxy_tools_export.py <galaxy_url> --env <name> [options]

# Example
python3 scripts/galaxy_tools_export.py https://usegalaxy.example.org \
    --env Conect --admin-key MY_KEY --no-revisions --skip-builtins
```

Useful options: `--dry-run` (audit, write nothing), `--no-tpv` (skip TPV fetch),
`--job-conf <path>` / `--tool-list <path>` (override the paths auto-derived from
`--env`), `--dest <name>` (force the effective default destination).

---

## Available Environments

| Environment | Target | Notes |
|-------------|--------|-------|
| `dev_gce` | GCE VM (CI/CD) | Reference environment, tested on every push |
| `ARTbio` | Bare-metal | Production server (artbio.snv.jussieu.fr), external nginx |
| `Conect` | Bare-metal | Production server (usegalaxy.sorbonne-universite.fr) |
| `Mississippi` | Bare-metal | Public Mississippi Galaxy server (mississippi.sorbonne-universite.fr) |
| `ag2025` | GCE VM | Analyse des Génomes 2025 training |
| `Docker` | Docker container | Local development via `docker_startup.sh` |

---

## Debugging

```bash
# Inspect all computed variables for an environment
ansible-playbook -i environments/<env>/hosts showvars.yml

# Run without applying changes
ansible-playbook -i environments/<env>/hosts playbook.yml --check

# Limit to specific tags
ansible-playbook -i environments/<env>/hosts playbook.yml --tags slurm
```

---

## Known Gotchas

1. **Symlink `000_cross_env_vars`** is mandatory in every environment's `group_vars/all/` — see *Architecture*.
2. **Galaxy `release_26.0+` and Gravity:** on 26.0 and later, a `graceful` restart crashes Gravity. `galaxy_gravity_restart_action` is set to `restart` automatically for `release_26.0+` (and omitted otherwise). Keep this in mind if you pin a custom `galaxy_commit_id`.
3. **`slurm-drmaa1` version mismatch** after OS upgrade: reinstall manually from the PPA to get the Ubuntu-release-appropriate build.
4. **Miniforge migration from legacy Miniconda:** if `conda` is present but `mamba` is absent in `miniconda_prefix`, the playbook automatically runs the Miniforge installer in upgrade mode (`-u -b`) before the `galaxyproject.miniconda` role executes.
5. **`galaxy_tool_dependency_dir`** must be defined explicitly in each environment's `group_vars` — do not rely on role defaults, as this variable must be available during pre-tasks.
6. **Job destinations vs partitions:** destination names in `job_destinations` (e.g. `cluster_8`) are Galaxy-side labels, not Slurm partitions. The template submits every Slurm destination to the `debug` partition, so that partition must exist in `slurm_partitions` (it does by default).
