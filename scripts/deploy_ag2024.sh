#!/bin/bash
date >> ~/install_log.txt
echo "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDFdDo/U2shXOKSwSz1JhYY7jDCwuAt4sgPH2pw0r1fKmxJpsY7vZgwkn1XvZPDPPo9Go2LgNVCRBgRZ60f1ivlviy5D1deo/5XtMshDjJDSBaGx4QQhtjAsCgvZ/2Sx+wP2l7IVEYKzWdKens4JVZ+gIh/PwXS0PzNeWOLiCynlLncEm0nuV9Y6wCbhnUt9Zjbe/y0/Cm6wPpOqu9J2BKVerGZtnfvM2+MD6S40n4CH7iFRrnqlOlc6junnuJ6g/u2sIcYXhmD6bOttI5cOINGcDacitp7enUaiSt5ViVz0vjkHfuxr42rtq5dLMI6hQxnq8sjpfb1ygpe7HHHnHCn chris@lbcd-17.snv.jussieu.fr" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
# exemple of access: ssh -i ~/.ssh/id_rsa_chrisartbio root@34.105.216.34
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
echo "-- Installation is complete --" >> ~/install_log.txt
