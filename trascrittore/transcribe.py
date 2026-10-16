"""FASE 1 — Trascrizione audio.

Motore PRIMARIO: `config.ASR_MODEL` (gemini-3.5-flash-lite). L'audio viene diviso
in blocchi da ~10 min (vedi config.MAX_BLOCCO_MIN) e trascritto IN PARALLELO
(config.ASR_WORKER blocchi insieme) = veloce e con quota larga.

flash-lite e' pero' un ASR stocastico: su qualche blocco puo' andare in RUNAWAY
(loop/allucinazione) o TRONCARE. Per questo ogni blocco passa da una GUARDIA:
  1. trascrive col modello flash-lite (thinking basso + cap sui token in uscita);
  2. toglie gli artefatti di formato (tag <i>, finti timestamp);
  3. DIAGNOSTICA: runaway (wpm altissima / tetto token / filata di numeri) o
     corto (wpm bassissima) o ok;
  4. se runaway → ritenta (i fallimenti sono stocastici); tiene il tentativo piu'
     lungo non-runaway;
  5. se TUTTI i tentativi sono runaway → ripiega su `config.TRANSCRIBE_MODEL`
     (trascrittore dedicato affidabile) con collasso delle ripetizioni.

Ogni blocco trascritto viene salvato in cache: ripartendo si riusano i blocchi
gia fatti. Il testo torna nella LINGUA PARLATA (nessuna traduzione qui).
"""
from __future__ import annotations

import concurrent.futures
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

from google.genai import types

from . import audio, config, util
from .errors import ContenutoBloccato, Interrotto
from .gemini import IMPOSTAZIONI_SICUREZZA, con_retry
from .progress import Reporter

PROMPT_TRASCRIZIONE = (
    "You are transcribing a university lecture. The speaker may be a non-native "
    "English speaker or may speak Italian; there may be occasional student questions "
    "recorded from far away. Produce a faithful, VERBATIM transcript in the ORIGINAL "
    "language actually spoken. Do NOT translate, do NOT summarize, do NOT add commentary, "
    "titles, speaker labels or timestamps. Transcribe everything that is said; for an "
    "unintelligible passage, write your best guess. Output ONLY the transcript text."
)

# --- Pulizia artefatti di formato che flash-lite a volte inventa -----------
# Il contenuto e' corretto ma lo "decora": tag HTML (<i>...</i>) e finti
# timestamp ("5:10"). Due cifre dopo i due punti → un rapporto "3:1" e i
# decimali "1,58" NON vengono toccati.
_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_TS = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")


def _pulisci_artefatti(t: str) -> str:
    t = _TAG.sub("", t)
    t = _TS.sub("", t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)   # spazio lasciato prima della punteggiatura
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


# --- Rilevatore di runaway NUMERICO ----------------------------------------
# flash-lite a volte si "aggancia" a una progressione (0,36 0,42 0,47 ... per
# centinaia di termini) che sfugge sia al check wpm (numeri "lenti") sia a
# quello di loop (tutti diversi). Contiamo la piu' lunga sequenza di token
# numerici CONSECUTIVI.
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")


def _max_run_numeri(t: str) -> int:
    run = mx = 0
    for tok in t.split():
        if _NUM.match(tok.strip(".,;:()[]")):
            run += 1
            mx = max(mx, run)
        else:
            run = 0
    return mx


