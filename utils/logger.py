"""Logger pour l'agent de postulation"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(name: str = "job-agent", log_file: str = None, level: str = "INFO"):
    """Configure le logger.
    
    Evite les doublons: si le logger a deja des handlers, on les supprime d'abord.
    Desactive aussi la propagation vers le logger root pour eviter les logs en double.
    """

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Supprimer les handlers existants pour eviter les doublons
    # (arrive si setup_logger est appele plusieurs fois ou si d'autres modules
    # ont deja configure le logger via logging.getLogger("job-agent"))
    if logger.handlers:
        logger.handlers.clear()

    # Desactiver la propagation vers le root logger (evite les logs en double
    # si le root a aussi un handler, ce que certains modules configurent)
    logger.propagate = False

    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


class ApplicationLogger:
    """Logger avec historique des postulations"""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.applications = []

    def log_application(self, platform: str, offer: dict, status: str):
        """Enregistre une postulation"""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'platform': platform,
            'offer_title': offer.get('title', 'Unknown'),
            'company': offer.get('company', 'Unknown'),
            'status': status,
            'url': offer.get('url', '')
        }
        self.applications.append(entry)
        self.logger.info(f"[{platform}] Postulation: {offer.get('title')} @ {offer.get('company')} - {status}")

    def get_today_applications(self) -> list:
        """Retourne les postulations du jour"""
        today = datetime.now().date()
        return [
            app for app in self.applications
            if datetime.fromisoformat(app['timestamp']).date() == today
        ]

    def get_stats(self) -> dict:
        """Statistiques des postulations"""
        today = self.get_today_applications()
        return {
            'total': len(self.applications),
            'today': len(today),
            'success': len([a for a in self.applications if a['status'] == 'success']),
            'failed': len([a for a in self.applications if a['status'] == 'failed'])
        }