# ml/ — atelier de l'équipe IA

Expérimentation et entraînement **hors ligne**. Rien ici n'est lancé par le dashboard : ce qui est
retenu est intégré dans `backend/` (voir le README racine).

| Dossier | Contenu | Passage en production |
|---|---|---|
| `vision/` | tests YOLO sur webcam : `webcam_test.py` (FPS, nombre de personnes), `yolo_intrusion.py` (démo d'intrusion avec photo) | **déjà intégré** : `backend/app/vision/` ; les poids sont dans `backend/models/` |
| `environment/` | `env_model.py` : Isolation Forest sur les mesures DHT22 (`train`, `score`, `demo`) | à brancher dans `LocalAnalyzer` (`backend/app/ai/local_analyzer.py`) ; copier `env_model.joblib` dans `backend/models/` |

```bash
# vision
pip install -r ml/vision/requirements.txt
python ml/vision/webcam_test.py

# environnement
pip install -r ml/environment/requirements.txt
python ml/environment/env_model.py demo
```

Les sorties de test (`vision/captures/`, `vision/runs/`) ne sont plus versionnées (voir `.gitignore`).