def _carica_file(client, path: Path, reporter: Reporter):
    """Carica un file audio via File API e attende che sia ACTIVE.

    L'UPLOAD passa da con_retry: un blip di rete (es. 'Server disconnected without
    sending a response') o un 503 non fa piu' fallire il blocco (e quindi l'intera
    lezione), ma riprova con backoff. Anche il polling dello stato tollera un
    singolo intoppo (riprova al giro dopo). L'attesa (file in PROCESSING) resta
    annullabile: se l'utente annulla, solleva Interrotto invece di restare nel ciclo."""
    def _upload():
        return client.files.upload(file=str(path))

    f = con_retry(_upload, f"carico {path.name}", reporter.log,
                  interrotto=reporter.interrotto)
    while f.state.name == "PROCESSING":
        if reporter.interrotto():
            raise Interrotto()
        time.sleep(2)
        try:
            f = client.files.get(name=f.name)
        except Exception:
            continue   # intoppo di rete durante il polling: non e' fatale, ritento
    if f.state.name != "ACTIVE":
        raise RuntimeError(f"upload fallito ({f.state.name}) per {path.name}")
    return f


# Motivi per cui Gemini puo' RIFIUTARE di rispondere. Li riconosciamo per dare
# all'utente un messaggio chiaro invece di crashare o ritentare a vuoto. Coi
# filtri a BLOCK_NONE (gemini.IMPOSTAZIONI_SICUREZZA) i blocchi per sola
# volgarita' non dovrebbero piu' scattare; restano casi fuori dal nostro
# controllo come il copyright (RECITATION) o una blocklist del modello.
_FINISH_BLOCCO = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}

def _messaggio_blocco(motivo: str) -> str:
    """Messaggio utente a seconda del PERCHE' Gemini ha rifiutato. Il motivo tecnico
    e' sempre incluso in coda: ci dice se e' qualcosa che possiamo toccare (safety,
    ora gia' a BLOCK_NONE) o no (copyright/proibito, non disattivabili sull'API)."""
    m = (motivo or "").upper()
    if m == "RECITATION":
        testa = ("Gemini riconosce nell'audio materiale protetto da copyright "
                 "(musica o clip di un programma) e non lo trascrive.")
    elif m in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
        testa = ("Gemini considera questo audio non adatto e si rifiuta di trascriverlo.")
    else:
        testa = "Gemini si e' rifiutato di elaborare questo audio."
    return (f"{testa} (motivo tecnico: {motivo}). "
            "Capita con i video di intrattenimento; con le lezioni normali non succede.")


def _motivo_blocco(risposta) -> str | None:
    """Se Gemini ha BLOCCATO la risposta, ritorna il motivo leggibile, altrimenti None.
    Due forme: blocco del PROMPT (`prompt_feedback.block_reason`, candidati vuoti)
    o blocco del CANDIDATO (`finish_reason` = SAFETY/RECITATION/...)."""
    pf = getattr(risposta, "prompt_feedback", None)
    br = getattr(pf, "block_reason", None)
    if br:
        return str(br).split(".")[-1]
    cand = getattr(risposta, "candidates", None) or []
    if cand:
        fr = str(getattr(cand[0], "finish_reason", "") or "").split(".")[-1]
        if fr in _FINISH_BLOCCO:
            return fr
    return None


def _estrai_transcript(risposta) -> str:
    """transcribe mette il testo in part.audio_transcription.text; i generalisti in part.text.

    Robusto quando Gemini non torna candidati o parti (risposta bloccata/vuota):
    ritorna "" invece di indicizzare un None (era il crash
    `'NoneType' object is not subscriptable`)."""
    cand = getattr(risposta, "candidates", None) or []
    if not cand:
        return ""
    parti = getattr(getattr(cand[0], "content", None), "parts", None) or []
    pezzi = []
    for part in parti:
        at = getattr(part, "audio_transcription", None)
        if at is not None and getattr(at, "text", None):
            pezzi.append(at.text)
        elif getattr(part, "text", None):
            pezzi.append(part.text)
    return "\n".join(pezzi).strip()


def _wpm(testo: str, durata_sec: float) -> float:
    """Parole al minuto del testo rispetto alla durata dell'audio."""
    minuti = max(durata_sec / 60.0, 0.1)
    return len(testo.split()) / minuti


