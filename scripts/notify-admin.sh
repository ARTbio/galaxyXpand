#!/bin/bash
# /usr/local/bin/notify-admin.sh

set -e

# utile en particulier en cas de reprise de VM
echo "En attente du réseau... (10s)"
sleep 10

# --- ⬇️ CONFIGURATION À REMPLIR ⬇️ ---
EVENT_TYPE="$1" # "start" ou "stop"
# !! METTEZ VOTRE NOUVELLE CLÉ API ICI !!
SENDGRID_API_KEY="SG.YOUR_SENDGRID_API_KEY_HERE"
ADMIN_EMAIL="christophe.antoniewski@u-paris.fr"
FROM_EMAIL="christophe.antoniewski@sorbonne-universite.fr"
# --- ⬆️ FIN CONFIGURATION ⬆️ ---

# Gérer l'affichage du sujet de l'email
if [ "$EVENT_TYPE" = "resume" ]; then
    EVENT_TYPE_DISPLAY="resume (start)"
else
    EVENT_TYPE_DISPLAY="$EVENT_TYPE"
fi


METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
HEADERS="Metadata-Flavor: Google"
VM_NAME=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/name")
VM_IP=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/network-interfaces/0/access-configs/0/external-ip" || echo "N/A")
PROJECT_ID=$(curl -sf -H "$HEADERS" "$METADATA_URL/project/project-id")

echo "Préparation du message..."
SUBJECT="[Galaxy VM] $VM_NAME ($EVENT_TYPE_DISPLAY)"
BODY_TEXT="La VM de l'étudiant est opérationnelle.

Evénement: $EVENT_TYPE_DISPLAY
Projet: $PROJECT_ID
VM: $VM_NAME
IP: $VM_IP
Horodatage: $(date)"

# --- Construction JSON sécurisée (pour les sauts de ligne) ---
JSON_BODY=$(echo "$BODY_TEXT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed -z 's/\n/\\n/g')
JSON_SUBJECT=$(echo "$SUBJECT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')

JSON_PAYLOAD=$(printf '{
  "personalizations": [{"to": [{"email": "%s"}]}],
  "from": {"email": "%s"},
  "subject": "%s",
  "content": [{"type": "text/plain", "value": "%s"}]
}' "$ADMIN_EMAIL" "$FROM_EMAIL" "$JSON_SUBJECT" "$JSON_BODY")


# Envoi via SendGrid (silencieux, mais échoue si erreur)
curl --request POST \
  --url https://api.sendgrid.com/v3/mail/send \
  --header "Authorization: Bearer $SENDGRID_API_KEY" \
  --header 'Content-Type: application/json' \
  --data "$JSON_PAYLOAD" \
  --silent --fail
