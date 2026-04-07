"""
Module de notification + bot interactif Telegram pour Sylph Job Agent.

- TelegramNotifier: envoi de messages (notifications candidatures, erreurs, recaps)
- TelegramBot: bot interactif avec IA (repond aux messages, commandes, stats)

Le bot tourne dans un thread separe et utilise le long polling Telegram.
"""

import json
import logging
import os
import threading
import time
import requests
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger("job-agent")

TELEGRAM_API = "https://api.telegram.org/bot{token}"
PARIS_TZ = ZoneInfo("Europe/Paris")

# Fichiers de donnees (pour les stats)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFERS_FILE = os.path.join(_BASE_DIR, "logs", "offers.json")
APPLIED_FILE = os.path.join(_BASE_DIR, "logs", "applied.json")


class TelegramNotifier:
    """Envoie des notifications Telegram"""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = TELEGRAM_API.format(token=token)
        self._verified = False

    def verify(self) -> bool:
        """Verifie que le bot est fonctionnel"""
        try:
            resp = requests.get(f"{self.base_url}/getMe", timeout=10)
            data = resp.json()
            if data.get("ok"):
                bot_name = data["result"].get("username", "inconnu")
                logger.info(f"Telegram: bot @{bot_name} connecte")
                self._verified = True
                return True
            else:
                logger.error(f"Telegram: bot invalide - {data}")
                return False
        except Exception as e:
            logger.error(f"Telegram: erreur verification - {e}")
            return False

    def send(self, message: str, parse_mode: str = "HTML") -> bool:
        """Envoie un message Telegram"""
        # Telegram limite a 4096 chars par message
        if len(message) > 4000:
            message = message[:4000] + "\n\n[... tronque]"
        try:
            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            data = resp.json()
            if data.get("ok"):
                return True
            else:
                logger.error(f"Telegram: envoi echoue - {data}")
                return False
        except Exception as e:
            logger.error(f"Telegram: erreur envoi - {e}")
            return False

    def notify_application(self, offer: dict, success: bool, details: str = "",
                           ai_summary: str = ""):
        """Notifie d'une candidature envoyee ou echouee"""
        status = "POSTULE" if success else "ECHEC"
        emoji = "+" if success else "x"

        title = offer.get('title', 'Sans titre')
        company = offer.get('company', 'Inconnue')
        platform = offer.get('platform', '?')
        url = offer.get('url', '')
        location = offer.get('location', '')

        msg = (
            f"[{emoji}] <b>{status}</b>\n\n"
            f"<b>{title}</b>\n"
            f"Entreprise: {company}\n"
            f"Plateforme: {platform}\n"
        )
        if location:
            msg += f"Lieu: {location}\n"
        msg += f"URL: {url}\n"

        # Resume IA de l'offre
        if ai_summary:
            msg += f"\n<b>Analyse IA:</b> {ai_summary}\n"

        if details:
            msg += f"\nDetails: {details}\n"
        msg += f"\n{datetime.now(PARIS_TZ).strftime('%d/%m/%Y %H:%M')}"

        self.send(msg)

    def notify_summary(self, total_found: int, applied: int, failed: int, blocked: int,
                       ai_filtered: int = 0):
        """Envoie un resume de la session de recherche"""
        msg = (
            f"<b>RESUME SYLPH</b>\n\n"
            f"Offres trouvees: {total_found}\n"
            f"Candidatures envoyees: {applied}\n"
            f"Candidatures echouees: {failed}\n"
            f"Offres bloquees (scam): {blocked}\n"
        )
        if ai_filtered:
            msg += f"Filtrees par IA (ecoles): {ai_filtered}\n"
        msg += f"\n{datetime.now(PARIS_TZ).strftime('%d/%m/%Y %H:%M')}"
        self.send(msg)

    def notify_error(self, error_msg: str):
        """Notifie d'une erreur critique"""
        msg = (
            f"[!] <b>ERREUR SYLPH</b>\n\n"
            f"{error_msg}\n\n"
            f"{datetime.now(PARIS_TZ).strftime('%d/%m/%Y %H:%M')}"
        )
        self.send(msg)


# ==================================================================
# BOT INTERACTIF - Ecoute les messages et repond via IA
# ==================================================================

