## Introduction
Pour la rendre 100% automatique la réinitialisation de slurm sur une VM générée
à partir d'un VMI (image), nous créons un service systemd "one-shot"
(à exécution unique) qui lancera le playbook `reinitialize_slurm.yml` au premier
démarrage de la VM des étudiants (si celui-ci est fait à partir d'une VMI galaxyXpand).

Ce service fera exactement ce qu'on demanderait aux étudiants de faire
(sudo -i, puis cd galaxyXpand && ansible-playbook)..., puis il s'auto-détruira
pour ne jamais être relancé.

Voici la procédure complète pour préparer l'image "modèle" finale.

---

1. (Rappel) L'état de la VM modèle
- Le playbook reinitialize_slurm.yml et tout le projet Ansible (ex: galaxyXpand)
sont présents sur le disque (dans /root/galaxyXpand).
- Les services Slurm sont bien arrêtés et désactivés :
```
systemctl disable slurmd.service slurmctld.service
```
2. Créer le service systemd
```
# /etc/systemd/system/ansible-first-boot.service
[Unit]
Description=Configuration Ansible au demarrage (Slurm, Galaxy)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
RemainAfterExit=no

WorkingDirectory=/root/galaxyXpand
ExecStart=/usr/bin/ansible-playbook -i environments/ag2025/hosts reinitialize_slurm.yml

# --- SUPPRIMEZ LES LIGNES SUIVANTES ---
# ExecStartPost=/bin/rm /etc/systemd/system/ansible-first-boot.service
# ExecStartPost=/bin/systemctl daemon-reload

[Install]
WantedBy=multi-user.target
```
3. Activer le service et créer l'image
- **Activer le service** : Sur la VM modèle, activer ce nouveau service pour
qu'il soit lancé au prochain démarrage :
```
systemctl enable ansible-first-boot.service
```
- **Arrêter la VM**
```
shutdown -h now
```
- **Créer l'image**
par exemple avec la commande gcloud.

---

## Le résultat final pour l'étudiant
1. L'étudiant crée sa VM à partir de votre nouvelle image.
- Il démarre la VM.
- Il attend 1 ou 2 minutes (le temps que la VM démarre ET que le playbook s'exécute en arrière-plan).
- Il se connecte à l'URL de son Galaxy.
- Tout fonctionnera sans qu'il n'ait eu à taper la moindre commande.

### La séquence de démarrage sera :

1. VM démarre.
- systemd lance ansible-first-boot.service.
- Le service exécute le playbook reinitialize_slurm.yml.
- Le playbook reconfigure slurm.conf (via le rôle), reconfigure Nginx et redémarre Galaxy.
- Les handlers de Slurm démarrent et activent slurmctld et slurmd (qui sont maintenant valides).
- Le playbook se termine.
- L'étudiant accède à son serveur, qui est 100% opérationnel.
