#!/bin/bash
date >> ~/install_log.txt
apt update >> ~/install_log.txt
apt upgrade -y >> ~/install_log.txt
apt install python3-pip python3-dev -y >> ~/install_log.txt
pip install -U pip >> ~/install_log.txt
/usr/local/bin/pip install ansible==3.0.0 >> ~/install_log.txt
ansible-galaxy install -r ~/galaxyXpand/requirements.yml -p ~/galaxyXpand/roles/ -f >> ~/install_log.txt
time ansible-playbook -i ~/galaxyXpand/environments/ag2024/hosts ~/galaxyXpand/playbook.yml >> ~/install_log.txt
sleep 60
systemctl restart galaxy.target
sleep 30
galaxyctl status >> ~/install_log.txt
time ansible-playbook -i ~/galaxyXpand/environments/ag2024/hosts ~/galaxyXpand/install_tools.yml >> ~/install_log.txt
date >> ~/install_log.txt
