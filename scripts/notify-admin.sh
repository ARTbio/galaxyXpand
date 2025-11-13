#!/bin/bash
# /usr/local/bin/notify-admin.sh

set -e
# set -x # Gardez-le pour le débogage

echo "En attente du réseau... (10s)"
sleep 10

# --- ⬇️ CONFIGURATION À REMPLIR ⬇️ ---
EVENT_TYPE="$1" # "start" ou "stop"
# !! METTEZ VOTRE NOUVELLE CLÉ API ICI !!
SENDGRID_API_KEY="SG.7......."
ADMIN_EMAIL="christophe.antoniewski@u-paris.fr"
FROM_EMAIL="christophe.antoniewski@sorbonne-universite.fr"
# --- ⬆️ FIN CONFIGURATION ⬆️ ---

echo "Récupération des métadonnées..."
METADATA_URL="http://metadata.google.internal/computeMetadata/v1"
HEADERS="Metadata-Flavor: Google"
VM_NAME=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/name")
VM_IP=$(curl -sf -H "$HEADERS" "$METADATA_URL/instance/network-interfaces/0/access-configs/0/external-ip" || echo "N/A")
PROJECT_ID=$(curl -sf -H "$HEADERS" "$METADATA_URL/project/project-id")

echo "Préparation du message..."
SUBJECT="[Galaxy VM] $VM_NAME ($EVENT_TYPE)"
BODY_TEXT="La VM de l'étudiant est en cours de $EVENT_TYPE.

Projet: $PROJECT_ID
VM: $VM_NAME
IP: $VM_IP
Horodatage: $(date)"

# --- CORRECTION MAJEURE : Construire le JSON de manière sûre ---

# 1. Échapper le corps du texte pour JSON (remplace \ par \\, " par \", et newline par \n)
#    sed -z traite l'entrée comme une seule ligne, \n correspond donc aux vrais sauts de ligne
JSON_BODY=$(echo "$BODY_TEXT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g' | sed -z 's/\n/\\n/g')
# Échapper aussi le sujet
JSON_SUBJECT=$(echo "$SUBJECT" | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')

# 2. Construire la payload JSON avec printf (plus sûr que HereDoc)
JSON_PAYLOAD=$(printf '{
  "personalizations": [{"to": [{"email": "%s"}]}],
  "from": {"email": "%s"},
  "subject": "%s",
  "content": [{"type": "text/plain", "value": "%s"}]
}' "$ADMIN_EMAIL" "$FROM_EMAIL" "$JSON_SUBJECT" "$JSON_BODY")

# --- FIN DE LA CORRECTION ---

echo "Envoi de l'email via SendGrid..."
# J'ai remis --silent (pour moins de bruit) mais gardé --fail
curl --request POST \
  --url https://api.sendgrid.com/v3/mail/send \
  --header "Authorization: Bearer $SENDGRID_API_KEY" \
  --header 'Content-Type: application/json' \
  --data "$JSON_PAYLOAD" \
  --silent --fail

echo "Envoi terminé."

