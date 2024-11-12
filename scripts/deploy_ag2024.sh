#!/bin/bash
date | tee ~/install_log.txt
apt update | tee ~/install_log.txt
apt upgrade -y | tee ~/install_log.txt
apt install python3-pip python3-dev -y | tee ~/install_log.txt
pip install -U pip | tee ~/install_log.txt
/usr/local/bin/pip install ansible==3.0.0 | tee ~/install_log.txt
ansible-galaxy install -r requirements.yml -p roles/ -f | tee ~/install_log.txt
time ansible-playbook -i environments/ag2024/hosts playbook.yml | tee ~/install_log.txt
sleep 60
systemctl restart galaxy.target
sleep 30
galaxyctl status | tee ~/install_log.txt
time ansible-playbook -i environments/ag2024/hosts install_tools.yml | tee ~/install_log.txt
date | tee ~/install_log.txt
