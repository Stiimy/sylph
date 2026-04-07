"""
Generateur de lettre de motivation automatique.

Version IA: utilise Ollama pour generer une lettre personnalisee
en fonction de l'offre, de l'entreprise et du profil.

Fallback: template statique si l'IA n'est pas dispo.
"""

import logging
from typing import Optional

logger = logging.getLogger("job-agent")


COVER_LETTER_SYSTEM = """Tu es un expert en redaction de lettres de motivation pour des alternances en informatique en France.
Tu ecris des lettres courtes, naturelles et professionnelles. PAS de formules creuses ou trop generiques.

REGLES STRICTES:
- Maximum 150 mots
- Ton professionnel mais pas robotique. Un jeune de 20 ans qui ecrit bien.
- JAMAIS de "je me permets de", "c'est avec un grand interet", "veuillez agreer"
- Commence par "Madame, Monsieur," et finis par "Cordialement, [NOM]"
- Mentionne le nom de l'entreprise et le titre du poste
- Relie les competences du candidat aux besoins du poste
- Si la description du poste mentionne des technos/outils, fais le lien avec les competences du candidat
- Sois specifique: pas de "je suis motive et dynamique", mais plutot ce que le candidat SAIT faire
- Ecris en francais correct avec accents

FORMAT:
Madame, Monsieur,

[Corps de la lettre - 2-3 paragraphes courts]

Cordialement,
[NOM COMPLET]"""


def generate_cover_letter(offer: dict, profile: dict, ai_client=None) -> str:
    """Genere une lettre de motivation adaptee a l'offre.
    
    Si ai_client est fourni et disponible, utilise l'IA.
    Sinon, fallback sur le template statique.
    
    Args:
        offer: dict avec title, company, description, platform, etc.
        profile: dict avec name, email, summary, etc.
        ai_client: Instance de OllamaClient (optionnel)
        
    Returns:
        Lettre de motivation en texte brut
    """
    # Essayer l'IA en premier
    if ai_client:
        ai_letter = _generate_ai_letter(offer, profile, ai_client)
        if ai_letter:
            return ai_letter
        logger.warning("Generation IA echouee, fallback sur template statique")

    # Fallback: template statique
    return _generate_template_letter(offer, profile)


def _generate_ai_letter(offer: dict, profile: dict, ai_client) -> Optional[str]:
    """Genere la lettre via Ollama"""
    name = profile.get('name', '')
    parts = name.split()
    nom_complet = f"{parts[-1]} {parts[0]}" if len(parts) > 1 else name

    title = offer.get('title', 'ce poste')
    company = offer.get('company', 'cette entreprise')
    description = offer.get('description', '')
    platform = offer.get('platform', '')

    # Limiter la description pour pas exploser le contexte
    if len(description) > 1500:
        description = description[:1500] + "..."

    prompt = f"""Ecris une lettre de motivation pour cette offre d'alternance.

CANDIDAT:
- Nom: {nom_complet}
- Formation: {profile.get('summary', 'Formation en informatique').split(chr(10))[0]}
- Competences: {profile.get('summary', 'informatique, systeme, reseau, securite')}
- Recherche: alternance informatique a Paris

OFFRE:
- Titre: {title}
- Entreprise: {company}
- Description: {description if description else 'Non disponible'}

Ecris la lettre de motivation. Signe avec "{nom_complet}"."""

    response = ai_client.generate(prompt, system=COVER_LETTER_SYSTEM, temperature=0.6)

    if not response:
        return None

    # Nettoyage basique
    letter = response.strip()

    # Verifier que ca commence et finit correctement
    if not letter.startswith("Madame"):
        # Le modele a peut-etre ajoute du blabla avant
        idx = letter.find("Madame")
        if idx != -1:
            letter = letter[idx:]
        else:
            # Reponse inutilisable
            logger.warning("Lettre IA mal formatee, fallback")
            return None

    # Verifier que le nom est bien a la fin
    if nom_complet not in letter:
        letter = letter.rstrip() + f"\n{nom_complet}"

    logger.info(f"Lettre de motivation IA generee ({len(letter)} chars)")
    return letter


def _generate_template_letter(offer: dict, profile: dict) -> str:
    """Fallback: genere une lettre avec le template statique (ancien code)"""
    name = profile.get('name', '')
    parts = name.split()
    nom_complet = f"{parts[-1]} {parts[0]}" if len(parts) > 1 else name

    title = offer.get('title', 'ce poste')
    company = offer.get('company', '')

    # Detecter le type de poste pour adapter le vocabulaire
    title_lower = title.lower()
    if any(w in title_lower for w in ['cyber', 'securite', 'ssi', 'rssi', 'pentest']):
        domaine = "la cybersecurite"
        motivation_detail = (
            "Passionne par la securite des systemes d'information, "
            "je maitrise les outils de pentest, l'OSINT et l'administration "
            "de systemes Linux. Ma formation en cybersecurite m'a permis "
            "de developper des competences solides en analyse de vulnerabilites "
            "et en protection des infrastructures."
        )
    elif any(w in title_lower for w in ['reseau', 'telecom', 'infra', 'systeme']):
        domaine = "les reseaux et systemes"
        motivation_detail = (
            "Forme a l'administration systeme et reseau, "
            "je maitrise Docker, Azure, et l'administration "
            "Linux. Je suis capable de deployer et maintenir des infrastructures "
            "fiables et securisees."
        )
    elif any(w in title_lower for w in ['support', 'technicien', 'assistance', 'helpdesk']):
        domaine = "le support informatique"
        motivation_detail = (
            "Rigoureux et pedagogue, je suis forme au diagnostic "
            "et a la resolution d'incidents informatiques. Ma formation "
            "m'a donne des bases solides en systemes, reseaux et securite "
            "qui me permettent d'assurer un support efficace."
        )
    elif any(w in title_lower for w in ['dev', 'developpeur', 'programmeur', 'devops']):
        domaine = "le developpement informatique"
        motivation_detail = (
            "Forme au developpement, "
            "je maitrise Python et les outils DevOps (Docker, CI/CD). "
            "Je suis motive pour contribuer a des projets concrets "
            "et monter en competences rapidement."
        )
    else:
        domaine = "l'informatique"
        motivation_detail = (
            "Disposant de competences variees en administration systeme, "
            "securite informatique, et deploiement d'infrastructures, "
            "je suis motive et pret a m'investir pleinement."
        )

    entreprise_text = f"au sein de {company}" if company and company != "Non specifie" else ""

    letter = (
        f"Madame, Monsieur,\n\n"
        f"Actuellement en formation informatique, "
        f"je suis a la recherche d'une alternance dans {domaine}. "
        f"Votre offre \"{title}\" {entreprise_text} correspond "
        f"parfaitement a mon projet professionnel.\n\n"
        f"{motivation_detail}\n\n"
        f"Je suis disponible immediatement pour integrer votre equipe "
        f"en alternance et mettre mes competences a votre service. "
        f"Je serais ravi d'echanger avec vous lors d'un entretien.\n\n"
        f"Cordialement,\n"
        f"{nom_complet}"
    )

    return letter
