"""Lingue supportate: codici brevi ↔ nomi.

- Il codice breve ("it", "en", ...) e quello che arriva dalla UI e che usiamo
  nei nomi dei file.
- Il nome inglese ("Italian", "English", ...) e quello che capiscono i prompt
  di Gemini.
- Il nome italiano serve solo per i messaggi all'utente.
"""
from __future__ import annotations

# codice -> (nome inglese per i prompt, nome italiano per l'utente)
# Lingue di USCITA: l'utente puo' tradurre verso una qualsiasi di queste.
# Gemini ne traduce molte di piu'; qui teniamo le piu' comuni (con bandiera lato UI).
LINGUE: dict[str, tuple[str, str]] = {
    "it": ("Italian", "Italiano"),
    "en": ("English", "Inglese"),
    "es": ("Spanish", "Spagnolo"),
    "fr": ("French", "Francese"),
    "de": ("German", "Tedesco"),
    "pt": ("Portuguese", "Portoghese"),
    "ar": ("Arabic", "Arabo"),
    "zh": ("Chinese (Simplified)", "Cinese (semplificato)"),
    "ja": ("Japanese", "Giapponese"),
    "ko": ("Korean", "Coreano"),
    "ru": ("Russian", "Russo"),
    "hi": ("Hindi", "Hindi"),
    "nl": ("Dutch", "Olandese"),
    "pl": ("Polish", "Polacco"),
    "tr": ("Turkish", "Turco"),
    "uk": ("Ukrainian", "Ucraino"),
    "el": ("Greek", "Greco"),
    "sv": ("Swedish", "Svedese"),
    "ro": ("Romanian", "Rumeno"),
    "cs": ("Czech", "Ceco"),
    "he": ("Hebrew", "Ebraico"),
    "fa": ("Persian", "Persiano"),
    "id": ("Indonesian", "Indonesiano"),
    "vi": ("Vietnamese", "Vietnamita"),
    "th": ("Thai", "Thailandese"),
    "da": ("Danish", "Danese"),
    "fi": ("Finnish", "Finlandese"),
    "no": ("Norwegian", "Norvegese"),
    "hu": ("Hungarian", "Ungherese"),
    "bg": ("Bulgarian", "Bulgaro"),
    "hr": ("Croatian", "Croato"),
    "sk": ("Slovak", "Slovacco"),
    "sr": ("Serbian", "Serbo"),
    "bn": ("Bengali", "Bengalese"),
    "ur": ("Urdu", "Urdu"),
    "ms": ("Malay", "Malese"),
}

# Lingue in cui ci aspettiamo sia PARLATA la lezione (per il rilevamento automatico).
# La trascrizione funziona anche con altre, ma il rilevamento sceglie tra queste
# (restare su poche opzioni rende il riconoscimento piu' affidabile).
LINGUE_INGRESSO = ["it", "en"]


def nome_prompt(codice: str) -> str:
    """Nome inglese della lingua, per i prompt di Gemini (default: Inglese)."""
    return LINGUE.get(codice, LINGUE["en"])[0]


def nome_italiano(codice: str) -> str:
    """Nome in italiano della lingua, per i messaggi all'utente."""
    return LINGUE.get(codice, ("", codice))[1]


def codice_da_nome(nome: str) -> str:
    """Dal nome inglese ('English') al codice ('en'). Default: 'en'."""
    nome = (nome or "").strip().lower()
    for codice, (en, _it) in LINGUE.items():
        if en.lower() == nome:
            return codice
    return "en"
