\# Sentinel-X — Infrastructure PostgreSQL \& MQTT



\## 1. Objectif



Ce package permet de préparer et de déployer l'infrastructure serveur du projet \*\*Sentinel-X\*\* à l'aide de Docker Compose.



La partie Infrastructure fournit :



\- un serveur PostgreSQL 17 fonctionnel ;

\- un volume Docker persistant pour les données PostgreSQL ;

\- un réseau Docker `sentinel-net` ;

\- les paramètres nécessaires à la connexion du futur backend au broker MQTT Mosquitto hébergé sur le Raspberry Pi ;

\- une configuration reproductible pouvant être déployée sur le PC serveur final.



La partie Infrastructure \*\*ne crée pas la base de données applicative Sentinel-X\*\*.



La création de la base applicative, des tables, des relations, du modèle de données et des migrations reste à la charge de l'équipe DEV.



\---



\## 2. Architecture générale



```text

ESP8266 / Capteurs

&#x20;       |

&#x20;       | MQTT

&#x20;       v

Raspberry Pi

Mosquitto

10.145.67.225:1883

&#x20;       |

&#x20;       | Réseau

&#x20;       v

PC serveur

&#x20;       |

&#x20;       v

Docker

&#x20;       |

&#x20;       +---------------------+

&#x20;       |                     |

&#x20;       v                     v

Backend DEV              PostgreSQL 17

&#x20;       |                     |

&#x20;       |                     v

&#x20;       +--------------> Base applicative

&#x20;                         créée par les DEV

```



Le Raspberry Pi assure notamment le rôle de \*\*broker MQTT Mosquitto\*\*.



Le futur backend devra récupérer les messages MQTT depuis le Raspberry Pi puis utiliser PostgreSQL pour le stockage des données selon l'architecture définie par l'équipe DEV.



\---



\## 3. Prérequis



La machine serveur doit disposer de :



\- Docker ;

\- Docker Compose ;

\- un accès réseau au Raspberry Pi ;

\- suffisamment d'espace disque pour les données PostgreSQL.



Sous Windows, \*\*Docker Desktop avec WSL 2\*\* peut être utilisé.



Vérification :



```powershell

docker --version

docker compose version

```



\---



\## 4. Contenu du package



Le package transmis contient :



```text

sentinel-x-server/

│

├── compose.yaml

├── .env.example

├── .gitignore

└── README.md

```



\### `compose.yaml`



Contient la définition de l'infrastructure Docker PostgreSQL.



\### `.env.example`



Contient le modèle des variables nécessaires au déploiement.



Il ne contient \*\*aucun véritable mot de passe\*\*.



\### `.env`



Ce fichier doit être créé localement sur le PC serveur.



Il contient les véritables identifiants PostgreSQL et MQTT.



\*\*Le fichier `.env` ne doit jamais être transmis, ajouté dans Git ou intégré au ZIP.\*\*



\### `.gitignore`



Empêche notamment l'ajout accidentel du fichier `.env` dans Git.



\---



\## 5. Création du fichier `.env`



Après avoir extrait le package, ouvrir PowerShell dans le dossier du projet.



Créer le fichier `.env` à partir du modèle :



```powershell

Copy-Item .env.example .env

```



Le fichier `.env.example` contient :



```text

\# PostgreSQL

POSTGRES\_ADMIN\_USER=sentinel\_admin

POSTGRES\_ADMIN\_PASSWORD=CHANGE\_ME



\# MQTT - Raspberry Pi

MQTT\_HOST=10.145.67.225

MQTT\_PORT=1883

MQTT\_USER=sentinelel

MQTT\_PASSWORD=CHANGE\_ME

```



Les valeurs `CHANGE\_ME` doivent être remplacées dans le fichier `.env` local.



\---



\## 6. Configuration PostgreSQL



Dans le fichier `.env`, remplacer :



```text

POSTGRES\_ADMIN\_PASSWORD=CHANGE\_ME

```



par un mot de passe fort.



Le compte :



```text

sentinel\_admin

```



