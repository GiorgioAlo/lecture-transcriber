"""FASI 2-3 — Elaborazione del testo con Gemini (pulizia e traduzione).

- `rileva_lingua`  : una chiamata leggera per capire in che lingua e il parlato.
- `pulisci`        : corregge e ripulisce il testo nella lingua sorgente.
- `traduci`        : traduce il testo pulito in una lingua d'arrivo.

Pulizia e traduzione usano lo stesso motore (`_processa`): cambia solo la
coppia lingua-sorgente / lingua-arrivo nel prompt.
"""
from __future__ import annotations

import concurrent.futures
import re

from google.genai import types

from . import config, languages
from .errors import Interrotto, LimiteGiornaliero
from .gemini import con_retry
from .progress import Reporter


# =====================================================================
# Rilevamento della lingua parlata
# =====================================================================

def _campione_lingua(testo: str, quanti: int = 1500) -> str:
    """Prende un campione da INIZIO + CENTRO del testo.

    Solo l'inizio non basta: una lezione puo' aprirsi con un saluto in una lingua
    e proseguire in un'altra; il centro e' piu' rappresentativo del corpo."""
    t = (testo or "").strip()
    if len(t) <= quanti:
        return t
    meta = len(t) // 2
    return t[: quanti // 2] + "\n" + t[meta: meta + quanti // 2]


def rileva_lingua(client, testo: str, interrotto=None) -> str:
    """Ritorna il codice lingua ('it', 'en', ...) del testo. Default 'en'."""
    campione = _campione_lingua(testo)
    if not campione:
        return "en"
    # Scegliamo solo tra le lingue d'INGRESSO attese (it/en): poche opzioni =
    # riconoscimento piu' affidabile. Le decine di lingue di USCITA non c'entrano qui.
    ingresso = languages.LINGUE_INGRESSO or list(languages.LINGUE.keys())
    codici = ", ".join(ingresso)
    prompt = (
        "Identify the language of the following text. "
        f"Answer with ONLY one of these codes: {codici}. No other words.\n\n"
        f"TEXT:\n{campione}"
    )

    def azione():
        r = client.models.generate_content(
            model=config.TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return (r.text or "").strip().lower()

    try:
        risposta = con_retry(azione, "rilevo la lingua", interrotto=interrotto)
    except Interrotto:
        raise
    except Exception:
        return ingresso[0]
    for codice in ingresso:
        if codice in risposta:
            return codice
    return ingresso[0]


# =====================================================================
# Rilevamento della materia (per affilare pulizia/traduzione)
# =====================================================================

# Caratteri di testo usati per dedurre la materia: ne bastano pochi. Misurato
# (exp_materia): la materia e azzeccata gia dai primi ~5-20K caratteri, il resto
# non cambia il verdetto; ~5s di chiamata. Campioniamo l'inizio e basta.
MAX_CAMPIONE_MATERIA = 20000


def _componi_materia(risposta: str) -> str:
    """Da 'SUBJECT: ...\\nTOPICS: ...' a una stringa compatta per il prompt."""
    subject, topics = "", ""
    for riga in (risposta or "").splitlines():
        r = riga.strip()
        low = r.lower()
        if low.startswith("subject:"):
            subject = r.split(":", 1)[1].strip()
        elif low.startswith("topics:"):
            topics = r.split(":", 1)[1].strip()
    if not subject:
        # Formato inatteso: ripiego sulla prima riga non vuota, troncata.
        prima = next((x.strip() for x in (risposta or "").splitlines() if x.strip()), "")
        return prima[:120]
    return f"{subject} (key topics: {topics})" if topics else subject


def deduci_materia(client, testo: str, interrotto=None) -> str:
    """Deduce in una chiamata leggera la MATERIA della lezione dal testo grezzo.

    Serve ad affilare pulizia/traduzione SENZA chiedere nulla all'utente: il
    risultato (es. 'Network Security (key topics: firewalls, proxies, VPN)')
    finisce nello slot 'dominio' del prompt, al posto del campo corso. Non e'
    critico: se fallisce o il testo e' troppo corto torna "" e il prompt resta
    generico. Misurato (exp_materia): ~5s, bastano i primi ~20K caratteri."""
    campione = (testo or "").strip()[:MAX_CAMPIONE_MATERIA]
    if len(campione) < 200:          # troppo poco testo per dire qualcosa di sensato
        return ""
    prompt = (
        "You are analyzing the RAW, uncorrected transcript of a university lecture "
        "(it may contain speech-recognition errors, filler and repetitions). "
        "Based ONLY on its content, infer what it is about.\n"
        "Answer in EXACTLY this format, nothing else:\n"
        "SUBJECT: <the academic field or course, a short noun phrase>\n"
        "TOPICS: <2-5 specific topics actually discussed, comma-separated>\n\n"
        f"TRANSCRIPT:\n{campione}"
    )

    def azione():
        r = client.models.generate_content(
            model=config.TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=200),
        )
        return (r.text or "").strip()

    try:
        risposta = con_retry(azione, "deduco la materia", interrotto=interrotto)
    except Interrotto:
        raise
    except Exception:
        return ""
    return _componi_materia(risposta)


# =====================================================================
# Divisione in blocchi
# =====================================================================

def dividi_blocchi(testo: str, max_caratteri: int = config.MAX_CARATTERI_BLOCCO) -> list[str]:
    """Divide il testo in blocchi di al massimo `max_caratteri`, tagliando a fine
    frase o a fine riga. Funziona anche con righe senza punteggiatura."""
    unita: list[tuple[str, bool]] = []
    for riga in testo.replace("\r\n", "\n").split("\n"):
        riga = riga.strip()
        if not riga:
            continue
        for f in re.split(r"(?<=[.!?])\s+", riga):
            while len(f) > max_caratteri:
                pos = f.rfind(" ", 0, max_caratteri)
                taglio = pos if pos > 0 else max_caratteri
                unita.append((f[:taglio], False))
                f = f[taglio:].strip()
            if f:
                unita.append((f, False))
        if unita:
            unita[-1] = (unita[-1][0], True)

    blocchi, corrente = [], ""
    for testo_unita, fine_riga in unita:
        pezzo = testo_unita + ("\n" if fine_riga else " ")
        if corrente and len(corrente) + len(pezzo) > max_caratteri:
            blocchi.append(corrente.strip())
            corrente = ""
        corrente += pezzo
    if corrente.strip():
        blocchi.append(corrente.strip())
    return blocchi


# =====================================================================
# Prompt ed elaborazione di un blocco
# =====================================================================

def _costruisci_prompt(blocco: str, sorgente: str, destinazione: str, dominio: str) -> str:
    contesto = (
        f'This lecture is about: "{dominio}". '
        "Use this subject to resolve ambiguous or misrecognized technical terms.\n"
        if dominio else ""
    )
    return f"""
You are an expert academic editor and translator working on university lectures across any discipline.
{contesto}Source Language of the audio: {sorgente}
Target Language for the output: {destinazione}

The raw text was produced by an automatic speech recognizer on a university lecture,
often with questions from students recorded from far away. Words are sometimes replaced by
similar-sounding ones (for example a common word in place of a technical term of the subject,
or a phrase split in the wrong place). Fix them ONLY when the context makes the correct term clear.

Your TASK is to process the provided raw transcript following these strict RULES:

1. **DO NOT SUMMARIZE (CRITICAL)**: Keep the dynamic, colloquial, and repetitive nature of the spoken lecture. Maintain the speaker's style completely. Do NOT shorten the text. Keep paragraphs and line breaks exactly as they are.
2. **Fix Phonetic Errors**: Recognize common mispronunciations and correct technical or proper terms based on the subject matter of the lecture. Do NOT invent terminology: correct a term only when the context makes the intended word clear.
3. **Fix Punctuation and Capitalization**: Insert periods, commas, and question marks to make sentences coherent. Capitalize proper nouns appropriately.
4. **Remove ONLY Obvious Artifacts**: Delete filler sounds (uh, um), nonsensical word loops and stutters, but keep the core meaning and repetitions made for emphasis intact.
5. **Action Required**:
   - If Target Language equals Source Language: Output the CLEANED text natively.
   - If Target Language is DIFFERENT from Source Language: Provide a faithful and literal translation. Do NOT guess or interpret unclear sentences; translate them literally. Keep technical terms and proper nouns in their original language when there is no standard equivalent in the target language.
6. **Do Not Add Information**: Do not insert commentary or facts not present in the audio.

RULES: Output ONLY the final {destinazione} text. Do not include titles, bullet points, markdown, or introductory remarks.

RAW TEXT TO PROCESS:
[START_TEXT]
{blocco}
[END_TEXT]
"""


def _elabora_blocco(client, indice, totale, blocco, sorgente, destinazione, corso, reporter):
    prompt = _costruisci_prompt(blocco, sorgente, destinazione, corso)

    def azione():
        risposta = client.models.generate_content(
            model=config.TEXT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1, max_output_tokens=config.MAX_OUTPUT_TOKENS),
        )
        testo = (risposta.text or "").strip()
        if not testo:
            raise RuntimeError("risposta vuota")
        return testo

    # Una sola chiamata, con con_retry per gli errori temporanei: sul 429 aspetta
    # il retryDelay DELL'API (non attese fisse), sul limite GIORNALIERO solleva
    # LimiteGiornaliero (la lasciamo salire: la UI dira' "finite per oggi" e il
    # lavoro gia' fatto resta in cache). Niente guardia anti-riassunto: misurato
    # che a blocchi grandi, con MAX_OUTPUT_TOKENS alto, flash-lite non riassume.
    try:
        testo = con_retry(azione, f"blocco {indice}/{totale}", reporter.log,
                          interrotto=reporter.interrotto,
                          max_tentativi=config.MAX_TENTATIVI_TESTO)
        return indice, testo, False
    except (LimiteGiornaliero, Interrotto):
        raise
    except Exception:
        marcatore = f"\n{config.MARCATORE_ERRORE}: blocco {indice} non elaborato dopo {config.MAX_TENTATIVI_TESTO} tentativi.]\n"
        return indice, marcatore, True


