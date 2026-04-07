"""
Dashboard route - Page d'accueil avec statistiques globales
"""

import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, current_app

dashboard_bp = Blueprint('dashboard', __name__)
PARIS_TZ = ZoneInfo("Europe/Paris")


def _load_json(filepath):
    """Charge un fichier JSON, retourne [] si erreur."""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return []


def _get_stats():
    """Calcule les statistiques globales."""
    offers = _load_json(current_app.config['OFFERS_FILE'])
    applied = _load_json(current_app.config['APPLIED_FILE'])
    
    now = datetime.now(PARIS_TZ)
    today_str = now.strftime('%Y-%m-%d')
    
    # Stats par plateforme
    platform_counts = {}
    for o in offers:
        p = o.get('platform', 'unknown')
        platform_counts[p] = platform_counts.get(p, 0) + 1
    
    # Stats candidatures par statut
    status_counts = {}
    for a in applied:
        s = a.get('status', 'unknown')
        status_counts[s] = status_counts.get(s, 0) + 1
    
    # Offres trouvees aujourd'hui
    today_offers = [o for o in offers if o.get('found_date', '').startswith(today_str)]
    
    # Candidatures aujourd'hui
    today_applied = [a for a in applied if a.get('timestamp', '').startswith(today_str)]
    
    # Offres des 7 derniers jours (pour le graphique)
    daily_offers = {}
    daily_applied = {}
    for i in range(7):
        day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        daily_offers[day] = len([o for o in offers if o.get('found_date', '').startswith(day)])
        daily_applied[day] = len([a for a in applied if a.get('timestamp', '').startswith(day)])
    
    # Dernieres offres (5 plus recentes)
    recent_offers = sorted(offers, key=lambda x: x.get('found_date', ''), reverse=True)[:5]
    
    # Dernieres candidatures (5 plus recentes)
    recent_applied = sorted(applied, key=lambda x: x.get('timestamp', ''), reverse=True)[:5]
    
    return {
        'total_offers': len(offers),
        'total_applied': len(applied),
        'today_offers': len(today_offers),
        'today_applied': len(today_applied),
        'platform_counts': platform_counts,
        'status_counts': status_counts,
        'daily_offers': dict(sorted(daily_offers.items())),
        'daily_applied': dict(sorted(daily_applied.items())),
        'recent_offers': recent_offers,
        'recent_applied': recent_applied,
        'success_count': status_counts.get('success', 0),
        'manual_count': status_counts.get('manual', 0),
        'failed_count': status_counts.get('failed', 0) + status_counts.get('captcha', 0) + status_counts.get('login', 0),
    }


@dashboard_bp.route('/')
def index():
    stats = _get_stats()
    return render_template('dashboard.html', stats=stats)


@dashboard_bp.route('/api/stats')
def api_stats():
    """API endpoint pour rafraichir les stats en AJAX."""
    from flask import jsonify
    stats = _get_stats()
    # Convertir pour JSON (les offres recentes sont deja des dicts)
    return jsonify(stats)
