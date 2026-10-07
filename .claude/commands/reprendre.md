---
description: Reprendre le travail sur Sentinel-X après un changement d'ordinateur (état du dépôt, ce qui a changé, prochaines étapes)
---

Je reprends le projet Sentinel-X sur un autre ordinateur. Contexte complet : `.claude/CLAUDE.md` et `.claude/context/`.

1. Lis `.claude/context/etat-et-decisions.md` (état, décisions, reste à faire).
2. Fais `git fetch`, `git status -sb` et `git log --oneline -15` ; compare avec `origin/main` et dis-moi ce que mes coéquipiers ont poussé depuis la date du fichier d'état.
3. Vérifie l'environnement **sans rien installer sans me demander** : `node -v`, `npm ls --depth=0`, présence de `backend/.venv` et des paquets (`fastapi`, `sqlalchemy`, `ultralytics`), présence de `backend/.env`, ports 4000 / 5173 libres.
4. Résume en 10 lignes maximum : où on en est, ce qui a changé, ce qui est cassé ou manquant sur cette machine.
5. Propose les 3 prochaines étapes, classées par rapport à l'échéance (soutenance locale le vendredi 9 octobre 2026), et demande laquelle faire.

$ARGUMENTS