est le compte administrateur PostgreSQL créé lors de la première initialisation du serveur PostgreSQL.



Ce compte permet d'administrer l'instance PostgreSQL.



Il ne représente pas nécessairement le futur compte utilisé par l'application.



La création de la base applicative et des comptes applicatifs reste à la charge de l'équipe DEV.



\---



\## 7. Configuration MQTT



Le broker MQTT Mosquitto est hébergé sur le Raspberry Pi.



La configuration actuelle est :



```text

MQTT\_HOST=10.145.67.225

MQTT\_PORT=1883

MQTT\_USER=sentinelel

MQTT\_PASSWORD=<MOT\_DE\_PASSE\_MQTT>

```



Le véritable mot de passe MQTT doit uniquement être renseigné dans le fichier `.env` local du serveur.



Il ne doit jamais être inscrit :



\- dans `.env.example` ;

\- dans le code source ;

\- dans Git ;

\- dans le README ;

\- dans le ZIP transmis.



Si l'adresse IP du Raspberry Pi change sur le réseau final, la valeur `MQTT\_HOST` devra être adaptée dans le fichier `.env`.



\---



\## 8. Vérifier la configuration Docker



Avant de démarrer l'infrastructure, exécuter :



```powershell

docker compose config --quiet

```



Si aucune erreur n'apparaît, la configuration Docker Compose est syntaxiquement valide.



L'utilisation de `--quiet` évite également d'afficher inutilement les valeurs résolues des variables d'environnement.



\---



\## 9. Démarrer PostgreSQL



Exécuter :



```powershell

docker compose up -d

```



Docker va automatiquement :



1\. télécharger l'image `postgres:17-alpine` si nécessaire ;

2\. créer le réseau Docker `sentinel-net` ;

3\. créer le volume persistant PostgreSQL ;

4\. créer le conteneur `sentinel-postgres` ;

5\. initialiser PostgreSQL ;

6\. créer le compte administrateur défini dans `.env` lors de la première initialisation ;

7\. démarrer PostgreSQL ;

8\. exécuter le contrôle de santé PostgreSQL.



\---



\## 10. Vérifier le fonctionnement de PostgreSQL



Exécuter :



```powershell

docker ps

```



Le conteneur doit apparaître avec un état similaire à :



```text

sentinel-postgres    Up ... (healthy)

```



L'état :



```text

healthy

```



indique que le contrôle de santé PostgreSQL est validé.



Si l'état apparaît temporairement comme :



```text

health: starting

```



attendre quelques secondes puis relancer :



```powershell

docker ps

```



\---



\## 11. Tester la connexion PostgreSQL



Exécuter :



```powershell

docker compose exec postgres psql -U sentinel\_admin -d postgres -c "\\conninfo"

```



Le résultat attendu est similaire à :



```text

You are connected to database "postgres" as user "sentinel\_admin"

```



La base `postgres` utilisée ici est une base de maintenance PostgreSQL.



\*\*Aucune base applicative Sentinel-X n'est créée par l'équipe Infrastructure.\*\*



\---



\## 12. Accès PostgreSQL depuis le futur backend



Si le backend est également déployé dans Docker et connecté au réseau :



```text

sentinel-net

```



il pourra joindre PostgreSQL avec :



```text

Host : postgres

Port : 5432

```



Le port PostgreSQL `5432` n'est volontairement pas publié sur le réseau du PC serveur.



Dans `docker ps`, il peut donc apparaître simplement comme :



```text

5432/tcp

```



et non comme :



```text

0.0.0.0:5432->5432/tcp

```



C'est volontaire.



Cela permet au backend Docker de communiquer avec PostgreSQL sans exposer directement PostgreSQL sur le réseau physique.



\---



\## 13. Réseau Docker



Le réseau utilisé par l'infrastructure est :



```text

sentinel-net

```



Il permettra aux différents conteneurs du projet Sentinel-X de communiquer entre eux.



Architecture prévue :



```text

sentinel-net

│

├── sentinel-postgres

│

└── futur backend DEV

```



Le backend pourra ainsi joindre PostgreSQL via :



