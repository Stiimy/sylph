"""
Logs route - Affichage des logs en temps reel via Server-Sent Events (SSE)
"""

import os
import time
import json
from flask import Blueprint, render_template, Response, current_app, stream_with_context

logs_bp = Blueprint('logs', __name__)


@logs_bp.route('/')
def index():
    """Page des logs en temps reel."""
    return render_template('logs.html')


@logs_bp.route('/stream')
def stream():
    """SSE stream des logs de l'agent."""
    log_file = current_app.config['LOG_FILE']
    
    def generate():
        # Si le fichier n'existe pas, attendre
        while not os.path.exists(log_file):
            yield f"data: {json.dumps({'type': 'info', 'message': 'En attente du fichier de log...'})}\n\n"
            time.sleep(2)
        
        # Lire les 50 dernieres lignes pour le contexte initial
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                last_lines = lines[-50:] if len(lines) > 50 else lines
                for line in last_lines:
                    line = line.strip()
                    if line:
                        level = _detect_level(line)
                        yield f"data: {json.dumps({'type': level, 'message': line})}\n\n"
        except IOError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Impossible de lire le fichier de log'})}\n\n"
            return
        
        yield f"data: {json.dumps({'type': 'separator', 'message': '--- Logs en temps reel ---'})}\n\n"
        
        # Suivre les nouvelles lignes (comme tail -f)
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(0, 2)  # Aller a la fin
            while True:
                line = f.readline()
                if line:
                    line = line.strip()
                    if line:
                        level = _detect_level(line)
                        yield f"data: {json.dumps({'type': level, 'message': line})}\n\n"
                else:
                    time.sleep(1)
                    # Heartbeat pour garder la connexion
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@logs_bp.route('/recent')
def recent():
    """Retourne les 100 dernieres lignes de log."""
    log_file = current_app.config['LOG_FILE']
    
    if not os.path.exists(log_file):
        return json.dumps([]), 200, {'Content-Type': 'application/json'}
    
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-100:] if len(lines) > 100 else lines
            result = []
            for line in last_lines:
                line = line.strip()
                if line:
                    result.append({'type': _detect_level(line), 'message': line})
            return json.dumps(result), 200, {'Content-Type': 'application/json'}
    except IOError:
        return json.dumps([{'type': 'error', 'message': 'Impossible de lire le fichier'}]), 200, {'Content-Type': 'application/json'}


def _detect_level(line):
    """Detecte le niveau de log d'une ligne."""
    line_upper = line.upper()
    if 'ERROR' in line_upper or 'CRITICAL' in line_upper:
        return 'error'
    elif 'WARNING' in line_upper or 'WARN' in line_upper:
        return 'warning'
    elif 'DEBUG' in line_upper:
        return 'debug'
    elif 'INFO' in line_upper:
        return 'info'
    return 'info'
