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

---
## Récapitulatif détaillé après long travail d'optimisation

**configuration finale**

### Service 1 : Ansible (Au boot/reboot uniquement)
Il s'exécute à chaque démarrage pour s'assurer que Slurm est propre et configuré avec le bon nom d'hôte. Fichier : `/etc/systemd/system/ansible-boot.service` (changement de nom pour plus de clarté)

```
[Unit]
Description=Configuration Ansible au demarrage (Slurm, Galaxy)
Wants=network-online.target
After=network-online.target
Before=slurmctld.service slurmd.service
Conflicts=slurmctld.service slurmd.service

[Service]
Type=oneshot
WorkingDirectory=/root/galaxyXpand
ExecStart=/usr/bin/ansible-playbook -i environments/ag2025/hosts reinitialize_slurm.yml

[Install]
WantedBy=multi-user.target
```
### Service 2 : Notification de Démarrage (Au boot/reboot uniquement)
Il s'exécute à chaque démarrage pour vous envoyer la nouvelle IP. Fichier : `/etc/systemd/system/vm-notify-start.service`
```
[Unit]
Description=Notifier l'administrateur du démarrage de la VM
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/notify-admin.sh start

[Install]
WantedBy=multi-user.target
```
### Service 3 : Notification de Reprise (Au "resume" uniquement)
C'est celui qui résout votre nouveau problème. Il s'exécute uniquement à la reprise pour vous envoyer la nouvelle IP (sans toucher à Slurm). Fichier : `/etc/systemd/system/vm-notify-resume.service`
```
[Unit]
Description=Notifier l'administrateur apres la reprise de la VM
After=suspend.target

[Service]
Type=oneshot
# On réutilise le même script, mais avec un argument "resume"
ExecStart=/usr/local/bin/notify-admin.sh resume
    
[Install]
WantedBy=suspend.target
```

## Avant l'extinction de la machine "Image"

Activer les 3 services:
```
sudo systemctl enable ansible-boot.service
sudo systemctl enable vm-notify-start.service
sudo systemctl enable vm-notify-resume.service
```

---
Checklist finale (avant le shutdown)

Juste avant de créer votre image, votre état final doit être :

Vérifier les services personnalisés :

```bash

systemctl is-enabled ansible-boot.service
systemctl is-enabled vm-notify-start.service
systemctl is-enabled vm-notify-resume.service
```

(Ils doivent tous répondre enabled)

Arrêter et désactiver Slurm :

```bash
sudo systemctl stop slurmctld slurmd
sudo systemctl disable slurmctld.service slurmd.service
```
(Optionnel) Nettoyer les logs :

```bash
sudo journalctl --rotate
sudo journalctl --vacuum-time=1s
history -c && history -w
```

Éteindre :

````
sudo shutdown -h now
```