def _sospetto_loop(testo: str, durata_sec: float) -> bool:
    """True se il blocco sembra in loop (troppe parole/minuto). Usato sul
    FALLBACK transcribe (che puo' loopare sulla coda di silenzio di fine lezione)."""
    minuti = durata_sec / 60.0
    if minuti < config.MIN_MIN_GUARDIA_LOOP:
        return False
    return _wpm(testo, durata_sec) > config.SOGLIA_LOOP_WPM


def _collassa_ripetizioni(testo: str, max_volte: int = config.MAX_RIPETIZIONI_FRASE) -> str:
    """Ultima spiaggia anti-loop per il transcribe, in due mosse.

    1) TRONCAMENTO della coda in loop (riscrive il finale decine di volte): taglio
       alla SECONDA comparsa della prima frase molto ripetuta.
    2) CAP di sicurezza: al massimo `max_volte` copie di ogni frase. I frammenti
       corti (<20 char) si tengono sempre.
    """
    frasi = re.split(r"(?<=[.?!])\s+", testo)
    norm = [f.strip().lower() for f in frasi]
    totali: dict[str, int] = {}
    for k in norm:
        if len(k) > 20:
            totali[k] = totali.get(k, 0) + 1

    soglia_loop = max(4, max_volte + 1)
    visti: set[str] = set()
    taglio = len(frasi)
    for i, k in enumerate(norm):
        if len(k) <= 20:
            continue
        if k in visti and totali.get(k, 0) >= soglia_loop:
            taglio = i
            break
        visti.add(k)
    frasi = frasi[:taglio]

    conteggio: dict[str, int] = {}
    tenute: list[str] = []
    for f in frasi:
        k = f.strip().lower()
        if len(k) <= 20:
            tenute.append(f)
            continue
        conteggio[k] = conteggio.get(k, 0) + 1
        if conteggio[k] <= max_volte:
            tenute.append(f)
    return " ".join(tenute).strip()


def _diagnosi(testo: str, finish: str, durata_sec: float) -> str:
    """'OK' | 'RUNAWAY' | 'CORTO' per un blocco trascritto da flash-lite."""
    minuti = durata_sec / 60.0
    if finish == "MAX_TOKENS":
        return "RUNAWAY"
    if minuti > config.ASR_MIN_MIN_GUARDIA and _wpm(testo, durata_sec) > config.ASR_SOGLIA_RUNAWAY_WPM:
        return "RUNAWAY"
    if _max_run_numeri(testo) > config.ASR_SOGLIA_RUN_NUMERI:
        return "RUNAWAY"              # filata di numeri inventata
    if minuti > config.ASR_MIN_MIN_GUARDIA and _wpm(testo, durata_sec) < config.ASR_SOGLIA_CORTO_WPM:
        return "CORTO"
    return "OK"


def _genera(client, model: str, file_obj, extra: dict, reporter: Reporter, descr: str):
    """Una chiamata a `model` sul file audio, con con_retry (429/503 → attesa del
    retryDelay dell'API, annullabile). Ritorna (testo, finish_reason)."""
    def azione():
        risposta = client.models.generate_content(
            model=model,
            contents=[file_obj, PROMPT_TRASCRIZIONE],
            config=types.GenerateContentConfig(
                temperature=config.TEMP_TRASCRIZIONE,
                safety_settings=IMPOSTAZIONI_SICUREZZA,
                **extra),
        )
        testo = _estrai_transcript(risposta)
        if not testo:
            # Niente testo: o Gemini ha RIFIUTATO (safety/copyright) -> errore chiaro
            # SUBITO (con_retry non lo ritenta), oppure e' un vuoto transitorio ->
            # RuntimeError, che con_retry ritenta.
            motivo = _motivo_blocco(risposta)
            if motivo:
                reporter.log(f"⛔ [{descr}] Gemini ha BLOCCATO il contenuto — motivo: {motivo}")
                raise ContenutoBloccato(_messaggio_blocco(motivo))
            raise RuntimeError("trascrizione vuota")
        finish = str(getattr(risposta.candidates[0], "finish_reason", "")).split(".")[-1]
        return testo, finish

    return con_retry(azione, descr, reporter.log, interrotto=reporter.interrotto)


