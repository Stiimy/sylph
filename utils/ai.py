"""
Client IA via Ollama pour Sylph.
Utilise l'API HTTP locale d'Ollama (localhost:11434).
Sert pour l'analyse des offres et la generation de lettres de motivation.
"""

import json
import logging
import requests
from typing import Optional

logger = logging.getLogger("job-agent")

# Timeout genereux pour les modeles cloud
DEFAULT_TIMEOUT = 120


class OllamaClient:
    """Client pour l'API Ollama locale"""

    def __init__(self, config: dict):
        self.base_url = config.get('base_url', 'http://localhost:11434')
        self.model = config.get('model', 'minimax-m2.5:cloud')
        self.timeout = config.get('timeout', DEFAULT_TIMEOUT)
        self.temperature = config.get('temperature', 0.3)
        self._available = None

    def is_available(self) -> bool:
        """Verifie si Ollama est accessible"""
        if self._available is not None:
            return self._available
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            self._available = resp.status_code == 200
            if self._available:
                logger.info(f"Ollama connecte ({self.base_url}), modele: {self.model}")
            return self._available
        except Exception as e:
            logger.warning(f"Ollama non disponible: {e}")
            self._available = False
            return False

    def generate(self, prompt: str, system: str = "", temperature: float = None, timeout: int = None) -> Optional[str]:
        """Genere du texte via Ollama.
        
        Args:
            prompt: Le prompt utilisateur
            system: Le prompt systeme (instructions)
            temperature: Temperature de generation (defaut: self.temperature)
            timeout: Timeout en secondes (defaut: self.timeout)
            
        Returns:
            Le texte genere ou None si erreur
        """
        if not self.is_available():
            return None

        temp = temperature if temperature is not None else self.temperature
        req_timeout = timeout if timeout is not None else self.timeout

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {
                "temperature": temp,
            }
        }

        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=req_timeout
            )
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get('response', '').strip()

            if not response_text:
                logger.warning("Ollama a retourne une reponse vide")
                return None

            logger.debug(f"Ollama: {len(response_text)} chars generes")
            return response_text

        except requests.Timeout:
            logger.warning(f"Ollama timeout ({req_timeout}s)")
            return None
        except requests.RequestException as e:
            logger.error(f"Erreur Ollama: {e}")
            return None
        except Exception as e:
            logger.error(f"Erreur inattendue Ollama: {e}")
            return None

    def analyze_json(self, prompt: str, system: str = "", timeout: int = 30) -> Optional[dict]:
        """Genere du JSON structure via Ollama avec timeout court.
        
        Essaie de parser la reponse comme JSON.
        Si le modele retourne du texte avec du JSON dedans, extrait le JSON.
        Timeout par defaut: 30s (rapide, skip si trop lent).
        """
        response = self.generate(prompt, system, temperature=0.1, timeout=timeout)
        if not response:
            return None

        # Essayer de parser directement
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Chercher un bloc JSON dans la reponse
        # Le modele met parfois du texte autour du JSON
        start = response.find('{')
        end = response.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                pass

        # Essayer avec des crochets (array)
        start = response.find('[')
        end = response.rfind(']')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                pass

        logger.warning(f"Impossible de parser le JSON d'Ollama: {response[:200]}")
        return None


def create_ai_client(config: dict) -> Optional[OllamaClient]:
    """Factory function. Retourne None si l'IA est desactivee dans la config."""
    ai_config = config.get('ai', {})
    if not ai_config.get('enabled', False):
        logger.info("IA desactivee dans la config")
        return None

    client = OllamaClient(ai_config)
    if client.is_available():
        return client

    logger.warning("Ollama non disponible, l'IA sera desactivee")
    return None
