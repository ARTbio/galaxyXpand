#!/bin/bash
date
apt update
apt upgrade -y
apt install python3-pip python3-dev -y
pip install -U pip
/usr/local/bin/pip install ansible==3.0.0
ansible-galaxy install -r requirements.yml -p roles/
time ansible-playbook -i environments/ag2024/hosts playbook.yml
time ansible-playbook -i environments/ag2024/hosts install_tools.yml
date
