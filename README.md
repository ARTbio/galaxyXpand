# GalaxyXpand

**GalaxyXpand** is an Ansible playbook for automated [Galaxy](https://galaxyproject.org/) server deployment on Ubuntu. Developed by the [ARTbio platform](https://artbio.fr/), it is the modern successor to *GalaxyKickStart* and deploys production-ready Galaxy instances on cloud environments (GCE, OVH, AWS) or bare-metal servers.

---

## OS Compatibility

| Target OS | Galaxy Version | Branch / Tag |
|-----------|---------------|--------------|
| **Ubuntu 24.04 LTS** | Latest (current) | `main` |
| **Ubuntu 20.04 LTS** | ≤ 24.1 | `final/release_24.1_ubuntu20.04-final` |

> For Ubuntu 20.04: `git checkout release_24.1_ubuntu20.04-final`

---

## Requirements

On the **control node** (Ubuntu 24.04 recommended):

```bash
sudo apt update && sudo apt install ansible -y
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
| `reinitialize_slurm.yml` | Reset Slurm state (useful after node restart) |
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
    │   ├── galaxy              # Galaxy-specific overrides
    │   └── nginx               # nginx overrides (if managed by galaxyXpand)
    ├── files/                  # Static files (job_conf.yml, logos, tool lists)
    └── templates/              # Jinja2 templates (welcome page, nginx vhost)
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
| `galaxy_commit_id` | `release_25.1` | Galaxy Git branch or tag to deploy |
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

> Partition names in `slurm_partitions` must exactly match destination IDs in your
`files/job_conf.yml`. A mismatch causes immediate job failure.

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

## Available Environments

| Environment | Target | Notes |
|-------------|--------|-------|
| `dev_gce` | GCE VM (CI/CD) | Reference environment, tested on every push |
| `artbio-gce-test` | GCE VM | ARTbio integration test (15 representative tools) |
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

1. **Symlink `000_cross_env_vars`** is mandatory in every environment's `group_vars/all/` — see Architecture section.
2. **Job handler naming:** if you rename handler pools in `galaxy_config`, ensure `job_conf.yml` uses `assign: db-skip-locked` so any available handler picks up jobs regardless of process name.
3. **`slurm-drmaa1` version mismatch** after OS upgrade: reinstall manually from the PPA to get the Ubuntu-release-appropriate build.
4. **Miniforge migration from legacy Miniconda:** if `conda` is present but `mamba` is absent in `miniconda_prefix`, the playbook automatically runs the Miniforge installer in upgrade mode (`-u -b`) before the `galaxyproject.miniconda` role executes.
5. **`galaxy_tool_dependency_dir`** must be defined explicitly in each environment's `group_vars` — do not rely on role defaults, as this variable must be available during pre-tasks.
