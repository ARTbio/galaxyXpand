#!/bin/bash
date
apt update
apt install python3-pip python3-dev -q
pip install -U pip
source .bashrc
pip install ansible==3.0.0
ansible-galaxy install -r requirements.yml -p roles/
time ansible-playbook -i environments/ag2024/hosts playbook.yml
time ansible-playbook -i environments/ag2024/hosts install_tools.yml
date
