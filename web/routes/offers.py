"""
Offers route - Liste, filtrage et details des offres d'emploi
"""

import json
import os
from flask import Blueprint, render_template, request, jsonify, current_app

offers_bp = Blueprint('offers', __name__)


def _load_json(filepath):
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return []


@offers_bp.route('/')
def list_offers():
    """Page principale des offres avec filtres."""
    offers = _load_json(current_app.config['OFFERS_FILE'])
    applied = _load_json(current_app.config['APPLIED_FILE'])
    
    # Index des URLs deja appliquees
    applied_urls = {a.get('url'): a for a in applied}
    
    # Ajouter le statut de candidature a chaque offre
    for offer in offers:
        url = offer.get('url', '')
        if url in applied_urls:
            offer['apply_status'] = applied_urls[url].get('status', 'unknown')
            offer['apply_details'] = applied_urls[url].get('details', '')
        else:
            offer['apply_status'] = 'pending'
            offer['apply_details'] = ''
    
    # Filtres depuis les query params
    platform_filter = request.args.get('platform', '')
    status_filter = request.args.get('status', '')
    search_filter = request.args.get('q', '')
    
    if platform_filter:
        offers = [o for o in offers if o.get('platform') == platform_filter]
    if status_filter:
        offers = [o for o in offers if o.get('apply_status') == status_filter]
    if search_filter:
        q = search_filter.lower()
        offers = [o for o in offers if q in o.get('title', '').lower() 
                  or q in o.get('company', '').lower()
                  or q in o.get('description', '').lower()]
    
    # Trier par date de decouverte (plus recent d'abord)
    offers.sort(key=lambda x: x.get('found_date', ''), reverse=True)
    
    # Pagination
    page = request.args.get('page', 1, type=int)
    per_page = 25
    total = len(offers)
    start = (page - 1) * per_page
    end = start + per_page
    paginated = offers[start:end]
    total_pages = (total + per_page - 1) // per_page
    
    # Plateformes uniques pour le filtre
    all_offers = _load_json(current_app.config['OFFERS_FILE'])
    platforms = sorted(set(o.get('platform', '') for o in all_offers))
    
    return render_template('offers.html',
                           offers=paginated,
                           page=page,
                           total_pages=total_pages,
                           total=total,
                           platforms=platforms,
                           platform_filter=platform_filter,
                           status_filter=status_filter,
                           search_filter=search_filter)


@offers_bp.route('/detail/<int:index>')
def offer_detail(index):
    """Detail d'une offre specifique."""
    offers = _load_json(current_app.config['OFFERS_FILE'])
    applied = _load_json(current_app.config['APPLIED_FILE'])
    
    if index < 0 or index >= len(offers):
        return "Offre non trouvee", 404
    
    offer = offers[index]
    applied_urls = {a.get('url'): a for a in applied}
    url = offer.get('url', '')
    application = applied_urls.get(url, None)
    
    return render_template('offer_detail.html', offer=offer, application=application, index=index)


@offers_bp.route('/api/list')
def api_list():
    """API JSON pour les offres (pour AJAX)."""
    offers = _load_json(current_app.config['OFFERS_FILE'])
    applied = _load_json(current_app.config['APPLIED_FILE'])
    applied_urls = {a.get('url'): a for a in applied}
    
    for offer in offers:
        url = offer.get('url', '')
        if url in applied_urls:
            offer['apply_status'] = applied_urls[url].get('status', 'unknown')
        else:
            offer['apply_status'] = 'pending'
    
    offers.sort(key=lambda x: x.get('found_date', ''), reverse=True)
    return jsonify(offers[:100])