```text

postgres:5432

```



Il n'est pas nécessaire de connaître l'adresse IP interne du conteneur PostgreSQL.



Docker assure la résolution du nom du service `postgres`.



\---



\## 14. Connexion MQTT au Raspberry Pi



Le broker Mosquitto est hébergé sur le Raspberry Pi.



Adresse actuelle :



```text

10.145.67.225

```



Port MQTT :



```text

1883

```



Le backend devra récupérer les paramètres MQTT depuis les variables d'environnement :



```text

MQTT\_HOST

MQTT\_PORT

MQTT\_USER

MQTT\_PASSWORD

```



L'adresse, le compte et surtout le mot de passe MQTT ne doivent pas être codés directement dans l'application.



\---



\## 15. Intégration du futur backend Docker



Lorsque l'équipe DEV ajoutera son backend dans Docker Compose, les variables MQTT pourront lui être transmises de cette manière :



```yaml

environment:

&#x20; MQTT\_HOST: ${MQTT\_HOST}

&#x20; MQTT\_PORT: ${MQTT\_PORT}

&#x20; MQTT\_USER: ${MQTT\_USER}

&#x20; MQTT\_PASSWORD: ${MQTT\_PASSWORD}

```



Le backend pourra ensuite utiliser ces variables pour établir la connexion avec Mosquitto.



Le principe est :



```text

Backend Docker

&#x20;     |

&#x20;     | MQTT

&#x20;     v

10.145.67.225:1883

&#x20;     |

&#x20;     v

Raspberry Pi

&#x20;     |

&#x20;     v

Mosquitto

```



Ainsi, aucune modification du code ne devrait être nécessaire simplement pour changer l'adresse ou les identifiants MQTT.



\---



\## 16. Tests réseau MQTT réalisés



Plusieurs tests ont été réalisés afin de valider la communication entre le PC, Docker et le Raspberry Pi.



\### Test PC Windows vers Raspberry Pi



Commande utilisée :



```powershell

Test-NetConnection 10.145.67.225 -Port 1883

```



Résultat validé :



```text

TcpTestSucceeded : True

```



Le PC peut donc joindre Mosquitto sur le port TCP `1883`.



\---



\### Test réseau depuis Docker vers Raspberry Pi



La communication IP entre un conteneur Docker et le Raspberry Pi a été testée avec succès.



Le Raspberry Pi répond depuis un conteneur Docker.



Cela valide le chemin :



```text

Conteneur Docker

&#x20;     |

&#x20;     v

Docker Desktop / réseau hôte

&#x20;     |

&#x20;     v

Réseau Wi-Fi

&#x20;     |

&#x20;     v

Raspberry Pi

```



\---



\### Test du port MQTT depuis Docker



Le port MQTT a été testé depuis un conteneur Docker avec Nmap.



Résultat validé :



```text

1883/tcp open mqtt

```



Cela confirme qu'un conteneur Docker peut atteindre le broker MQTT sur le Raspberry Pi.



\---



\## 17. Vérifications réalisées sur Mosquitto



Le service Mosquitto a été vérifié sur le Raspberry Pi.



Le service est :



```text

active (running)

```



Mosquitto écoute sur :



```text

0.0.0.0:1883

```



Cela signifie que le broker MQTT écoute sur le port `1883` sur les interfaces réseau du Raspberry Pi.



Le port `8883` a également été observé en écoute sur le Raspberry Pi.



\---



\## 18. Test d'authentification MQTT depuis Docker



Une publication MQTT authentifiée a été réalisée depuis un conteneur Docker utilisant le client Mosquitto.



Paramètres du test :



```text

Broker : 10.145.67.225

Port   : 1883

Topic  : sentinel/test

```



Le test de publication s'est terminé sans erreur.



Cela valide le chemin complet :



```text

Conteneur Docker

&#x20;     |

&#x20;     | MQTT authentifié

&#x20;     v

PC / Réseau

&#x20;     |

&#x20;     v

Raspberry Pi

&#x20;     |

&#x20;     v

Mosquitto

```



