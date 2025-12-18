#!/bin/bash
# Attendre que le noeud soit DOWN ou DRAIN, puis le remettre en ligne.

NODE_NAME=$(hostname -s)
MAX_WAIT_TIME=180  # Max 180 secondes (3 minutes)
SLEEP_INTERVAL=10  # Vérifie toutes les 10 secondes

echo "$(date) - Démarrage du check de l'état du noeud $NODE_NAME."

for (( i=0; i<$MAX_WAIT_TIME; i+=$SLEEP_INTERVAL )); do
    # Récupère l'info du noeud
    INFO=$(/usr/bin/scontrol show node $NODE_NAME 2>/dev/null || true)
    
    # La solution la plus robuste et la plus simple : chercher si l'état contient DOWN ou DRAIN.
    # L'opérateur | (OU) fonctionne avec grep -E (Extended Regex).
    if echo "$INFO" | grep -qE 'State=[^ ]*(DOWN|DRAIN)' ; then
        echo "$(date) - État requis (DOWN/DRAIN) détecté. Tentative de RESUME."
        /usr/bin/scontrol update node=$NODE_NAME state=RESUME
        exit 0
    fi

    /bin/sleep $SLEEP_INTERVAL
done

echo "$(date) - Avertissement : $NODE_NAME n'a pas atteint l'état DOWN/DRAIN dans les $MAX_WAIT_TIME secondes."
exit 0