def _trascrivi_con_guardia(client, chunk_path: Path, durata_sec: float,
                           descrizione: str, reporter: Reporter) -> tuple[str, str]:
    """Trascrive UN blocco con la guardia. Ritorna (testo, motore_usato).

    Fino a ASR_MAX_TENTATIVI tentativi con flash-lite: scarta i RUNAWAY (ritenta),
    tiene il tentativo piu' LUNGO non-runaway (recupera i troncamenti; un blocco
    genuinamente rado resta corto su tutti i tentativi → si accetta il migliore).
    Se TUTTI i tentativi sono runaway → fallback su TRANSCRIBE_MODEL."""
    cap = max(3072, int(durata_sec / 60.0 * config.ASR_CAP_WPM * 1.4))
    cfg_flash = {
        "max_output_tokens": cap,
        "thinking_config": types.ThinkingConfig(thinking_budget=config.ASR_THINKING_BUDGET),
    }
    f = _carica_file(client, chunk_path, reporter)
    try:
        tentativi_ok: list[str] = []
        for t in range(1, config.ASR_MAX_TENTATIVI + 1):
            if reporter.interrotto():
                raise Interrotto()
            testo, finish = _genera(client, config.ASR_MODEL, f, cfg_flash, reporter, descrizione)
            testo = _pulisci_artefatti(testo)
            d = _diagnosi(testo, finish, durata_sec)
            if d == "RUNAWAY":
                reporter.log(f"⚠️  [{descrizione}] blocco sospetto (runaway), ritento "
                             f"({t}/{config.ASR_MAX_TENTATIVI})")
                continue
            tentativi_ok.append(testo)
            if d == "OK":
                break
        if tentativi_ok:
            return max(tentativi_ok, key=lambda s: len(s.split())), config.ASR_MODEL

        # tutti runaway → fallback sul trascrittore dedicato
        reporter.log(f"↩️  [{descrizione}] uso {config.TRANSCRIBE_MODEL} (fallback)")
        testo, _finish = _genera(client, config.TRANSCRIBE_MODEL, f, {}, reporter,
                                 descrizione + " (fallback)")
        if _sospetto_loop(testo, durata_sec):
            testo = _collassa_ripetizioni(testo)
        return _pulisci_artefatti(testo), config.TRANSCRIBE_MODEL
    finally:
        try:
            client.files.delete(name=f.name)   # non lasciare file sull'account
        except Exception:
            pass