La communication MQTT entre un conteneur Docker et le Raspberry Pi est donc fonctionnelle.



\---



\## 19. Persistance des données PostgreSQL



Les données PostgreSQL sont stockées dans un volume Docker persistant.



Le volume est déclaré dans `compose.yaml` avec :



```yaml

volumes:

&#x20; postgres\_data:

```



Lors du déploiement de test, Docker a créé un volume correspondant au projet.



La persistance a été testée en arrêtant et en supprimant le conteneur avec :



```powershell

docker compose down

```



Le volume PostgreSQL était toujours présent.



Le service a ensuite été recréé avec :



```powershell

docker compose up -d

```



Après recréation du conteneur, PostgreSQL est revenu dans l'état :



```text

healthy

```



Le volume avait donc bien été conservé.



\---



\## 20. Attention à la suppression des volumes



Ne pas utiliser :



```powershell

docker compose down -v

```



sans savoir exactement pourquoi.



L'option :



```text

\-v

```



demande également la suppression des volumes Docker associés.



Cela peut donc provoquer la suppression des données PostgreSQL.



Pour arrêter normalement l'infrastructure, utiliser :



```powershell

docker compose down

```



\---



\## 21. Arrêter les services



Exécuter :



```powershell

docker compose down

```



Cette commande arrête et supprime les conteneurs de la stack tout en conservant le volume PostgreSQL.



\---



\## 22. Redémarrer les services



Exécuter :



```powershell

docker compose up -d

```



Puis vérifier :



```powershell

docker ps

```



Le conteneur PostgreSQL doit revenir dans l'état :



```text

healthy

```



\---



\## 23. Responsabilités de l'équipe Infrastructure



L'équipe Infrastructure prend en charge :



\- l'installation et le fonctionnement de Docker ;

\- Docker Compose ;

\- le déploiement de PostgreSQL ;

\- le réseau Docker `sentinel-net` ;

\- la persistance des données PostgreSQL ;

\- la disponibilité du service PostgreSQL ;

\- la configuration permettant au backend d'obtenir les paramètres MQTT ;

\- la connectivité réseau entre le PC serveur et le Raspberry Pi ;

\- la sécurisation de l'infrastructure ;

\- la gestion des secrets au niveau du serveur.



\---



\## 24. Responsabilités de l'équipe DEV



L'équipe DEV prend en charge :



\- la création de la base applicative ;

\- la création des tables ;

\- les relations entre les tables ;

\- le modèle de données ;

\- les migrations ;

\- le développement du backend ;

\- la connexion du backend à PostgreSQL ;

\- la consommation des messages MQTT ;

\- l'utilisation des variables d'environnement fournies par l'Infrastructure ;

\- le traitement des messages reçus ;

\- l'enregistrement des données dans PostgreSQL selon les besoins applicatifs.



\---



\## 25. Informations à transmettre à l'équipe DEV



\### PostgreSQL



Lorsque le backend est dans Docker et connecté à `sentinel-net` :



```text

Host : postgres

Port : 5432

```



La base applicative, les comptes applicatifs, les tables et les migrations devront être définis selon les besoins du développement.



\### MQTT



Les variables suivantes sont prévues :



```text

MQTT\_HOST

MQTT\_PORT

MQTT\_USER

MQTT\_PASSWORD

```



Configuration actuelle du broker :



```text

Host : 10.145.67.225

Port : 1883

```



Les identifiants réels sont fournis via le fichier `.env` local du serveur et ne doivent pas être intégrés au code source.



\---



\## 26. Sécurité



Ne jamais :



\- transmettre le fichier `.env` ;

\- ajouter `.env` dans Git ;

\- écrire les mots de passe directement dans `compose.yaml` ;

\- écrire les mots de passe dans le code du backend ;

\- écrire les mots de passe dans le README ;

\- intégrer les secrets dans le ZIP du projet.



Le fichier `.gitignore` doit contenir :



```text

.env

```



Le package distribué doit contenir uniquement :



```text

compose.yaml

.env.example

.gitignore

README.md

```



\---



\## 27. Déploiement sur le PC serveur final



