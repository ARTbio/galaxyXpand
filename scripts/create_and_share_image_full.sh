#!/usr/bin/env bash
# Crée une image Compute Engine à partir d'une VM
# et partage cette image + le projet avec une liste d'utilisateurs.
#
# Usage :
#   ./create_and_share_image_full.sh <VM_NAME> <ZONE> <PROJECT_ID> <EMAIL_FILE>
#
# Exemple :
#   ./create_and_share_image_full.sh image-ag2025 europe-west9-b ag2025-25-10-01-1 students.txt

set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "Usage: $0 <VM_NAME> <ZONE> <PROJECT_ID> <EMAIL_FILE>"
  exit 1
fi

VM_NAME="$1"
ZONE="$2"
PROJECT_ID="$3"
EMAIL_FILE="$4"
DATE_TAG=$(date +%Y%m%d)
IMAGE_NAME="${VM_NAME}-image-${DATE_TAG}"

if [[ ! -f "$EMAIL_FILE" ]]; then
  echo "❌ Fichier d'adresses introuvable : $EMAIL_FILE"
  exit 1
fi

echo "⏳ Création de l'image '${IMAGE_NAME}' à partir de la VM '${VM_NAME}'..."
gcloud compute images create "$IMAGE_NAME" \
  --source-disk="$VM_NAME" \
  --source-disk-zone="$ZONE" \
  --project="$PROJECT_ID" \
  --quiet || {
    echo "❌ Échec de la création de l'image"
    exit 1
  }
echo "✅ Image créée : $IMAGE_NAME"

echo
echo "📤 Partage de l'image et du projet avec les adresses de $EMAIL_FILE"
echo "------------------------------------------------------------"

SUCCESS_COUNT=0
FAIL_COUNT=0

while IFS= read -r email; do
  [[ -z "$email" ]] && continue
  echo "→ Traitement : $email"

  # 1. Donne accès à l'image (Compute Image User)
  if gcloud compute images add-iam-policy-binding "$IMAGE_NAME" \
        --project="$PROJECT_ID" \
        --member="user:$email" \
        --role="roles/compute.imageUser" \
        --quiet 2>/tmp/share_errors.log; then
    echo "   🟢 Accès image OK"
  else
    if grep -q "does not exist" /tmp/share_errors.log; then
      echo "   ⚠️  Compte non encore activé (coupon inactif)"
    else
      echo "   ⚠️  Erreur lors de l'ajout du rôle imageUser"
    fi
  fi

  # 2. Donne un rôle Viewer sur le projet (pour visibilité)
  if gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="user:$email" \
        --role="roles/viewer" \
        --quiet >/dev/null 2>&1; then
    echo "   🟢 Rôle Viewer projet OK"
    ((SUCCESS_COUNT++))
  else
    echo "   ⚠️  Impossible d'ajouter le rôle Viewer (peut déjà exister)"
    ((FAIL_COUNT++))
  fi

done < "$EMAIL_FILE"

echo
echo "------------------------------------------------------------"
echo "🎯 Résumé du partage :"
echo "   ✔️  $SUCCESS_COUNT utilisateurs configurés avec succès"
echo "   ⚠️  $FAIL_COUNT erreurs ou comptes inactifs"
echo "------------------------------------------------------------"
echo "🏁 Terminé : image = $IMAGE_NAME, projet = $PROJECT_ID"
