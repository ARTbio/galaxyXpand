#!/bin/bash
# /usr/local/bin/notify-admin.sh

set -e

# --- ⬇️ CONFIGURATION À REMPLIR ⬇️ ---
EVENT_TYPE="$1" # "start" ou "stop"
SENDGRID_API_KEY="VOTRE_CLÉ_API_SENDGRID_COMMENÇANT_PAR_SG...."
ADMIN_EMAIL="christophe.antoniewski@sorbonne-universite.fr"
FROM_EMAIL="christophe.antoniewski@sorbonne-universite.fr"
# --- ⬆️ FIN CONFIGURATION ⬆️ ---

# Récupérer les infos sur la VM depuis le serveur de métadonnées
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
HEADERS="Metadata-Flavor: Google"

# Utiliser -f pour ignorer les erreurs si la VM n'a pas d'IP externe, etc.
VM_NAME=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/name")
VM_IP=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/network-interfaces/0/access-configs/0/external-ip" || echo "N/A")
PROJECT_ID=$(curl -sf -H "$HEADERS" "$METADATA_URL/project/project-id")

# Préparer le message
SUBJECT="[Galaxy VM] $VM_NAME ($EVENT_TYPE)"
BODY_TEXT="La VM de l'étudiant est en cours de $EVENT_TYPE.

Projet: $PROJECT_ID
VM: $VM_NAME
IP: $VM_IP
Horodatage: $(date)"

# Formater pour l'API JSON de SendGrid
read -r -d '' JSON_PAYLOAD << EOM
{
  "personalizations": [{"to": [{"email": "$ADMIN_EMAIL"}]}],
  "from": {"email": "$FROM_EMAIL"},
  "subject": "$SUBJECT",
  "content": [{"type": "text/plain", "value": "$BODY_TEXT"}]
}
EOM

# Envoyer via l'API SendGrid
# Le -s (silent) est important pour ne pas polluer les logs
curl --request POST \
  --url https://api.sendgrid.com/v3/mail/send \
  --header "Authorization: Bearer $SENDGRID_API_KEY" \
  --header 'Content-Type: application/json' \
  --data "$JSON_PAYLOAD" \
  --silent --fail # --fail pour que le script s'arrête en cas d'erreur