Sur le PC serveur final :



1\. installer Docker et Docker Compose ;

2\. extraire le package `sentinel-x-server` ;

3\. ouvrir un terminal dans le dossier ;

4\. créer `.env` à partir de `.env.example` ;

5\. renseigner les véritables mots de passe PostgreSQL et MQTT ;

6\. vérifier que le PC serveur peut joindre le Raspberry Pi ;

7\. vérifier la configuration Docker Compose ;

8\. démarrer PostgreSQL ;

9\. vérifier que le conteneur est `healthy`.



Commandes principales :



```powershell

Copy-Item .env.example .env

```



Modifier ensuite `.env`, puis :



```powershell

docker compose config --quiet

docker compose up -d

docker ps

```



Pour vérifier l'accès au Raspberry Pi :



```powershell

Test-NetConnection 10.145.67.225 -Port 1883

```



Le résultat attendu est :



```text

TcpTestSucceeded : True

```



\---



\## 28. Point important concernant l'adresse du Raspberry Pi



La configuration actuelle utilise :



```text

MQTT\_HOST=10.145.67.225

```



Cette adresse doit rester joignable depuis le PC serveur.



Si le Raspberry Pi reçoit une autre adresse IP sur le réseau final, il faudra mettre à jour :



```text

MQTT\_HOST

```



dans le fichier `.env` du PC serveur.



L'objectif est que l'application utilise la variable `MQTT\_HOST` et non une adresse IP codée directement dans le backend.



\---



\## 29. Résumé de l'architecture finale



```text

&#x20;            CAPTEURS

&#x20;               |

&#x20;               v

&#x20;         ESP8266 / IoT

&#x20;               |

&#x20;               | MQTT

&#x20;               v

&#x20;      +------------------+

&#x20;      |   Raspberry Pi   |

&#x20;      |                  |

&#x20;      |    Mosquitto     |

&#x20;      |   TCP / 1883     |

&#x20;      +--------+---------+

&#x20;               |

&#x20;               | Réseau

&#x20;               |

&#x20;               v

&#x20;      +--------------------------+

&#x20;      |       PC SERVEUR         |

&#x20;      |                          |

&#x20;      |          Docker          |

&#x20;      |                          |

&#x20;      |   +------------------+   |

&#x20;      |   |   Backend DEV    |   |

&#x20;      |   +--------+---------+   |

&#x20;      |            |             |

&#x20;      |            | PostgreSQL  |

&#x20;      |            v             |

&#x20;      |   +------------------+   |

&#x20;      |   | PostgreSQL 17    |   |

&#x20;      |   | postgres:5432    |   |

&#x20;      |   +------------------+   |

&#x20;      |                          |

&#x20;      |      sentinel-net        |

&#x20;      +--------------------------+

```



Le Raspberry Pi reste principalement chargé de la collecte et du transport MQTT.



Le PC serveur héberge les composants plus lourds, notamment PostgreSQL et le futur backend applicatif.



L'architecture sépare donc clairement :



```text

Collecte / MQTT       → Raspberry Pi

Backend applicatif    → PC serveur / Docker

Base de données       → PC serveur / Docker

```



\---



\## 30. État actuel de validation



Les éléments suivants ont été validés lors de la préparation de l'infrastructure :



```text

Docker Desktop                         OK

Docker Compose                         OK

PostgreSQL 17                          OK

Conteneur sentinel-postgres            OK

Healthcheck PostgreSQL                 OK

Compte PostgreSQL sentinel\_admin       OK

Connexion PostgreSQL                   OK

Volume PostgreSQL persistant           OK

Réseau Docker sentinel-net             OK

PC vers Raspberry Pi                   OK

TCP 1883 vers Mosquitto                OK

Docker vers Raspberry Pi               OK

Docker vers MQTT 1883                  OK

Authentification MQTT depuis Docker    OK

Publication MQTT depuis Docker         OK

```



L'infrastructure est donc prête à être transmise et complétée par l'équipe DEV pour l'intégration du backend et de la base applicative Sentinel-X.