def prepara_audio(
    sorgente: Path | None,
    work_dir: Path,
    inizio: float,
    minuti: float | None,
    reporter: Reporter,
    url: str | None = None,
    cookies: str | None = None,
    password: str | None = None,
    avanzamento=lambda fr: None,
) -> list[Path]:
    """FASE 0 — procura l'audio e lo divide in blocchi. Ritorna i blocchi (riusa i gia presenti).

    L'audio arriva da un file locale (`sorgente`) oppure, se c'e' `url`, viene
    prima SCARICATO col link (yt-dlp). La barra di FASE 0 avanza via `avanzamento`."""
    audio_file = work_dir / "audio.m4a"
    chunk_dir = work_dir / "chunks_audio"

    # Un set di blocchi rimasto da una sessione uccisa (o da una cache vecchia, pre-fix
    # segmentazione atomica) puo' essere PARZIALE/corrotto: se NESSUN blocco e' valido lo
    # butto, cosi' sotto rigenero invece di finire in errore "file vuoto o danneggiato".
    esistenti = sorted(chunk_dir.glob("part_*.m4a"))
    if esistenti and not any(audio.durata(c) >= 1.0 for c in esistenti):
        shutil.rmtree(chunk_dir, ignore_errors=True)

    if not sorted(chunk_dir.glob("part_*.m4a")):
        # Estrazione + segmentazione, con RIPRESA robusta dopo un "annulla tutto": un
        # kill (terminate) a meta' puo' lasciare un audio.m4a corrotto o un set di
        # blocchi parziale. Se qualcosa va storto (ffmpeg fallisce, durata incoerente),
        # pulisco TUTTO e riprovo da zero una volta; solo al 2o fallimento mi arrendo.
        # Senza questo, la lezione finiva in errore e bisognava rimetterla in coda a mano.
        for tentativo in (1, 2):
            try:
                if audio_file.exists() and audio.durata(audio_file) <= 0:
                    reporter.log("⚠️  audio incompleto da una sessione interrotta: lo rifaccio")
                    audio_file.unlink(missing_ok=True)
                if not audio_file.exists():
                    if url:  # lezione da link: prima scarico (il grosso di FASE 0)
                        from . import download
                        # il download e' il grosso dell'attesa per un link: gli diamo quasi
                        # tutta la barra di FASE 0 (0->0.9) cosi' avanza visibilmente mentre scarica.
                        sorgente = download.scarica(url, work_dir, cookies, password, reporter,
                                                    avanzamento=lambda fr: avanzamento(0.9 * fr))
                    if sorgente is None:
                        raise FileNotFoundError("Nessuna sorgente audio: ne' file ne' link.")
                    reporter.log("🎛️  Estraggo l'audio (AAC mono 16 kHz)...")
                    audio.estrai_audio(Path(sorgente), audio_file, inizio, minuti)
                    avanzamento(0.95)   # estrazione fatta (>0.9 del download: la barra non torna indietro)
                # Blocchi bilanciati: numero minimo sotto il tetto, poi tutti ~uguali
                # (es. 92 min, tetto 10 -> 10 blocchi da ~9,2 min).
                totale = audio.durata(audio_file)
                tetto = config.MAX_BLOCCO_MIN * 60
                if totale > 0:
                    n = max(1, math.ceil(totale / tetto))
                    seg = math.ceil(totale / n)
                    reporter.log(f"✂️  Divido in {n} blocchi da ~{seg / 60:.0f} min...")
                else:
                    # Durata non leggibile (ffprobe fallito): tagliamo a tempo fisso.
                    seg = tetto
                    reporter.log(f"✂️  Durata ignota: divido a blocchi da {seg / 60:.0f} min...")
                audio.segmenta(audio_file, chunk_dir, int(seg))
                break
            except subprocess.CalledProcessError:
                # ffmpeg ha fallito: l'audio e' quasi certamente corrotto (kill a meta').
                # Butto audio.m4a, gli eventuali .part orfani e i blocchi, e riparto pulito.
                reporter.log("⚠️  audio inservibile (interruzione a meta'): ripulisco e riestraggo")
                audio_file.unlink(missing_ok=True)
                for p in work_dir.glob("audio.part*"):
                    p.unlink(missing_ok=True)
                shutil.rmtree(chunk_dir, ignore_errors=True)
                if tentativo == 2:
                    raise

    chunks = [c for c in sorted(chunk_dir.glob("part_*.m4a")) if audio.durata(c) >= 1.0]
    audio_file.unlink(missing_ok=True)             # il file unito non serve piu (restano i blocchi)
    if not chunks:
        raise RuntimeError("Non sono riuscito a ricavare l'audio: il file sembra vuoto o danneggiato.")
    reporter.log(f"{len(chunks)} blocchi audio pronti")
    return chunks