BOT_SYSTEM_PROMPT = """Tu es Sylph, un assistant personnel Telegram.
Tu es un agent de recherche d'alternance informatique a Paris.

TON ROLE:
- Repondre aux questions sur les candidatures et offres
- Donner les stats quand on te demande
- Etre sympa, direct et en francais
- Repondre de maniere courte (Telegram = messages courts)
- Tu tutoies l'utilisateur

CONTEXTE ACTUEL:
{context}

REGLES:
- Reponds en francais, max 300 mots
- Sois direct et concis
- Pas de blabla corporate
- Si tu ne sais pas, dis-le
- Ne formate PAS en markdown, utilise du texte brut (Telegram n'aime pas le markdown)"""


class TelegramBot:
    """Bot Telegram interactif avec IA via Ollama"""

    def __init__(self, token: str, chat_id: str, ai_client=None):
        self.token = token
        self.chat_id = str(chat_id)
        self.base_url = TELEGRAM_API.format(token=token)
        self.ai_client = ai_client
        self._running = False
        self._thread = None
        self._last_update_id = 0

    def start(self):
        """Demarre le bot dans un thread separe"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("Telegram Bot: demarre (thread daemon)")

    def stop(self):
        """Arrete le bot"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Telegram Bot: arrete")

    def _poll_loop(self):
        """Boucle de long polling Telegram avec backoff exponentiel sur erreurs"""
        logger.info("Telegram Bot: boucle de polling demarree")

        # Flush les anciens messages au demarrage
        self._flush_old_updates()

        consecutive_errors = 0
        MAX_BACKOFF = 300  # 5 minutes max entre les retries

        while self._running:
            try:
                updates = self._get_updates(timeout=30)
                if updates is None:
                    # _get_updates retourne None en cas d'erreur reseau
                    consecutive_errors += 1
                    backoff = min(5 * (2 ** (consecutive_errors - 1)), MAX_BACKOFF)
                    logger.warning(
                        f"Telegram Bot: erreur reseau ({consecutive_errors}x), "
                        f"retry dans {backoff}s"
                    )
                    time.sleep(backoff)
                    continue

                # Succes — reset le compteur d'erreurs
                consecutive_errors = 0
                for update in updates:
                    self._handle_update(update)
            except Exception as e:
                consecutive_errors += 1
                backoff = min(5 * (2 ** (consecutive_errors - 1)), MAX_BACKOFF)
                logger.error(
                    f"Telegram Bot: erreur polling ({consecutive_errors}x): {e}, "
                    f"retry dans {backoff}s"
                )
                time.sleep(backoff)

    def _flush_old_updates(self):
        """Vide les messages accumules pendant que le bot etait offline"""
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": -1, "limit": 1, "timeout": 0},
                timeout=10
            )
            data = resp.json()
            if data.get("ok") and data.get("result"):
                last = data["result"][-1]
                self._last_update_id = last["update_id"] + 1
                logger.debug(f"Telegram Bot: flush {last['update_id']} anciens messages")
        except Exception as e:
            logger.debug(f"Telegram Bot: erreur flush: {e}")

    def _get_updates(self, timeout: int = 30) -> list | None:
        """Recupere les nouveaux messages via long polling.
        
        Retourne:
            list — messages recus (peut etre vide)
            None — erreur reseau (le caller doit faire un backoff)
        """
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset": self._last_update_id,
                    "timeout": timeout,
                    "allowed_updates": '["message"]'
                },
                timeout=timeout + 10
            )
            data = resp.json()
            if data.get("ok"):
                updates = data.get("result", [])
                if updates:
                    self._last_update_id = updates[-1]["update_id"] + 1
                return updates
        except requests.Timeout:
            pass  # Normal pour le long polling
        except Exception as e:
            # Erreur reseau (DNS, connexion, etc.) — retourner None pour backoff
            logger.debug(f"Telegram Bot: erreur getUpdates: {e}")
            return None
        return []

    def _handle_update(self, update: dict):
        """Traite un message recu"""
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "").strip()

        # Securite: ne repondre qu'a Stiimy
        if chat_id != self.chat_id:
            logger.warning(f"Telegram Bot: message ignore de chat_id {chat_id}")
            return

        if not text:
            return

        logger.info(f"Telegram Bot: message recu: '{text}'")

        # Traiter le message
        response = self._process_message(text)

        # Envoyer la reponse
        self._send_reply(response)

    def _process_message(self, text: str) -> str:
        """Traite un message et genere une reponse"""
        text_lower = text.lower().strip()

        # Commandes rapides (pas besoin d'IA)
        if text_lower in ('/status', 'status', 'statut'):
            return self._cmd_status()
        elif text_lower in ('/stats', 'stats', 'statistiques'):
            return self._cmd_stats()
        elif text_lower in ('/help', 'aide', 'help'):
            return self._cmd_help()
        elif text_lower in ('/offres', 'offres', 'dernieres offres'):
            return self._cmd_recent_offers()

        # Tout le reste passe par l'IA
        if self.ai_client:
            return self._ai_response(text)
        else:
            return (
                "L'IA n'est pas disponible pour l'instant.\n\n"
                "Commandes dispo:\n"
                "/status - Etat de l'agent\n"
                "/stats - Statistiques\n"
                "/offres - Dernieres offres\n"
                "/help - Aide"
            )

    def _ai_response(self, user_message: str) -> str:
        """Genere une reponse IA en fonction du contexte"""
        # Construire le contexte
        context = self._build_context()

        system = BOT_SYSTEM_PROMPT.format(context=context)
        prompt = f"Message de Stiimy: {user_message}"

        response = self.ai_client.generate(prompt, system=system, temperature=0.5)

        if response:
            return response
        else:
            return "Desolee, j'ai pas reussi a generer une reponse. Ollama est peut-etre down."

    def _build_context(self) -> str:
        """Construit le contexte actuel pour l'IA"""
        parts = []
        now = datetime.now(PARIS_TZ)
        parts.append(f"Date/heure: {now.strftime('%d/%m/%Y %H:%M')} (Paris)")

        # Stats offres
        try:
            offers_path = Path(OFFERS_FILE)
            if offers_path.exists():
                with open(offers_path) as f:
                    offers = json.load(f)
                parts.append(f"Total offres en base: {len(offers)}")

                # Offres du jour
                today_str = now.strftime('%Y-%m-%d')
                today_offers = [o for o in offers if o.get('found_date', '').startswith(today_str)]
                parts.append(f"Offres trouvees aujourd'hui: {len(today_offers)}")

                # 3 dernieres offres
                recent = offers[-3:]
                if recent:
                    parts.append("3 dernieres offres:")
                    for o in reversed(recent):
                        parts.append(f"  - {o.get('title', '?')} @ {o.get('company', '?')} ({o.get('platform', '?')})")
        except Exception:
            pass

        # Stats candidatures
        try:
            applied_path = Path(APPLIED_FILE)
            if applied_path.exists():
                with open(applied_path) as f:
                    applied = json.load(f)
                total = len(applied)
                successes = sum(1 for a in applied if a.get('status') == 'success')
                failures = sum(1 for a in applied if a.get('status') in ('failed', 'captcha'))
                externals = sum(1 for a in applied if a.get('status') == 'external')
                parts.append(f"\nCandidatures total: {total} (succes: {successes}, echec: {failures}, externe: {externals})")

                # Candidatures du jour
                today_str = now.strftime('%Y-%m-%d')
                today_applied = [a for a in applied if a.get('timestamp', '').startswith(today_str)]
                today_success = sum(1 for a in today_applied if a.get('status') == 'success')
                parts.append(f"Candidatures aujourd'hui: {len(today_applied)} (succes: {today_success})")

                # Dernieres candidatures
                recent_apps = [a for a in applied if a.get('status') == 'success'][-3:]
                if recent_apps:
                    parts.append("Dernieres candidatures reussies:")
                    for a in reversed(recent_apps):
                        parts.append(f"  - {a.get('offer_title', '?')} @ {a.get('company', '?')}")
        except Exception:
            pass

        return "\n".join(parts)

    # ============================================================
    # COMMANDES RAPIDES
    # ============================================================

    def _cmd_status(self) -> str:
        """Commande /status"""
        now = datetime.now(PARIS_TZ)
        hour = now.hour

        if 8 <= hour < 17:
            status = "EN COURS (8h-16h30)"
        else:
            status = "EN PAUSE (hors horaires)"

        context = self._build_context()
        return f"SYLPH - {status}\n\n{context}"

    def _cmd_stats(self) -> str:
        """Commande /stats"""
        now = datetime.now(PARIS_TZ)
        parts = [f"STATISTIQUES SYLPH - {now.strftime('%d/%m/%Y %H:%M')}\n"]

        try:
            # Offres
            offers_path = Path(OFFERS_FILE)
            if offers_path.exists():
                with open(offers_path) as f:
                    offers = json.load(f)
                parts.append(f"Offres en base: {len(offers)}")

                # Par plateforme
                platforms = {}
                for o in offers:
                    p = o.get('platform', 'autre')
                    platforms[p] = platforms.get(p, 0) + 1
                for p, count in sorted(platforms.items()):
                    parts.append(f"  {p}: {count}")

            # Candidatures
            applied_path = Path(APPLIED_FILE)
            if applied_path.exists():
                with open(applied_path) as f:
                    applied = json.load(f)

                parts.append(f"\nCandidatures totales: {len(applied)}")
                statuses = {}
                for a in applied:
                    s = a.get('status', 'unknown')
                    statuses[s] = statuses.get(s, 0) + 1
                for s, count in sorted(statuses.items()):
                    parts.append(f"  {s}: {count}")

                # Aujourd'hui
                today_str = now.strftime('%Y-%m-%d')
                today = [a for a in applied if a.get('timestamp', '').startswith(today_str)]
                if today:
                    parts.append(f"\nAujourd'hui: {len(today)} candidatures")
                    for a in today:
                        status = a.get('status', '?')
                        title = a.get('offer_title', '?')[:40]
                        parts.append(f"  [{status}] {title}")
        except Exception as e:
            parts.append(f"Erreur lecture stats: {e}")

        return "\n".join(parts)

    def _cmd_help(self) -> str:
        """Commande /help"""
        return (
            "SYLPH - Commandes\n\n"
            "/status - Etat de l'agent\n"
            "/stats - Statistiques detaillees\n"
            "/offres - 5 dernieres offres trouvees\n"
            "/help - Cette aide\n\n"
            "Ou pose-moi une question en francais,\n"
            "je te reponds via l'IA !"
        )

    def _cmd_recent_offers(self) -> str:
        """Commande /offres"""
        try:
            offers_path = Path(OFFERS_FILE)
            if not offers_path.exists():
                return "Aucune offre en base."

            with open(offers_path) as f:
                offers = json.load(f)

            if not offers:
                return "Aucune offre en base."

            recent = offers[-5:]
            parts = [f"5 DERNIERES OFFRES (sur {len(offers)} total)\n"]
            for i, o in enumerate(reversed(recent), 1):
                title = o.get('title', '?')[:50]
                company = o.get('company', '?')
                platform = o.get('platform', '?')
                date = o.get('found_date', '')[:10]
                parts.append(f"{i}. {title}\n   {company} ({platform}) - {date}")

            return "\n".join(parts)
        except Exception as e:
            return f"Erreur lecture offres: {e}"

    def _send_reply(self, text: str):
        """Envoie une reponse (texte brut, pas de HTML)"""
        try:
            # Telegram limite a 4096 chars
            if len(text) > 4000:
                text = text[:4000] + "\n\n[... tronque]"

            resp = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error(f"Telegram Bot: envoi echoue: {data}")
        except Exception as e:
            logger.error(f"Telegram Bot: erreur envoi: {e}")


# ==================================================================
# FACTORY FUNCTIONS
# ==================================================================

def create_notifier(config: dict) -> TelegramNotifier | None:
    """Cree un notifier depuis la config"""
    tg_config = config.get('telegram', {})
    token = tg_config.get('bot_token', '')
    chat_id = tg_config.get('chat_id', '')

    if not token or not chat_id:
        logger.warning("Telegram: token ou chat_id manquant, notifications desactivees")
        return None

    notifier = TelegramNotifier(token, str(chat_id))
    if notifier.verify():
        return notifier
    return None


def create_bot(config: dict, ai_client=None) -> TelegramBot | None:
    """Cree le bot interactif depuis la config"""
    tg_config = config.get('telegram', {})
    token = tg_config.get('bot_token', '')
    chat_id = tg_config.get('chat_id', '')

    if not token or not chat_id:
        return None

    bot = TelegramBot(token, str(chat_id), ai_client=ai_client)
    return bot
