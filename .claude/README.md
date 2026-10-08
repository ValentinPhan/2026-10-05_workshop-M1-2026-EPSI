# Dossier `.claude/`

Contexte du projet pour **Claude Code**, versionné avec le dépôt pour reprendre le travail sur n'importe quel ordinateur.

| Fichier | Rôle |
|---|---|
| `CLAUDE.md` | chargé automatiquement : résumé, arborescence, démarrage, règles de travail ; importe les trois fichiers ci-dessous |
| `context/projet.md` | sujet du workshop, grilles de notation, équipe, plan de la semaine, idées « signatures » |
| `context/architecture.md` | réseau, flux de données, contrats (WebSocket, API, snapshot), backend, frontend, Raspberry |
| `context/etat-et-decisions.md` | ce qui marche / pas fait, limites, décisions et raisons, prochaines étapes |
| `context/pieges-et-verifications.md` | pièges rencontrés, comment tester (lu à la demande) |
| `commands/reprendre.md` | commande `/reprendre` : fait le point sur le dépôt et propose la suite |

## Reprendre sur un autre ordinateur

1. `git clone https://github.com/ValentinPhan/2026-10-05_workshop-M1-2026-EPSI.git`, puis suivre « Démarrer (nouvel ordinateur) » dans `CLAUDE.md`.
2. Ouvrir le dossier avec Claude Code (CLI, extension VS Code ou application) : `CLAUDE.md` est lu tout seul.
3. Taper `/reprendre`.

La **conversation** elle-même n'est pas transférée : ce dossier en est le résumé durable. Le mettre à jour (surtout `etat-et-decisions.md`) quand quelque chose d'important change.
**Ne jamais y mettre de mot de passe, de jeton ou de clé** (ils vont dans `backend/.env`, ignoré par git). `settings.local.json` (réglages personnels de Claude Code) est ignoré par git.
