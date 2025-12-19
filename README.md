## GalaxyXpand 🌌

**GalaxyXpand** is the next-generation Ansible playbook for automated [Galaxy](https://galaxyproject.org/) server deployment. Developed by the [ARTbio platform](https://artbio.fr/), it serves as the modern successor to *GalaxyKickStart*, designed to deploy production-ready Galaxy instances on cloud environments (e.g., Google Cloud Engine) or bare-metal servers.

### 🚀 Features

* **Automated Deployment:** Deploys a full Galaxy stack from scratch.
* **Job Management:** Supports configurations for Slurm or Celery.
* **Tool Management:** Includes utilities to install Galaxy tools automatically.
* **Extensible:** Uses standard Ansible roles and collections.

### 📋 Requirements

Before running this playbook, ensure your control node and target machines meet the following requirements.


### Operating System Compatibility

The playbook version you use depends on your target Operating System and the Galaxy version you intend to deploy.


<table>
  <tr>
   <td><strong>Target OS</strong>
   </td>
   <td><strong>Galaxy Version</strong>
   </td>
   <td><strong>Playbook Branch / Tag</strong>
   </td>
  </tr>
  <tr>
   <td><strong>Ubuntu 24.04 LTS</strong>
   </td>
   <td>Latest (Current)
   </td>
   <td>main
   </td>
  </tr>
  <tr>
   <td><strong>Ubuntu 20.04 LTS</strong>
   </td>
   <td>$\le$ 24.1
   </td>
   <td>final/release_24.1_ubuntu20.04-final
   </td>
  </tr>
</table>



⚠️ For Ubuntu 20.04 users:

You must switch to the dedicated tag or branch to ensure compatibility with Galaxy release 24.1 or older.

```
# Example using the tag
git checkout release_24.1_ubuntu20.04-final
```


### Quick Setup

On a fresh Ubuntu machine, installing the dependencies is straightforward. You do not need to manage complex pip environments manually; the system package manager provides a sufficiently recent version of Ansible.

Run the following command on your control node (Ubuntu 24.04 recommended):
```
sudo apt update && sudo apt install ansible -y
```


### 🏁 Quick Start & Usage

Once Ansible is installed, follow these steps to deploy Galaxy.


#### 1. Setup the Repository
```
# Clone the repository and install the required Ansible roles.
git clone [https://github.com/ARTbio/galaxyXpand.git](https://github.com/ARTbio/galaxyXpand.git)
cd galaxyXpand

# Install external roles dependencies
ansible-galaxy install -r requirements.yml -p roles/
```

#### 2. Deploy Galaxy

Run the main playbook specifying your target environment inventory (e.g., dev_gce).
```
ansible-playbook -i environments/dev_gce/hosts playbook.yml
```

**📝 Note:** If executed on a standard GCE VM (e.g., 4 CPUs), this will deploy a full Galaxy instance. Jobs will be managed by either **Celery** or **Slurm**, depending on the configuration defined in your job_conf.xml.

#### 3. Install Tools

Once Galaxy is running, you can automate the installation of tools (as defined in tool_list.yaml).
```
ansible-playbook -i environments/dev_gce/hosts install_tools.yml
```

*This installs the tools described in [tool_list.yaml.sample](https://github.com/ARTbio/ansible-galaxy-tools/blob/galaxyXpand/files/tool_list.yaml.sample).*

### 🔧 Utilities & Debugging

#### Inspect Variables

To debug or verify the configuration of a specific environment (e.g., Mississippi) without applying changes, use the showvars.yml playbook.
```
ansible-playbook -i environments/Mississippi/hosts showvars.yml
```


*This will display the computed value of all ansible variables for the target environment.*


### ⚙️ Configuration & Actionable Variables

This playbook relies on a **hierarchical configuration architecture**.



1. **Defaults**: Global defaults are defined in environments/000_cross_env_vars.
2. **Overrides**: Specific settings are defined in environments/&lt;your_env>/group_vars/all.

    **ℹ️ Note:** The main galaxy_config dictionary uses a **recursive deep merge**. You only need to define the specific keys you want to change or add in your environment; everything else is inherited from the global defaults.



#### 1. Core Deployment Variables

Control the software versions and main feature flags.


<table>
  <tr>
   <td><strong>Variable</strong>
   </td>
   <td><strong>Default / Example</strong>
   </td>
   <td><strong>Description</strong>
   </td>
  </tr>
  <tr>
   <td>galaxy_commit_id
   </td>
   <td>release_25.1
   </td>
   <td>The Galaxy Git branch or tag to deploy (e.g., downgrade to release_24.1 for stability).
   </td>
  </tr>
  <tr>
   <td>miniconda_installer_version
   </td>
   <td>25.11.0-1
   </td>
   <td>Pinned version of the Miniforge installer to ensure reproducibility.
   </td>
  </tr>
  <tr>
   <td>install_slurm
   </td>
   <td>true
   </td>
   <td>Feature flag to install and configure the Slurm workload manager.
   </td>
  </tr>
  <tr>
   <td>install_uptime
   </td>
   <td>false
   </td>
   <td>Feature flag to install Uptime Kuma for monitoring.
   </td>
  </tr>
</table>



#### 2. Galaxy Configuration (galaxy_config)

Key functional settings nested under galaxy_config. Due to the deep merge strategy, you can override specific leaves of the tree.


<table>
  <tr>
   <td><strong>YAML Path</strong>
   </td>
   <td><strong>Description</strong>
   </td>
  </tr>
  <tr>
   <td><strong>galaxy</strong>
   </td>
   <td>
   </td>
  </tr>
  <tr>
   <td>.admin_users
   </td>
   <td>Comma-separated list of admin emails. <strong>Replaces</strong> the default list entirely.
   </td>
  </tr>
  <tr>
   <td>.brand
   </td>
   <td>Custom text or HTML label for the navigation bar (e.g., "🧬 Ag2025").
   </td>
  </tr>
  <tr>
   <td>.enable_quotas
   </td>
   <td>true or false. Enforce storage limits for users.
   </td>
  </tr>
  <tr>
   <td><strong>gravity</strong>
   </td>
   <td>
   </td>
  </tr>
  <tr>
   <td>.gunicorn.bind
   </td>
   <td>Network binding. Use unix:... for local sockets or 0.0.0.0:4000 for exposing Galaxy (Docker/Cloud).
   </td>
  </tr>
  <tr>
   <td>.gunicorn.workers
   </td>
   <td>Number of Gunicorn workers handling web requests.
   </td>
  </tr>
  <tr>
   <td>.celery.workers
   </td>
   <td>Number of Celery workers for background tasks (if added to the environment).
   </td>
  </tr>
</table>



#### 3. Tool Management

Tools are not defined in the variables directly but referenced via external YAML files.

galaxy_tools_tool_list_files: \
  - "environments/&lt;your_env>/files/your_tool_list.yaml" \



#### 4. Infrastructure & Performance


##### Slurm (Compute)

Slurm resources are often calculated dynamically via Jinja2 filters in the playbook, but can be overridden.



* **slurm_nodes**: Defines CPU/RAM per node.
    * *Default behavior:* Auto-calculates RealMemory as 95% of total RAM.
* **slurm_partitions**: Defines queues (e.g., debug).
    * *Crucial:* Partition names must match the destinations defined in your files/job_conf.yml.


##### NGINX (Proxy)



* **nginx_conf_http.client_max_body_size**: Max upload size (e.g., 10g). Essential for large datasets (FASTQ/BAM).
* **nginx_conf_http.gzip_comp_level**: Compression level (default 6).


#### ⚠️ Important Configuration Gotchas



1. Job Handlers Naming: \
If you rename handler pools in galaxy_config (e.g., changing job-handler to job-handlers), ensure your job_conf.yml uses the assign: - db-skip-locked mechanism. This allows any available handler to pick up jobs regardless of the specific process name.
2. Job Destinations: \
Always verify that every destination ID used in files/job_conf.yml refers to a valid cluster/partition defined in slurm_partitions (in group_vars). A mismatch will cause jobs to fail immediately.