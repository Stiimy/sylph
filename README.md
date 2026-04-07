# Sylph

![Version](https://img.shields.io/badge/version-1.0-purple)
![License](https://img.shields.io/badge/license-MIT-darkred)
![Python](https://img.shields.io/badge/python-3.11+-3670A0?logo=python&logoColor=ffdd54)
![Selenium](https://img.shields.io/badge/selenium-stealth-43B02A?logo=selenium&logoColor=white)
![Telegram](https://img.shields.io/badge/telegram-bot-26A5E4?logo=telegram&logoColor=white)
![Ollama](https://img.shields.io/badge/ollama-AI-black?logo=ollama&logoColor=white)

Agent automatise de recherche d'alternance en informatique sur **6 plateformes francaises**.

Sylph recherche des offres, filtre les arnaques et les ecoles deguisees, et postule automatiquement sur les plateformes supportees. Les offres non-automatisables sont envoyees sur Telegram pour candidature manuelle.

<p align="center">
  <img src="https://private-user-images.githubusercontent.com/114451424/574584210-afe821c2-868c-4d82-a86d-b46cd09b67cd.jpg?jwt=eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJnaXRodWIuY29tIiwiYXVkIjoicmF3LmdpdGh1YnVzZXJjb250ZW50LmNvbSIsImtleSI6ImtleTUiLCJleHAiOjE3NzU1NTQ4NTMsIm5iZiI6MTc3NTU1NDU1MywicGF0aCI6Ii8xMTQ0NTE0MjQvNTc0NTg0MjEwLWFmZTgyMWMyLTg2OGMtNGQ4Mi1hODZkLWI0NmNkMDliNjdjZC5qcGc_WC1BbXotQWxnb3JpdGhtPUFXUzQtSE1BQy1TSEEyNTYmWC1BbXotQ3JlZGVudGlhbD1BS0lBVkNPRFlMU0E1M1BRSzRaQSUyRjIwMjYwNDA3JTJGdXMtZWFzdC0xJTJGczMlMkZhd3M0X3JlcXVlc3QmWC1BbXotRGF0ZT0yMDI2MDQwN1QwOTM1NTNaJlgtQW16LUV4cGlyZXM9MzAwJlgtQW16LVNpZ25hdHVyZT1hZGI1N2NhY2M5NGUzZjIzMjkzYjE3MzgyNDQwZDZiZDRkOWM4YTZiNjNhNWI1YzIxNDBiYTE4NWI3ZTZjZGY2JlgtQW16LVNpZ25lZEhlYWRlcnM9aG9zdCJ9.o6FOleumRqmyuq1MrMyFESQLU-gOPk06PMg8ICTLeD8" alt="Sylph pfp" />
</p>

---

## Plateformes supportees

| Plateforme | Recherche | Candidature auto |
|---|---|---|
| ![HelloWork](https://img.shields.io/badge/HelloWork-Selenium-FF6B35?style=flat-square) | Scraping | Formulaire auto |
| ![France Travail](https://img.shields.io/badge/France_Travail-API-0055A4?style=flat-square) | API HTTP | Redirection externe |
| ![LinkedIn](https://img.shields.io/badge/LinkedIn-HTTP-0A66C2?style=flat-square&logo=linkedin) | Public search | Notification Telegram |
| ![WTTJ](https://img.shields.io/badge/WTTJ-Algolia-FFCD00?style=flat-square) | API Algolia | ATS externe |
| ![APEC](https://img.shields.io/badge/APEC-API-E30613?style=flat-square) | API POST | Redirection externe |
| ![Indeed](https://img.shields.io/badge/Indeed-Selenium-003A9B?style=flat-square&logo=indeed) | Scraping | Bloque (anti-bot) |

---

## Fonctionnalites

- **Recherche multi-plateforme** — 6 plateformes, ~650 offres par cycle
- **Filtrage intelligent** :
  - Geographique (Ile-de-France)
  - Domaine non-IT (~100 mots-cles non pertinents)
  - Ecoles/centres de formation deguises (blacklist + IA)
  - Anti-arnaque (whitelist, detection WHOIS)
  - Deduplication avant analyse
- **Candidature automatique** :
  - HelloWork : remplissage et soumission de formulaire
  - SuccessFactors / SmartRecruiters : modules ATS
  - Fallback : notification Telegram avec lien
- **Notifications Telegram** — bot interactif avec stats, offres, erreurs
- **Dashboard web** — interface pour suivre offres, candidatures et logs
- **Mode continu** — boucle toutes les heures pendant les heures actives
- **IA locale** — Ollama pour la detection d'ecoles

---

## Prerequis

![Python](https://img.shields.io/badge/Python-3.11+-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54)
![Chrome](https://img.shields.io/badge/Chrome-Driver-4285F4?style=for-the-badge&logo=googlechrome&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)

### Dependances systeme

<details>
<summary><b>Ubuntu / Debian</b></summary>

```bash
# Python 3.11+
sudo apt update
sudo apt install python3 python3-pip python3-venv

# Google Chrome
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update
sudo apt install google-chrome-stable

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
```

</details>

<details>
<summary><b>Arch Linux</b></summary>

```bash
# Python 3.11+
sudo pacman -S python python-pip python-virtualenv

# Google Chrome (AUR)
yay -S google-chrome

# Ollama
sudo pacman -S ollama
ollama pull qwen2.5:3b
```

</details>

> **Note** : ChromeDriver est gere automatiquement par Selenium 4.20+. Un bot Telegram est necessaire — creez-en un via [@BotFather](https://t.me/BotFather).

---

## Installation

```bash
git clone https://github.com/Stiimy/sylph.git
cd sylph

# Environnement virtuel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configuration
cp config.yaml.example config.yaml
# Editez config.yaml avec vos informations

# Creer le dossier de logs
mkdir -p logs
```

## Configuration

Copiez `config.yaml.example` en `config.yaml` et remplissez :

- **profile** : nom, email, telephone, chemin du CV
- **platforms** : identifiants HelloWork, activer/desactiver chaque plateforme
- **telegram** : bot_token et chat_id
- **ai** : URL Ollama et modele

---

## Utilisation

```bash
# Mode continu (recommande) — boucle toutes les heures
python3 agent.py

# Une seule recherche + candidatures
python3 agent.py --once

# Recherche sans postuler
python3 agent.py --search-only

# Importer des cookies depuis votre navigateur
python3 agent.py --import-cookies cookies.txt

# Gerer la quarantaine (offres suspectes)
python3 agent.py --quarantine
```

### Service systemd (optionnel)

```bash
# Adaptez sylph.service.example avec vos chemins
sudo cp sylph.service.example /etc/systemd/system/sylph.service
sudo systemctl enable sylph
sudo systemctl start sylph
```

---

## Architecture

```
sylph/
├── agent.py              # Point d'entree principal, filtres, boucle
├── config.yaml           # Configuration (non versionne)
├── platforms/            # Modules de recherche par plateforme
│   ├── hellowork.py      # Selenium scraping
│   ├── francetravail.py  # API HTTP
│   ├── linkedin.py       # HTTP public search
│   ├── wttj.py           # API Algolia
│   ├── apec.py           # API POST
│   └── indeed.py         # Selenium (bloque par anti-bot)
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
└── logs/                 # Offres, candidatures, logs (non versionne)
```

---

## Licence

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for more details. 

---  
 
## ⚠️ **Disclaimer**  
 
Le bot est encore en phase test donc voila.  
 
---  

$\color{#a3a3a3}{Copyright (c) 2026 Stiimy}$
