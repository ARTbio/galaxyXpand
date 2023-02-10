[![Docker Repository on Quay](https://quay.io/repository/artbioplatform/galaxyxpand/status "Docker Repository on Quay")](https://quay.io/repository/artbioplatform/galaxyxpand)

# galaxyXpand

Our Next Generation of Ansible Playbook for Galaxy server deployment

Documentation is coming soon.

Requirements
```

Python >= 3.7 
ansible >= 2.10.1
```

### Example of use

```
ansible-galaxy install -r requirements.yml -p roles/
ansible-playbook -i environments/dev_gce/hosts playbook.yml
```
If executed on a GCE VM (4 cpu), this will deploy Galaxy with job being managed either
with celery or slurm (as defined in job_conf.xml)

Then,
```
ansible-playbook -i environments/dev_gce/hosts install_tools.yml
```
installs 3 sample tools described in `files/`

----
```
ansible-playbook -i environments/Mississippi/hosts showvars.yml
```
This will display the value of all ansible variables for the environment Mississippi



Our previous [GalaxyKickStart](https://github.com/artbio/galaxykickstart) Ansible playbook
supports the deployment of Galaxy releases <= 22.01
