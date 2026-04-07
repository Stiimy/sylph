"""
Platforms route - Gestion des connexions aux plateformes (cookies, login)
"""

import json
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, jsonify, current_app

platforms_bp = Blueprint('platforms', __name__)
PARIS_TZ = ZoneInfo("Europe/Paris")

# Etat global des sessions de login en cours
_login_sessions = {}
_login_lock = threading.Lock()


def _load_json(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return []


def _load_cookies():
    """Charge les cookies et determine le statut de chaque plateforme."""
    cookies_file = current_app.config['COOKIES_FILE']
    cookies = _load_json(cookies_file)
    
    # Grouper par plateforme
    platform_cookies = {
        'hellowork': {'cookies': [], 'status': 'disconnected', 'count': 0},
        'indeed': {'cookies': [], 'status': 'disconnected', 'count': 0},
        'francetravail': {'cookies': [], 'status': 'disconnected', 'count': 0},
        'linkedin': {'cookies': [], 'status': 'disconnected', 'count': 0},
        'wttj': {'cookies': [], 'status': 'connected', 'count': 0, 'note': 'API publique — pas de login requis'},
        'apec': {'cookies': [], 'status': 'connected', 'count': 0, 'note': 'API publique — pas de login requis'},
    }
    
    domain_map = {
        'hellowork': ['hellowork.com', '.hellowork.com'],
        'indeed': ['indeed.com', '.indeed.com', 'indeed.fr', '.indeed.fr', 'secure.indeed.com'],
        'francetravail': ['francetravail.fr', '.francetravail.fr', 'candidat.francetravail.fr'],
        'linkedin': ['linkedin.com', '.linkedin.com', 'www.linkedin.com'],
    }
    
    now = time.time()
    
    for cookie in cookies:
        domain = cookie.get('domain', '')
        for platform, domains in domain_map.items():
            if any(domain.endswith(d) or domain == d for d in domains):
                platform_cookies[platform]['cookies'].append(cookie)
                platform_cookies[platform]['count'] += 1
                
                # Verifier si les cookies sont expires
                expiry = cookie.get('expiry', cookie.get('expirationDate', 0))
                if expiry and expiry > now:
                    platform_cookies[platform]['status'] = 'connected'
                break
    
    # Verifier dans applied.json les echecs recents de login
    applied = _load_json(current_app.config['APPLIED_FILE'])
    recent_logins = {}
    for a in applied:
        if a.get('status') == 'login':
            p = a.get('platform', '')
            ts = a.get('timestamp', '')
            if p in platform_cookies:
                recent_logins[p] = ts
    
    # Si un login failure recent, marquer comme expired
    for p, ts in recent_logins.items():
        if platform_cookies[p]['status'] == 'connected':
            platform_cookies[p]['status'] = 'expired'
            platform_cookies[p]['note'] = f'Login echoue le {ts[:10]}'
    
    return platform_cookies


PLATFORM_INFO = {
    'hellowork': {
        'name': 'HelloWork',
        'url': 'https://www.hellowork.com/fr-fr/login.html',
        'icon': 'bi-briefcase',
        'color': '#FF6B35',
        'login_url': 'https://www.hellowork.com/fr-fr/login.html',
        'check_url': 'https://www.hellowork.com/fr-fr/mon-compte.html',
    },
    'indeed': {
        'name': 'Indeed',
        'url': 'https://secure.indeed.com/auth',
        'icon': 'bi-search',
        'color': '#2164F3',
        'login_url': 'https://secure.indeed.com/auth',
        'check_url': 'https://www.indeed.fr/mon-indeed',
    },
    'francetravail': {
        'name': 'France Travail',
        'url': 'https://candidat.francetravail.fr/espacepersonnel/',
        'icon': 'bi-building',
        'color': '#003DA5',
        'login_url': 'https://authentification-candidat.francetravail.fr/connexion',
        'check_url': 'https://candidat.francetravail.fr/espacepersonnel/',
    },
    'linkedin': {
        'name': 'LinkedIn',
        'url': 'https://www.linkedin.com/login',
        'icon': 'bi-linkedin',
        'color': '#0077B5',
        'login_url': 'https://www.linkedin.com/login',
        'check_url': 'https://www.linkedin.com/feed/',
        'note': 'Recherche seulement (pas de login necessaire). LinkedIn revoque les sessions depuis un serveur.',
    },
    'wttj': {
        'name': 'Welcome to the Jungle',
        'url': 'https://www.welcometothejungle.com/',
        'icon': 'bi-tree',
        'color': '#FFCD00',
        'login_url': '',
        'check_url': '',
        'note': 'Recherche via API Algolia (pas de login). Candidature manuelle via Telegram.',
    },
    'apec': {
        'name': 'APEC',
        'url': 'https://www.apec.fr/',
        'icon': 'bi-mortarboard',
        'color': '#E30613',
        'login_url': '',
        'check_url': '',
        'note': 'Recherche via API POST (pas de login). Candidature manuelle via Telegram.',
    },
}


@platforms_bp.route('/')
def index():
    """Page de gestion des plateformes."""
    platform_cookies = _load_cookies()
    
    platforms = []
    for key, info in PLATFORM_INFO.items():
        cookie_data = platform_cookies.get(key, {})
        platforms.append({
            'key': key,
            'name': info['name'],
            'icon': info['icon'],
            'color': info['color'],
            'url': info['url'],
            'login_url': info['login_url'],
            'note': info.get('note', cookie_data.get('note', '')),
            'status': cookie_data.get('status', 'disconnected'),
            'cookie_count': cookie_data.get('count', 0),
        })
    
    return render_template('platforms.html', platforms=platforms)


@platforms_bp.route('/api/status')
def api_status():
    """API pour obtenir le statut des plateformes."""
    platform_cookies = _load_cookies()
    result = {}
    for key, info in PLATFORM_INFO.items():
        cookie_data = platform_cookies.get(key, {})
        result[key] = {
            'name': info['name'],
            'status': cookie_data.get('status', 'disconnected'),
            'cookie_count': cookie_data.get('count', 0),
        }
    return jsonify(result)


@platforms_bp.route('/login/<platform>', methods=['POST'])
def start_login(platform):
    """Lance une session de login Selenium en mode visible (non-headless).
    
    Le browser s'ouvre, l'utilisateur se connecte manuellement,
    puis on recupere les cookies automatiquement.
    """
    if platform not in PLATFORM_INFO:
        return jsonify({'error': 'Plateforme inconnue'}), 400
    
    if platform == 'linkedin':
        return jsonify({'error': 'LinkedIn fonctionne sans login (recherche publique)'}), 400
    
    with _login_lock:
        if platform in _login_sessions and _login_sessions[platform].get('active'):
            return jsonify({'error': 'Session de login deja en cours'}), 409
        _login_sessions[platform] = {'active': True, 'status': 'starting', 'message': 'Demarrage du navigateur...'}
    
    # Lancer le login dans un thread separe
    thread = threading.Thread(target=_run_login_session, args=(platform, current_app._get_current_object()))
    thread.daemon = True
    thread.start()
    
    return jsonify({'status': 'started', 'message': f'Session de login {PLATFORM_INFO[platform]["name"]} demarree'})


@platforms_bp.route('/login/<platform>/status')
def login_status(platform):
    """Verifie le statut d'une session de login en cours."""
    with _login_lock:
        session = _login_sessions.get(platform, {'active': False, 'status': 'idle'})
    return jsonify(session)


def _run_login_session(platform, app):
    """Execute la session de login Selenium dans un thread."""
    try:
        with _login_lock:
            _login_sessions[platform] = {'active': True, 'status': 'browser_opening', 'message': 'Ouverture du navigateur...'}
        
        from utils.stealth import StealthBrowser
        
        # Ouvrir en mode VISIBLE (pas headless) pour que l'utilisateur puisse se connecter
        browser = StealthBrowser(headless=False)
        browser.start()
        
        login_url = PLATFORM_INFO[platform]['login_url']
        check_url = PLATFORM_INFO[platform]['check_url']
        
        with _login_lock:
            _login_sessions[platform] = {'active': True, 'status': 'waiting_login', 
                                          'message': f'Navigateur ouvert sur {login_url}. Connectez-vous manuellement...'}
        
        browser.driver.get(login_url)
        
        # Attendre que l'utilisateur se connecte (max 5 min)
        # On verifie periodiquement si l'URL a change vers la page connectee
        max_wait = 300  # 5 minutes
        start_time = time.time()
        logged_in = False
        
        while time.time() - start_time < max_wait:
            time.sleep(3)
            try:
                current_url = browser.driver.current_url
                # Verifier si on est sur une page post-login
                if platform == 'hellowork' and 'mon-compte' in current_url:
                    logged_in = True
                    break
                elif platform == 'indeed' and ('mon-indeed' in current_url or 'myaccess' in current_url):
                    logged_in = True
                    break
                elif platform == 'francetravail' and 'espacepersonnel' in current_url:
                    logged_in = True
                    break
                # Aussi verifier si on est plus sur la page de login
                elif platform == 'hellowork' and 'login' not in current_url and 'hellowork.com' in current_url:
                    logged_in = True
                    break
                elif platform == 'indeed' and 'auth' not in current_url and 'indeed' in current_url:
                    logged_in = True
                    break
            except Exception:
                pass
        
        if logged_in:
            with _login_lock:
                _login_sessions[platform] = {'active': True, 'status': 'saving_cookies', 
                                              'message': 'Login detecte ! Sauvegarde des cookies...'}
            
            # Recuperer tous les cookies du navigateur
            selenium_cookies = browser.driver.get_cookies()
            
            # Sauvegarder dans cookies.json
            with app.app_context():
                cookies_file = app.config['COOKIES_FILE']
                existing_cookies = _load_json_static(cookies_file)
                
                # Supprimer les anciens cookies de cette plateforme
                domains = {
                    'hellowork': 'hellowork.com',
                    'indeed': 'indeed',
                    'francetravail': 'francetravail.fr',
                }
                domain_match = domains.get(platform, '')
                existing_cookies = [c for c in existing_cookies if domain_match not in c.get('domain', '')]
                
                # Ajouter les nouveaux cookies
                existing_cookies.extend(selenium_cookies)
                
                with open(cookies_file, 'w', encoding='utf-8') as f:
                    json.dump(existing_cookies, f, indent=2, ensure_ascii=False)
            
            with _login_lock:
                _login_sessions[platform] = {'active': False, 'status': 'success', 
                                              'message': f'Connecte a {PLATFORM_INFO[platform]["name"]} ! {len(selenium_cookies)} cookies sauvegardes.'}
        else:
            with _login_lock:
                _login_sessions[platform] = {'active': False, 'status': 'timeout', 
                                              'message': 'Timeout : pas de login detecte en 5 minutes.'}
        
        browser.quit()
        
    except Exception as e:
        with _login_lock:
            _login_sessions[platform] = {'active': False, 'status': 'error', 
                                          'message': f'Erreur: {str(e)}'}


def _load_json_static(filepath):
    """Version statique de _load_json (pas besoin de app context)."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return []


@platforms_bp.route('/import-cookies', methods=['POST'])
def import_cookies():
    """Importer des cookies depuis un fichier texte Netscape."""
    if 'cookies_file' not in request.files:
        return jsonify({'error': 'Aucun fichier envoye'}), 400
    
    file = request.files['cookies_file']
    if file.filename == '':
        return jsonify({'error': 'Fichier vide'}), 400
    
    content = file.read().decode('utf-8', errors='ignore')
    cookies = _parse_cookies_txt(content)
    
    if not cookies:
        return jsonify({'error': 'Aucun cookie valide trouve dans le fichier'}), 400
    
    # Sauvegarder
    cookies_file = current_app.config['COOKIES_FILE']
    existing = _load_json(cookies_file)
    existing.extend(cookies)
    
    with open(cookies_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
    
    return jsonify({'status': 'ok', 'message': f'{len(cookies)} cookies importes'})


def _parse_cookies_txt(content):
    """Parse un fichier cookies.txt au format Netscape."""
    cookies = []
    for line in content.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) >= 7:
            try:
                cookie = {
                    'domain': parts[0],
                    'path': parts[2],
                    'secure': parts[3].upper() == 'TRUE',
                    'expiry': int(parts[4]) if parts[4] != '0' else 0,
                    'name': parts[5],
                    'value': parts[6],
                }
                cookies.append(cookie)
            except (ValueError, IndexError):
                continue
    return cookies