def _processa(client, testo, sorgente, destinazione, corso, reporter, avanzamento):
    """Elabora tutto il testo (pulizia o traduzione) a blocchi, in parallelo."""
    blocchi = dividi_blocchi(testo)
    reporter.log(f"📦 {len(blocchi)} blocchi (max {config.MAX_CARATTERI_BLOCCO} caratteri), "
                 f"{config.WORKER_PARALLELI} in parallelo")
    risultati: list[tuple[int, str]] = []
    errori = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=config.WORKER_PARALLELI) as ex:
        futs = [ex.submit(_elabora_blocco, client, i, len(blocchi), b, sorgente, destinazione, corso, reporter)
                for i, b in enumerate(blocchi, 1)]
        for n, f in enumerate(concurrent.futures.as_completed(futs), 1):
            if reporter.interrotto():
                for fut in futs:
                    fut.cancel()
                raise Interrotto()
            indice, testo_out, fallito = f.result()
            errori += fallito
            risultati.append((indice, testo_out))
            avanzamento(n / max(1, len(blocchi)))
    return "\n\n".join(t for _, t in sorted(risultati)), errori


# =====================================================================
# API pubbliche delle fasi 2 e 3
# =====================================================================

def pulisci(client, testo, lingua_sorgente, corso, reporter, avanzamento=lambda f: None):
    """FASE 2 — ripulisce il testo nella sua stessa lingua."""
    nome = languages.nome_prompt(lingua_sorgente)
    return _processa(client, testo, nome, nome, corso, reporter, avanzamento)


def traduci(client, testo_pulito, lingua_sorgente, lingua_target, corso, reporter, avanzamento=lambda f: None):
    """FASE 3 — traduce il testo pulito dalla lingua sorgente a quella d'arrivo."""
    return _processa(client, testo_pulito,
                     languages.nome_prompt(lingua_sorgente),
                     languages.nome_prompt(lingua_target),
                     corso, reporter, avanzamento)