def trascrivi_chunks(
    client,
    chunks: list[Path],
    work_dir: Path,
    reporter: Reporter,
    avanzamento=lambda frazione: None,
) -> str:
    """FASE 1 — trascrive i blocchi audio IN PARALLELO e ritorna il testo grezzo.

    Ogni blocco passa dalla guardia (_trascrivi_con_guardia). I blocchi gia' in
    cache e non-runaway si riusano. `avanzamento(frazione)` avanza man mano che i
    blocchi vengono completati. Annullabile: alla richiesta di annullo i worker
    ancora in coda vengono cancellati e si solleva Interrotto."""
    chunk_dir = work_dir / "chunks_audio"
    n = len(chunks)
    durate = {i: audio.durata(c) for i, c in enumerate(chunks)}

    def lavora(i: int, c: Path):
        """Gira in un worker: ritorna (indice, testo, chiamata_api_fatta?)."""
        if reporter.interrotto():
            raise Interrotto()
        cache = chunk_dir / f"part_{i + 1:03d}.txt"
        dur = durate[i]
        # Riuso dalla cache SOLO se non sembra un blocco runaway (un blocco venuto
        # male in una run vecchia non va riproposto all'infinito).
        if cache.exists():
            cached = cache.read_text(encoding="utf-8")
            if _diagnosi(cached, "STOP", dur) != "RUNAWAY":
                return i, cached, False
            reporter.log(f"[{i + 1}/{n}] in cache ma sembra un runaway: lo ritrascrivo")
        t0 = time.time()
        reporter.log(f"[{i + 1}/{n}] trascrivo (~{dur / 60:.0f} min)...")
        testo, motore = _trascrivi_con_guardia(client, c, dur, f"audio {i + 1}/{n}", reporter)
        util.scrivi_testo(cache, testo)
        reporter.log(f"[{i + 1}/{n}] ✅ ({time.time() - t0:.0f}s, {len(testo.split())} parole"
                     + (f", {motore}" if motore != config.ASR_MODEL else "") + ")")
        return i, testo, True

    parti: dict[int, str] = {}
    completati = 0
    # Gestisco l'executor A MANO (niente `with`): all'annullo MIRATO voglio
    # mollare SUBITO. Il `with` all'uscita fa shutdown(wait=True) = aspetta che
    # TUTTI i blocchi in volo finiscano la loro chiamata API (~20-30s l'uno),
    # ed e' questo che rendeva l'annullo lento. Con shutdown(wait=False,
    # cancel_futures=True) annullo i blocchi non ancora partiti e NON aspetto
    # quelli in volo: le chiamate API gia' partite non sono interrompibili, ma
    # la cache atomica rende innocuo il loro eventuale completamento in background.
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=min(config.ASR_WORKER, n))
    futs = [ex.submit(lavora, i, c) for i, c in enumerate(chunks)]
    pending = set(futs)
    try:
        # NON uso `as_completed`: controllerebbe l'annullo SOLO quando un blocco
        # finisce, e se i blocchi sono fermi in una chiamata API bloccante (o in
        # un'attesa di retry) non finisce niente → l'annullo restava appeso per
        # decine di secondi. Con `wait(timeout=1)` mi sveglio ogni secondo e
        # controllo l'annullo a prescindere dai blocchi in volo → stop entro ~1s.
        while pending:
            if reporter.interrotto():
                raise Interrotto()
            done, pending = concurrent.futures.wait(
                pending, timeout=1.0,
                return_when=concurrent.futures.FIRST_COMPLETED)
            for fut in done:
                i, testo, chiamata_api = fut.result()   # propaga Interrotto / errori del worker
                parti[i] = testo
                if chiamata_api:
                    reporter.richiesta_trascrizione()    # quota: una per blocco trascritto via API
                completati += 1
                avanzamento(completati / max(1, n))
    finally:
        # Mollo SUBITO: i blocchi non ancora partiti si annullano; quelli in volo
        # finiscono in background (la cache atomica rende innocuo il loro arrivo).
        ex.shutdown(wait=False, cancel_futures=True)

    return "\n".join(parti[i] for i in sorted(parti) if parti[i])
