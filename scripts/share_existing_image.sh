#!/usr/bin/env bash
# Partage une image Compute Engine EXISTANTE
# et le projet (rôle Viewer) avec une liste d'utilisateurs.
#
# Usage :
#   ./share_existing_image.sh <IMAGE_NAME> <PROJECT_ID> <EMAIL_FILE>
#
# Exemple :
#   ./share_existing_image.sh vm-base-image-20251111 ag2025-25-10-01-1 students.txt

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <IMAGE_NAME> <PROJECT_ID> <EMAIL_FILE>"
  exit 1
fi

IMAGE_NAME="$1"
PROJECT_ID="$2"
EMAIL_FILE="$3"

if [[ ! -f "$EMAIL_FILE" ]]; then
  echo "❌ Fichier d'adresses introuvable : $EMAIL_FILE"
  exit 1
fi

echo "🔎 Vérification de l'existence de l'image '${IMAGE_NAME}' dans le projet '${PROJECT_ID}'..."
if ! gcloud compute images describe "$IMAGE_NAME" --project="$PROJECT_ID" --quiet >/dev/null 2>&1; then
  echo "❌ L'image '${IMAGE_NAME}' n'a pas été trouvée dans le projet '${PROJECT_ID}'."
  exit 1
fi
echo "✅ Image trouvée. Début du partage..."

echo
echo "📤 Partage de l'image '$IMAGE_NAME' et du projet '$PROJECT_ID' avec les adresses de $EMAIL_FILE"
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
echo "🏁 Terminé : partage de l'image = $IMAGE_NAME, projet = $PROJECT_ID"

