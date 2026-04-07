# Sylph

Agent automatisé de recherche d'alternance en informatique sur 6 plateformes françaises.

Sylph recherche des offres, filtre les arnaques et les écoles déguisées, et postule automatiquement sur les plateformes supportées. Les offres non-automatisables sont envoyées sur Telegram pour candidature manuelle.

## Plateformes supportées

| Plateforme | Recherche | Candidature auto |
|---|---|---|
| HelloWork | Selenium scraping | Formulaire auto |
| France Travail | API HTTP | Redirection externe |
| LinkedIn | HTTP public search | Notification Telegram |
| Welcome to the Jungle | API Algolia | ATS externe / SuccessFactors |
| APEC | API POST | Redirection externe |
| Indeed | Selenium | Bloqué (anti-bot) |

## Fonctionnalités

- **Recherche multi-plateforme** : 6 plateformes, ~650 offres par cycle
- **Filtrage intelligent** :
  - Géographique (Île-de-France)
  - Domaine non-IT (détecte ~100 mots-clés non pertinents)
  - Écoles/centres de formation déguisés en recruteurs (blacklist + IA)
  - Anti-arnaque (whitelist de domaines, détection WHOIS)
  - Déduplication avant analyse
- **Candidature automatique** :
  - HelloWork : remplissage et soumission de formulaire
  - SuccessFactors / SmartRecruiters : modules ATS
  - Fallback : notification Telegram avec lien pour postuler manuellement
- **Notifications Telegram** : bot interactif avec stats, offres LinkedIn, erreurs
- **Dashboard web** : interface pour suivre les offres, candidatures et logs
- **Mode continu** : tourne en boucle toutes les heures pendant les heures actives
- **IA locale** : Ollama (qwen2.5:3b) pour la détection d'écoles

## Prérequis

- Python 3.11+
- Google Chrome / Chromium + ChromeDriver
- [Ollama](https://ollama.ai) avec un modèle (ex: `qwen2.5:3b`)
- Un bot Telegram (créé via [@BotFather](https://t.me/BotFather))

## Installation

```bash
git clone https://github.com/VOTRE_USER/sylph.git
cd sylph

# Environnement virtuel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp config.yaml.example config.yaml
# Editez config.yaml avec vos informations

# Créer le dossier de logs
mkdir -p logs

# Installer Ollama et télécharger le modèle
ollama pull qwen2.5:3b
```

## Configuration

Copiez `config.yaml.example` en `config.yaml` et remplissez :

- **profile** : nom, email, téléphone, chemin du CV
- **platforms** : identifiants HelloWork, activer/désactiver chaque plateforme
- **telegram** : bot_token et chat_id
- **ai** : URL Ollama et modèle

## Utilisation

```bash
# Mode continu (recommandé) — boucle toutes les heures
python3 agent.py

# Une seule recherche + candidatures
python3 agent.py --once

# Recherche sans postuler
python3 agent.py --search-only

# Importer des cookies depuis votre navigateur
python3 agent.py --import-cookies cookies.txt

# Gérer la quarantaine (offres suspectes)
python3 agent.py --quarantine
```

### Service systemd (optionnel)

```bash
# Adaptez sylph.service.example avec vos chemins
sudo cp sylph.service.example /etc/systemd/system/sylph.service
sudo systemctl enable sylph
sudo systemctl start sylph
```

## Architecture

```
sylph/
├── agent.py              # Point d'entrée principal, filtres, boucle
├── config.yaml           # Configuration (non versionné)
├── platforms/            # Modules de recherche par plateforme
│   ├── hellowork.py      # Selenium scraping
│   ├── francetravail.py  # API HTTP
│   ├── linkedin.py       # HTTP public search
│   ├── wttj.py           # API Algolia
│   ├── apec.py           # API POST
│   └── indeed.py         # Selenium (bloqué par anti-bot)
├── apply/                # Modules de candidature
│   ├── hellowork.py      # Formulaire auto HelloWork
│   ├── wttj.py           # ATS auto / fallback externe
│   ├── external_ats.py   # Dispatcher ATS
│   ├── ats/
│   │   ├── successfactors.py
│   │   └── smartrecruiters.py
│   └── ...
├── filters/
│   ├── ai_analyzer.py    # Analyse IA (Ollama)
│   └── scam_detector.py  # Anti-arnaque + quarantaine
├── utils/
│   ├── telegram.py       # Notifications + bot interactif
│   ├── stealth.py        # Navigateur Selenium stealth
│   ├── ai.py             # Client Ollama
│   ├── requester.py      # Client HTTP
│   └── logger.py         # Configuration logging
├── web/                  # Dashboard web
│   ├── app.py
│   ├── routes/
│   ├── templates/
│   └── static/
└── logs/                 # Offres, candidatures, logs (non versionné)
```

## Licence

MIT
