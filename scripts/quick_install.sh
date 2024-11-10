#!/bin/bash

apt update
apt install python3-pip python3-dev
pip install -U pip
source .bashrc
pip install ansible==3.0.0

curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh ./get-docker.sh

git clone https://github.com/artbio/galaxyXpand
sed -i "s/vault_password_file/#vault_password_file/" galaxyXpand/ansible.cfg


