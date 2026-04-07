"""
Agent control route - Start/stop agent, edit config, run manual searches
"""

import json
import os
import subprocess
import threading
import yaml
from flask import Blueprint, render_template, request, jsonify, current_app

agent_bp = Blueprint('agent', __name__)

# Etat de l'agent (process en cours)
_agent_process = None
_agent_lock = threading.Lock()


def _load_config():
    """Charge la config YAML."""
    config_file = current_app.config['CONFIG_FILE']
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except (yaml.YAMLError, IOError) as e:
        return {'error': str(e)}


def _save_config(config):
    """Sauvegarde la config YAML."""
    config_file = current_app.config['CONFIG_FILE']
    with open(config_file, 'w', encoding='utf-8') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _get_service_status():
    """Verifie le statut du service systemd job-agent."""
    try:
        result = subprocess.run(
            ['systemctl', '--user', 'is-active', 'job-agent'],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        if status == 'active':
            return 'running'
        elif status == 'inactive':
            return 'stopped'
        elif status == 'failed':
            return 'failed'
        else:
            # Essayer sans --user (service systeme)
            result2 = subprocess.run(
                ['systemctl', 'is-active', 'job-agent'],
                capture_output=True, text=True, timeout=5
            )
            status2 = result2.stdout.strip()
            if status2 == 'active':
                return 'running'
            return status2 or 'unknown'
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 'unknown'


def _get_service_info():
    """Obtient les infos detaillees du service."""
    try:
        result = subprocess.run(
            ['systemctl', 'status', 'job-agent'],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 'Impossible de lire le statut du service'


@agent_bp.route('/')
def index():
    """Page de controle de l'agent."""
    config = _load_config()
    service_status = _get_service_status()
    service_info = _get_service_info()
    
    # Lire le config.yaml brut pour l'editeur
    config_file = current_app.config['CONFIG_FILE']
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config_raw = f.read()
    except IOError:
        config_raw = ''
    
    return render_template('agent.html',
                           config=config,
                           config_raw=config_raw,
                           service_status=service_status,
                           service_info=service_info)


@agent_bp.route('/api/status')
def api_status():
    """API pour le statut de l'agent."""
    return jsonify({
        'service_status': _get_service_status(),
    })


@agent_bp.route('/config', methods=['POST'])
def save_config():
    """Sauvegarder la config YAML depuis l'editeur web."""
    raw_yaml = request.form.get('config_yaml', '')
    
    if not raw_yaml.strip():
        return jsonify({'error': 'Config vide'}), 400
    
    try:
        # Valider le YAML
        config = yaml.safe_load(raw_yaml)
        if not isinstance(config, dict):
            return jsonify({'error': 'Le YAML doit etre un dictionnaire'}), 400
        
        # Verifier les champs critiques
        required = ['search', 'profile', 'platforms', 'telegram']
        missing = [r for r in required if r not in config]
        if missing:
            return jsonify({'error': f'Sections manquantes: {", ".join(missing)}'}), 400
        
        # Sauvegarder
        config_file = current_app.config['CONFIG_FILE']
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(raw_yaml)
        
        return jsonify({'status': 'ok', 'message': 'Configuration sauvegardee'})
    except yaml.YAMLError as e:
        return jsonify({'error': f'YAML invalide: {str(e)}'}), 400


@agent_bp.route('/run-search', methods=['POST'])
def run_search():
    """Lance une recherche manuelle (--search-only)."""
    global _agent_process
    
    with _agent_lock:
        if _agent_process and _agent_process.poll() is None:
            return jsonify({'error': 'Une recherche est deja en cours'}), 409
    
    base_dir = current_app.config['BASE_DIR']
    agent_script = os.path.join(base_dir, 'agent.py')
    
    try:
        _agent_process = subprocess.Popen(
            ['python3', agent_script, '--search-only'],
            cwd=base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return jsonify({'status': 'started', 'pid': _agent_process.pid,
                        'message': 'Recherche lancee (--search-only)'})
    except Exception as e:
        return jsonify({'error': f'Impossible de lancer la recherche: {str(e)}'}), 500


@agent_bp.route('/run-once', methods=['POST'])
def run_once():
    """Lance un cycle complet (--once)."""
    global _agent_process
    
    with _agent_lock:
        if _agent_process and _agent_process.poll() is None:
            return jsonify({'error': 'Un cycle est deja en cours'}), 409
    
    base_dir = current_app.config['BASE_DIR']
    agent_script = os.path.join(base_dir, 'agent.py')
    
    try:
        _agent_process = subprocess.Popen(
            ['python3', agent_script, '--once'],
            cwd=base_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return jsonify({'status': 'started', 'pid': _agent_process.pid,
                        'message': 'Cycle complet lance (--once)'})
    except Exception as e:
        return jsonify({'error': f'Impossible de lancer le cycle: {str(e)}'}), 500


@agent_bp.route('/process-status')
def process_status():
    """Verifie si un process agent est en cours."""
    global _agent_process
    
    if _agent_process is None:
        return jsonify({'running': False})
    
    poll = _agent_process.poll()
    if poll is None:
        return jsonify({'running': True, 'pid': _agent_process.pid})
    else:
        # Process termine
        stdout = _agent_process.stdout.read().decode('utf-8', errors='ignore') if _agent_process.stdout else ''
        stderr = _agent_process.stderr.read().decode('utf-8', errors='ignore') if _agent_process.stderr else ''
        result = {
            'running': False,
            'exit_code': poll,
            'stdout': stdout[-2000:],  # Dernieres 2000 chars
            'stderr': stderr[-2000:],
        }
        _agent_process = None
        return jsonify(result)
