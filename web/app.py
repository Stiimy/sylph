"""
Sylph Web Dashboard - Interface graphique pour l'agent de recherche d'emploi
"""

import sys
import os

# Ajouter le dossier parent au path pour importer les modules de l'agent
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask
from web.routes.dashboard import dashboard_bp
from web.routes.offers import offers_bp
from web.routes.platforms import platforms_bp
from web.routes.agent_ctrl import agent_bp
from web.routes.logs import logs_bp


def create_app():
    app = Flask(__name__,
                template_folder='templates',
                static_folder='static')
    
    app.config['SECRET_KEY'] = 'sylph-dashboard-secret-2026'
    app.config['BASE_DIR'] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app.config['CONFIG_FILE'] = os.path.join(app.config['BASE_DIR'], 'config.yaml')
    app.config['OFFERS_FILE'] = os.path.join(app.config['BASE_DIR'], 'logs', 'offers.json')
    app.config['APPLIED_FILE'] = os.path.join(app.config['BASE_DIR'], 'logs', 'applied.json')
    app.config['COOKIES_FILE'] = os.path.join(app.config['BASE_DIR'], 'logs', 'cookies.json')
    app.config['LOG_FILE'] = os.path.join(app.config['BASE_DIR'], 'logs', 'agent.log')
    app.config['QUARANTINE_FILE'] = os.path.join(app.config['BASE_DIR'], 'logs', 'quarantine.json')
    
    # Enregistrer les blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(offers_bp, url_prefix='/offers')
    app.register_blueprint(platforms_bp, url_prefix='/platforms')
    app.register_blueprint(agent_bp, url_prefix='/agent')
    app.register_blueprint(logs_bp, url_prefix='/logs')
    
    return app


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Sylph Web Dashboard')
    parser.add_argument('--debug', action='store_true', help='Mode debug')
    parser.add_argument('--port', type=int, default=5713, help='Port (default: 5713)')
    args = parser.parse_args()
    
    app = create_app()
    app.run(host='0.0.0.0', port=args.port, debug=args.debug)
