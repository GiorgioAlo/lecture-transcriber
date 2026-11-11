"""Suite di test OFFLINE (zero API, zero quota) per le fix del 2026-10-05.

Esegue con:  PYTHONPATH=. python tests_offline.py
Copre: collisione cartelle, guardia loop (truncation + soglie), dividi_blocchi,
genera_docx, valida_cookies, download .part, rilevamento lingua (campione).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from trascrittore import config, transcribe, download, textproc, aggiornamenti
from trascrittore.pipeline import Job, cartella_lavoro, identita_job, nome_pulito
from trascrittore import documents

ok = 0
ko = 0


def check(nome, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  PASS  {nome}")
    else:
        ko += 1
        print(f"  FAIL  {nome}")


print("\n#1 Collisione cartelle (due file diversi, stesso nome -> cartelle diverse)")
base = Path("cache")
a = Job(sorgente=Path(r"C:\Downloads\lezione.mp4"), nome="lezione")
b = Job(sorgente=Path(r"D:\Backup\lezione.mp4"), nome="lezione")
wa = cartella_lavoro(base, a.nome, identita_job(a))
wb = cartella_lavoro(base, b.nome, identita_job(b))
print("   ", wa.name, "|", wb.name)
check("stesso nome, sorgenti diverse -> cartelle DIVERSE", wa != wb)
check("nome leggibile conservato nel prefisso", wa.name.startswith("lezione_"))
# stessa sorgente -> stessa cartella (deve essere STABILE per la ripresa)
check("stessa sorgente -> stessa cartella (ripresa)", wa == cartella_lavoro(base, a.nome, identita_job(a)))
# link: identita = url
j = Job(url="https://youtube.com/watch?v=ABC", nome="Titolo bello")
check("link: identita = url", identita_job(j) == "https://youtube.com/watch?v=ABC")

print("\n#3 _collassa_ripetizioni (troncamento loop terminale + cap)")
# loop terminale: 'A. B. C.' legittimo poi il finale 'FIN1 FIN2' ripetuto 20x
corpo = " ".join(f"Frase numero {i} del corpo lezione importante." for i in range(1, 40))
finale = "Questo e il finale importante della lezione odierna. Grazie a tutti e arrivederci ragazzi."
loopato = corpo + " " + (" " + finale) * 20
pulito = transcribe._collassa_ripetizioni(loopato)
n_fin = pulito.count("Questo e il finale importante della lezione odierna")
print("   copie del finale dopo collasso:", n_fin)
check("il finale ripetuto 20x si riduce a <=3", 1 <= n_fin <= 3)
check("il corpo legittimo resta", "Frase numero 39 del corpo" in pulito)
check("la coda in loop viene rimossa", len(pulito.split()) < len(loopato.split()) * 0.6)

# Verifica sul FILE REALE loopato (Andrea Tocchetti), se ancora in cache.
reale = Path("cache/Andrea_Tocchetti_s_Personal_Room-20250110_1051-1/grezza.txt")
if reale.exists():
    raw = reale.read_text(encoding="utf-8")
    fix = transcribe._collassa_ripetizioni(raw)
    def uniche(s):
        fr = [x.strip() for x in re.split(r"(?<=[.?!])\s+", s) if len(x.strip()) > 20]
        return len(fr), len(set(fr))
    tp, up = uniche(raw)
    td, ud = uniche(fix)
    print(f"    REALE: parole {len(raw.split())}->{len(fix.split())}, frasi {tp}({up}u)->{td}({ud}u)")
    check("file reale: quasi tutte le frasi finali diventano uniche", td <= up + 5)

# ripetizione LEGITTIMA (2 volte) deve restare intatta
testo2 = "Ripeto questo concetto chiave due volte per enfasi didattica importante. " * 2 + "Poi vado avanti col resto della spiegazione tranquillamente."
r2 = transcribe._collassa_ripetizioni(testo2)
check("ripetizione legittima 2x conservata", r2.count("Ripeto questo concetto chiave") == 2)
# testo senza ripetizioni invariato (a meno di spazi)
semplice = "Prima frase tutta normale senza nulla di strano qui. Seconda frase diversa pure questa."
check("testo senza ripetizioni invariato", transcribe._collassa_ripetizioni(semplice).split() == semplice.split())

print("\n#7 _sospetto_loop (soglie e durata)")
veloce_corto = "x " * 160   # 30s di parlato veloce
check("coda corta 30s NON flaggata (falso positivo evitato)", transcribe._sospetto_loop(veloce_corto, 30) is False)
normale = "x " * 5000       # 38 min normale (~130 wpm)
check("blocco normale 38min NON flaggato", transcribe._sospetto_loop(normale, 38 * 60) is False)
loop = "x " * 31000         # 38 min loopato (~800 wpm)
check("blocco loopato 38min flaggato", transcribe._sospetto_loop(loop, 38 * 60) is True)
check("durata 0 (ffprobe ko) NON flaggata", transcribe._sospetto_loop("x " * 999, 0) is False)

print("\n#  dividi_blocchi (casi limite)")
check("vuoto -> nessun blocco", textproc.dividi_blocchi("") == [])
senza_punt = "parola " * 3000  # nessuna punteggiatura, > 5000 char
bl = textproc.dividi_blocchi(senza_punt)
check("testo lungo senza punteggiatura si spezza", len(bl) >= 2 and all(len(b) <= config.MAX_CARATTERI_BLOCCO for b in bl))
parola_monstre = "a" * 12000
blm = textproc.dividi_blocchi(parola_monstre)
check("parola gigantesca spezzata sotto il tetto", all(len(b) <= config.MAX_CARATTERI_BLOCCO for b in blm))

print("\n#9/#docx genera_docx (testo ostile non crasha)")
tmp = Path(tempfile.mkdtemp())
ostile = ("TITOLO IN MAIUSCOLO\n\nUn paragrafo normale con una domanda? Si, una risposta.\n\n"
          "- punto uno\n- punto due\n\nOK.\n\n" + config.MARCATORE_ERRORE + ": blocco 3 non elaborato.]\n")
out = tmp / "t.docx"
documents.genera_docx(ostile, out, "Titolo Lezione", "nota di prova")
check("docx creato e non vuoto", out.exists() and out.stat().st_size > 0)
check("'OK.' NON e' titolo", documents._sembra_titolo("OK.") is False)
check("'NON CAPISCO.' NON e' titolo", documents._sembra_titolo("NON CAPISCO.") is False)
check("'ARCHITETTURA' e' titolo", documents._sembra_titolo("ARCHITETTURA") is True)

print("\n#  formati dei documenti: docx / txt / md")
check("formati: vuoto -> solo Word", documents.normalizza_formati([]) == ["docx"])
check("formati: ordine fisso, niente doppioni, sconosciuti scartati",
      documents.normalizza_formati(["md", "pdf", "TXT", ".md", "word"]) == ["docx", "txt", "md"])
check("formati: stringa 'txt,md'", documents.normalizza_formati("txt,md") == ["txt", "md"])
check("percorso con un punto nel nome NON perde pezzi",
      documents.percorso_documento(tmp / "Lez. 3_IT", "md").name == "Lez. 3_IT.md")
testo_f = ("INTRODUZIONE:\nUsiamo *asterischi* e var_name. [00:10:30] Primo punto.\n"
           "Che cos'e' un attacco? Lo vediamo.\n- uno\n- due\n# non un titolo\n")
creati = documents.genera(testo_f, tmp / "Lez. 3_IT", "Lezione — Prova", "nota", ["txt", "md", "docx"])
check("genera: un file per formato, in ordine docx/txt/md",
      [p.suffix for p in creati] == [".docx", ".txt", ".md"] and all(p.exists() for p in creati))
txt = creati[1].read_text(encoding="utf-8")
check("txt: titolo + intestazione interna + punti elenco attaccati",
      txt.startswith("Lezione — Prova\n") and "\nINTRODUZIONE\n" in txt and "• uno\n• due" in txt)
check("txt: timestamp lasciato com'e'", "[00:10:30]" in txt)
md = creati[2].read_text(encoding="utf-8")
check("md: titolo, ## intestazione, elenco", md.startswith("# Lezione — Prova\n") and "## INTRODUZIONE" in md
      and "- uno\n- due" in md)
check("md: timestamp in grassetto, domanda in corsivo",
      "**[00:10:30]**" in md and "*Che cos'e' un attacco?*" in md)
check("md: asterischi/trattini bassi del testo neutralizzati", "\\*asterischi\\*" in md and "var\\_name" in md)
check("md: '#' a inizio paragrafo NON diventa un titolo", "\n\\# non un titolo" in md)
check("md: '2024.' a inizio paragrafo NON diventa un elenco", documents._md_riga("2024. Anno") == "2024\\. Anno")

print("\n#  note sulle parti non riuscite (riquadro a parte, lingua del documento)")
testo_n = ("Prima frase della lezione. Seconda frase.\n"
           f"{config.MARCATORE_ERRORE}: questa parte non è stata ripulita (Gemini era occupato); "
           "qui sotto c'è la trascrizione grezza, non corretta.]\n"
           "testo grezzo senza punteggiatura\n"
           f"{config.MARCATORE_FINE}: fine della parte non ripulita.]\n"
           "Il testo pulito riprende qui.\n"
           f"{config.MARCATORE_ERRORE}: questa parte non è stata tradotta (Gemini era occupato).]\n"
           "[⚠️ NOTE: this part was translated by Gemini]\n")
bl = documents._blocchi(testo_n, "it")
check("note: blocchi separati, mai dentro un paragrafo",
      [t for t, _ in bl] == ["para", "nota", "para", "fine", "para", "nota", "nota"]
      and not any("⚠" in c for t, c in bl if t == "para"))
check("note: in italiano per un documento italiano", bl[1][1].startswith("⚠️ NOTA: questa parte non è stata ripulita"))
check("note: in inglese per le altre lingue",
      documents._blocchi(testo_n, "de")[1][1].startswith("⚠️ NOTE: this part was not cleaned up")
      and documents._blocchi(testo_n, "en")[3][1] == "⚠️ End of the part that was not cleaned up.")
check("note: una nota sconosciuta resta com'e' (senza parentesi quadre)",
      bl[-1][1] == "⚠️ NOTE: this part was translated by Gemini")
creati_n = documents.genera(testo_n, tmp / "Note_EN", "Lezione — Note", "nota", ["docx", "txt", "md"], "en")
check("note: docx creato", creati_n[0].exists() and creati_n[0].stat().st_size > 0)
from docx import Document as _Doc
_pars = [p for p in _Doc(str(creati_n[0])).paragraphs if "⚠" in p.text]
check("note docx: riquadro (sfondo + bordo) e grassetto",
      len(_pars) == 4 and all(p._p.pPr.find(qn_shd) is not None for p in _pars for qn_shd in [
          "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd"])
      and _pars[0].runs[0].bold and _pars[1].runs[0].italic)
md_n = creati_n[2].read_text(encoding="utf-8")
check("note md: citazione in grassetto / corsivo",
      "\n> **⚠️ NOTE: this part was not cleaned up" in md_n and "\n> *⚠️ End of the part" in md_n)
txt_n = creati_n[1].read_text(encoding="utf-8")
check("note txt: paragrafo a se' con righe vuote attorno",
      "\n\n⚠️ NOTE: this part was not cleaned up (Gemini was busy). Below is the raw, uncorrected transcription.\n\n" in txt_n)

print("\n#6 download _scaricati_completi (esclude i parziali)")
dtmp = Path(tempfile.mkdtemp())
(dtmp / "scaricato.webm.part").write_text("parziale")
check("solo un .part -> nessun file completo", download._scaricati_completi(dtmp) == [])
(dtmp / "scaricato.m4a").write_text("completo")
done = download._scaricati_completi(dtmp)
check("file completo riconosciuto, .part ignorato", len(done) == 1 and done[0].name == "scaricato.m4a")

print("\n#  rileva_lingua _campione_lingua (inizio + centro)")
lungo = ("INIZIO " * 200) + ("CENTRO " * 200) + ("FINE " * 200)
camp = textproc._campione_lingua(lungo, quanti=400)
check("campione pesca anche dal centro", "CENTRO" in camp)
check("campione limitato in lunghezza", len(camp) <= 420)

print("\n#  valida_cookies (livelli di forma)")
ct = Path(tempfile.mkdtemp())
non_cookie = ct / "a_caso.txt"; non_cookie.write_text("ciao questo non e un cookie\n")
check("file a caso -> rifiutato", download.valida_cookies(str(non_cookie))[0] is False)
solo_google = ct / "g.txt"
solo_google.write_text(".google.com\tTRUE\t/\tFALSE\t0\tNID\tabc\n")
check("cookie solo google -> rifiutato (niente webex)", download.valida_cookies(str(solo_google))[0] is False)
webex_ok = ct / "w.txt"
webex_ok.write_text("# Netscape HTTP Cookie File\n.webex.com\tTRUE\t/\tTRUE\t0\tJSESSIONID\txyz\n")
check("cookie webex veri -> accettati", download.valida_cookies(str(webex_ok))[0] is True)
testo_nomina_webex = ct / "n.txt"
testo_nomina_webex.write_text("parlo di webex.com ma non ho cookie veri\n")
check("testo che nomina webex -> rifiutato", download.valida_cookies(str(testo_nomina_webex))[0] is False)

print("\n#  aggiornamenti: confronto versioni (semver)")
check("1.1.0 > 1.0.0", aggiornamenti.e_piu_recente("1.1.0", "1.0.0") is True)
check("v1.0.1 > 1.0.0 (prefisso v)", aggiornamenti.e_piu_recente("v1.0.1", "1.0.0") is True)
check("1.0.0 non > 1.0.0 (uguale)", aggiornamenti.e_piu_recente("1.0.0", "1.0.0") is False)
check("1.0.0 non > 1.1.0 (piu' vecchia)", aggiornamenti.e_piu_recente("1.0.0", "1.1.0") is False)
check("2.0.0 > 1.9.9 (non confronto stringhe)", aggiornamenti.e_piu_recente("2.0.0", "1.9.9") is True)
check("1.10.0 > 1.9.0 (numerico, non lessicale)", aggiornamenti.e_piu_recente("1.10.0", "1.9.0") is True)
check("1.1.0-beta ignora il suffisso", aggiornamenti.versione_tupla("1.1.0-beta") == (1, 1, 0))
check("tag illeggibile -> (0,) (mai piu' recente)", aggiornamenti.e_piu_recente("boh", "1.0.0") is False)

print("\n#  aggiornamenti: throttle (un controllo al giorno)")
check("niente stato -> controlla", aggiornamenti._deve_controllare({}, "2026-10-15") is True)
check("gia' controllato oggi -> salta", aggiornamenti._deve_controllare({"ultimo_controllo": "2026-10-15"}, "2026-10-15") is False)
check("controllato ieri -> ricontrolla", aggiornamenti._deve_controllare({"ultimo_controllo": "2026-10-14"}, "2026-10-15") is True)

print("\n#  aggiornamenti: controlla() dormiente se repo non configurato")
_o, _r = config.GITHUB_OWNER, config.GITHUB_REPO
config.GITHUB_OWNER, config.GITHUB_REPO = "", ""
check("repo vuoto -> None senza toccare la rete", aggiornamenti.controlla() is None)
config.GITHUB_OWNER, config.GITHUB_REPO = _o, _r

print("\n#  aggiornamenti: URL del form di segnalazione")
_u, _c = config.URL_FORM_SEGNALAZIONE, config.FORM_CAMPO_VERSIONE
config.URL_FORM_SEGNALAZIONE, config.FORM_CAMPO_VERSIONE = "", ""
check("form non configurato -> None", aggiornamenti.url_segnalazione("1.0.0") is None)
config.URL_FORM_SEGNALAZIONE = "https://docs.google.com/forms/d/e/XYZ/viewform"
config.FORM_CAMPO_VERSIONE = "entry.123"
u = aggiornamenti.url_segnalazione("1.2.3")
check("versione pre-compilata nell'URL", u is not None and "entry.123=1.2.3" in u and "usp=pp_url" in u)
config.FORM_CAMPO_VERSIONE = ""
u2 = aggiornamenti.url_segnalazione("1.2.3")
check("senza campo -> form nudo (niente query pp_url)", u2 is not None and "pp_url" not in u2)
config.URL_FORM_SEGNALAZIONE, config.FORM_CAMPO_VERSIONE = _u, _c

print("\n#  transcribe: risposta Gemini bloccata/vuota (niente crash, errore chiaro)")
# Risposte Gemini finte: riproducono i casi che prima mandavano l'app in crash
# ('NoneType' object is not subscriptable) perche' si faceva candidates[0] a vuoto.
class _FintaParte:
    def __init__(self, text=None, at=None):
        self.text = text
        self.audio_transcription = at

class _FintoContenuto:
    def __init__(self, parts):
        self.parts = parts

class _FintoCandidato:
    def __init__(self, parts=None, finish_reason="STOP"):
        self.content = _FintoContenuto(parts) if parts is not None else None
        self.finish_reason = finish_reason

class _FintoFeedback:
    def __init__(self, block_reason):
        self.block_reason = block_reason

class _FintaRisposta:
    def __init__(self, candidates=None, prompt_feedback=None):
        self.candidates = candidates
        self.prompt_feedback = prompt_feedback

# 1) PROMPT bloccato: candidates=None (il caso del video reaction segnalato)
bloccata_prompt = _FintaRisposta(candidates=None,
                                 prompt_feedback=_FintoFeedback("SAFETY"))
check("candidates=None NON crasha, estrae ''", transcribe._estrai_transcript(bloccata_prompt) == "")
check("prompt_feedback.block_reason riconosciuto", transcribe._motivo_blocco(bloccata_prompt) == "SAFETY")

# 2) CANDIDATO bloccato: content/parts None, finish_reason non-STOP
bloccata_cand = _FintaRisposta(candidates=[_FintoCandidato(parts=None, finish_reason="RECITATION")])
check("content.parts=None NON crasha, estrae ''", transcribe._estrai_transcript(bloccata_cand) == "")
check("finish_reason RECITATION riconosciuto come blocco", transcribe._motivo_blocco(bloccata_cand) == "RECITATION")

# 3) risposta NORMALE: testo estratto, nessun blocco
ok_resp = _FintaRisposta(candidates=[_FintoCandidato(parts=[_FintaParte(text="Ciao a tutti.")])])
check("risposta normale: testo estratto", transcribe._estrai_transcript(ok_resp) == "Ciao a tutti.")
check("risposta normale: nessun motivo di blocco", transcribe._motivo_blocco(ok_resp) is None)

# 4) vuoto transitorio (nessun candidato, nessun block_reason) != blocco
vuota = _FintaRisposta(candidates=[], prompt_feedback=None)
check("vuoto senza block_reason -> NON e' un blocco (ritentabile)", transcribe._motivo_blocco(vuota) is None)

print("\n#  gemini.con_retry: ContenutoBloccato NON viene ritentato")
from trascrittore.gemini import con_retry
from trascrittore.errors import ContenutoBloccato
_chiamate = {"n": 0}
def _azione_bloccata():
    _chiamate["n"] += 1
    raise ContenutoBloccato("rifiutato")
try:
    con_retry(_azione_bloccata, "test", max_tentativi=5)
    check("con_retry rilancia ContenutoBloccato", False)
except ContenutoBloccato:
    check("con_retry rilancia ContenutoBloccato", True)
check("ContenutoBloccato: una sola chiamata (nessun retry)", _chiamate["n"] == 1)

# contro-prova: un errore generico viene ritentato fino a max_tentativi
_chiamate2 = {"n": 0}
def _azione_transitoria():
    _chiamate2["n"] += 1
    raise RuntimeError("vuota")
try:
    con_retry(_azione_transitoria, "test", max_tentativi=3)
except RuntimeError:
    pass
check("errore generico ritentato max_tentativi volte", _chiamate2["n"] == 3)

print("\n#  transcribe._carica_file: l'upload riprova su un blip di rete (non fa cadere la lezione)")
class _FakeState:
    def __init__(self, nm): self.name = nm
class _FakeFile:
    def __init__(self, stato): self.state = _FakeState(stato); self.name = "files/x"
class _FakeFiles:
    def __init__(self): self.tent = 0
    def upload(self, file=None):
        self.tent += 1
        if self.tent == 1:
            raise RuntimeError("Server disconnected without sending a response")
        return _FakeFile("ACTIVE")
    def get(self, name=None): return _FakeFile("ACTIVE")
class _FakeClient:
    def __init__(self): self.files = _FakeFiles()
class _RepT:
    def log(self, m): pass
    def interrotto(self): return False
_fc = _FakeClient()
_f = transcribe._carica_file(_fc, Path("x.m4a"), _RepT())
check("upload: 1 blip -> riprova e torna ACTIVE", _f.state.name == "ACTIVE" and _fc.files.tent == 2)

print("\n#  textproc: pulizia fallita -> TRASCRIZIONE GREZZA nel testo (non un buco)")
class _CliFail:
    class models:
        @staticmethod
        def generate_content(**kw): raise RuntimeError("503 high demand")
class _RepTx:
    def log(self, m): pass
    def interrotto(self): return False
_old_mt = config.MAX_TENTATIVI_TESTO
config.MAX_TENTATIVI_TESTO = 1          # 1 tentativo, nessuna attesa di backoff nel test
_raw_in = "Prima frase grezza del blocco di prova. Seconda frase grezza importante."
_out, _err = textproc.pulisci(_CliFail(), _raw_in, "it", "", _RepTx())
check("pulizia fallita: conta il blocco fallito", _err >= 1)
check("pulizia fallita: il testo GREZZO finisce nel risultato", "Prima frase grezza del blocco di prova" in _out)
check("pulizia fallita: c'e' la nota/marcatore", config.MARCATORE_ERRORE in _out)
check("pulizia fallita: la parte grezza e' chiusa DOPO il testo grezzo",
      _out.index("Prima frase grezza del blocco di prova") < _out.index(config.MARCATORE_FINE))
_out2, _err2 = textproc.traduci(_CliFail(), _raw_in, "it", "en", "", _RepTx())
check("traduzione fallita: conta il blocco", _err2 >= 1)
check("traduzione fallita: nota presente", config.MARCATORE_ERRORE in _out2)
check("traduzione fallita: NON mette il grezzo (lingua sbagliata)", "Prima frase grezza del blocco di prova" not in _out2)
config.MAX_TENTATIVI_TESTO = _old_mt

print("\n#  gemini.IMPOSTAZIONI_SICUREZZA: filtri a BLOCK_NONE")
from trascrittore.gemini import IMPOSTAZIONI_SICUREZZA
check("4 categorie coperte", len(IMPOSTAZIONI_SICUREZZA) == 4)
check("tutte BLOCK_NONE", all(str(s.threshold).endswith("BLOCK_NONE") for s in IMPOSTAZIONI_SICUREZZA))

print("\n#  punto 8 A: modello Gemini RITIRATO (404 NOT_FOUND confermato da models.get)")
from google.genai import errors as _gerr
from trascrittore import gemini as _gem, coda as _coda
from trascrittore.errors import ModelloNonDisponibile
_old_attesa = _gem._attendi_annullabile
_gem._attendi_annullabile = lambda s, i=None: None      # niente attese reali nei test

def _err404(nome):
    return _gerr.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message":
        f"models/{nome} is not found for API version v1beta, or is not supported for generateContent."}})

class _CliModelli:
    """Client finto: `esiste` decide cosa risponde models.get (True / False / 'rete')."""
    def __init__(self, esiste):
        self.n_gen = 0; self.n_get = 0; self._esiste = esiste
        cli = self
        class models:
            @staticmethod
            def generate_content(**kw):
                cli.n_gen += 1
                raise _err404(kw.get("model", "gemini-x"))
            @staticmethod
            def get(model):
                cli.n_get += 1
                if cli._esiste == "rete":
                    raise ConnectionError("rete giu'")
                if cli._esiste:
                    return {"name": f"models/{model}"}
                raise _gerr.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND",
                                                        "message": f"Model is not found: models/{model}"}})
        self.models = models

def _prova(cli, usato="gemini-vecchio", atteso="gemini-vecchio", passa_client=True, max_t=4):
    try:
        _gem.con_retry(lambda: cli.models.generate_content(model=usato), "test", max_tentativi=max_t,
                       client=cli if passa_client else None, modello=atteso if passa_client else None)
    except Exception as e:
        return e

_c = _CliModelli(esiste=False)
_e = _prova(_c)
check("ritiro confermato -> ModelloNonDisponibile", isinstance(_e, ModelloNonDisponibile))
check("ritiro confermato -> 1 sola chiamata (niente retry)", _c.n_gen == 1 and _c.n_get == 1)
check("ritiro confermato -> nome del modello nell'eccezione", getattr(_e, "modello", None) == "gemini-vecchio")

_c = _CliModelli(esiste=True)
_e = _prova(_c)
check("404 ma models.get dice che ESISTE -> retry normali",
      _c.n_gen == 4 and not isinstance(_e, ModelloNonDisponibile))

_c = _CliModelli(esiste="rete")
_e = _prova(_c)
check("404 ma verifica fallita per rete -> retry normali",
      _c.n_gen == 4 and not isinstance(_e, ModelloNonDisponibile))

_c = _CliModelli(esiste=False)
_e = _prova(_c, passa_client=False)
check("senza client/modello (es. upload) -> comportamento di sempre", _c.n_gen == 4 and _c.n_get == 0)

_c = _CliModelli(esiste=False)
_e = _prova(_c, usato="gemini-altro")
check("404 che cita un ALTRO nome -> nessuna verifica, retry normali", _c.n_gen == 4 and _c.n_get == 0)
check("nome-prefisso non basta (gemini-vecchio vs gemini-vecchio-2)",
      not _gem._sembra_modello_ritirato(_err404("gemini-vecchio-2"), "gemini-vecchio"))
check("503 -> non e' un ritiro", not _gem._sembra_modello_ritirato(
      _gerr.ServerError(503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "high demand"}}),
      "gemini-x"))

# FASE TESTO: la pulizia si FERMA (niente nota "Gemini era occupato")
_old_tm = config.TEXT_MODEL
config.TEXT_MODEL = "gemini-vecchio"
_c = _CliModelli(esiste=False)
try:
    textproc.pulisci(_c, _raw_in, "it", "", _RepTx())
    check("pulizia con modello ritirato -> la lezione si ferma", False)
except ModelloNonDisponibile:
    check("pulizia con modello ritirato -> la lezione si ferma", True)
_c = _CliModelli(esiste=False)
try:
    textproc.rileva_lingua(_c, _raw_in * 5)
    check("rileva_lingua non maschera il ritiro con la lingua di default", False)
except ModelloNonDisponibile:
    check("rileva_lingua non maschera il ritiro con la lingua di default", True)
config.TEXT_MODEL = _old_tm

# CODA: al primo modello ritirato si ferma TUTTA la coda (come il limite giornaliero)
class _PfFinto:
    def __init__(self, *a, **k): pass
    def start(self): return self
    def attendi_pronta(self, k): pass
    def completata(self, k): pass
    def stop(self): pass
_old = (_coda.Prefetcher, _coda.crea_client, _coda.pipeline.fase_trascrizione,
        _coda.cartella_lavoro, _coda.identita_job, _coda.modelli.prepara)
_coda.modelli.prepara = lambda *a, **k: None          # niente rete nei test
_tmp = Path(tempfile.mkdtemp())
_partite = []
def _fase_finta(job, *a, **k):
    _partite.append(job)
    raise ModelloNonDisponibile("gemini-vecchio")
_coda.Prefetcher = _PfFinto
_coda.crea_client = lambda *a, **k: object()
_coda.pipeline.fase_trascrizione = _fase_finta
_coda.identita_job = lambda job: job.nome
_coda.cartella_lavoro = lambda base, nome, ident: _tmp / nome
class _J:
    def __init__(self, n): self.nome = n
    def __repr__(self): return self.nome
_jobs = [_J("L1"), _J("L2"), _J("L3")]
_esiti = []
try:
    _coda.esegui_coda(_jobs, ["k1", "k2", "k3"], "chiave", lambda k: _RepTx(), _tmp,
                      al_termine=lambda key, ris, err: _esiti.append((key, type(err).__name__)))
finally:
    (_coda.Prefetcher, _coda.crea_client, _coda.pipeline.fase_trascrizione,
     _coda.cartella_lavoro, _coda.identita_job, _coda.modelli.prepara) = _old
check("coda: si ferma alla prima lezione", _partite == [_jobs[0]])
check("coda: la scheda riceve ModelloNonDisponibile", _esiti == [("k1", "ModelloNonDisponibile")])

# "no longer available to new users": models.get dice che ESISTE, ma la frase basta
class _CliChiuso(_CliModelli):
    def __init__(self):
        super().__init__(esiste=True)
        cli = self
        class models:
            @staticmethod
            def generate_content(**kw):
                cli.n_gen += 1
                raise _gerr.ClientError(404, {"error": {"code": 404, "status": "NOT_FOUND", "message":
                    "This model models/gemini-vecchio is no longer available to new users. Please update "
                    "your code to use models/gemini-nuovo-preview for the latest features."}})
            get = staticmethod(lambda model: {"name": model})
        self.models = models
_c = _CliChiuso()
_e = _prova(_c)
check("'no longer available' -> ModelloNonDisponibile anche se models.get dice che esiste",
      isinstance(_e, ModelloNonDisponibile) and _c.n_gen == 1)
check("'no longer available' -> sostituto suggerito da Google letto dal messaggio",
      getattr(_e, "suggerito", None) == "gemini-nuovo-preview")
_gem._attendi_annullabile = _old_attesa

print("\n#  punto 8 B: modelli.json (GitHub -> cache -> config.py)")
import json as _json
from trascrittore import modelli as _mod
_REPO_FILE = Path(__file__).resolve().parent / "modelli.json"
_ufficiale = _json.loads(_REPO_FILE.read_text(encoding="utf-8"))
_v = _mod.valida(_ufficiale)
check("modelli.json del repo: tutti e 3 i ruoli validi", set(_v) == {"asr", "fallback", "text"})
check("modelli.json == config.py: nomi dei modelli",
      (_v["asr"]["model"], _v["fallback"]["model"], _v["text"]["model"])
      == (config.ASR_MODEL, config.TRANSCRIBE_MODEL, config.TEXT_MODEL))
check("modelli.json == config.py: rpd asr = RPD_TRASCRIZIONE", _v["asr"]["rpd"] == config.RPD_TRASCRIZIONE)
check("modelli.json == config.py: rpm -> stessi worker (12 audio, 4 testo)",
      _mod.worker_asr(_v["asr"]["rpm"]) == config.ASR_WORKER
      and _mod.worker_testo(_v["text"]["rpm"]) == config.WORKER_PARALLELI)

_snap = (config.ASR_MODEL, config.TRANSCRIBE_MODEL, config.TEXT_MODEL, config.RPD_TRASCRIZIONE,
         config.ASR_WORKER, config.WORKER_PARALLELI)
def _stato():
    return (config.ASR_MODEL, config.TRANSCRIBE_MODEL, config.TEXT_MODEL, config.RPD_TRASCRIZIONE,
            config.ASR_WORKER, config.WORKER_PARALLELI)

_mod.applica(_v)
check("applicare il file ufficiale non cambia niente", _stato() == _snap)

check("valida: nome non gemini- scartato", "asr" not in _mod.valida({"asr": {"model": "gpt-4"}}))
check("valida: maiuscole/spazi scartati", "asr" not in _mod.valida({"asr": {"model": "gemini-3 Flash"}}))
check("valida: file non-dizionario -> niente", _mod.valida(["x"]) == {} and _mod.valida(None) == {})
check("valida: rpm strano ignorato, nome tenuto",
      _mod.valida({"text": {"model": "gemini-x", "rpm": "15"}}) == {"text": {"model": "gemini-x"}})

class _CliGet:
    def __init__(self, esistenti):
        es = set(esistenti)
        class models:
            @staticmethod
            def get(model):
                if model not in es:
                    raise RuntimeError("404")
                return {"name": model}
        self.models = models

_nuovo = {"asr": {"model": "gemini-nuovo-flash", "rpm": 5, "rpd": 20},
          "text": {"model": "gemini-nuovo-lite", "rpm": 5, "rpd": 20}}
_mod.applica(_mod.valida(_nuovo), _CliGet({"gemini-nuovo-flash", "gemini-nuovo-lite"}))
check("nome nuovo confermato da Google -> usato", config.ASR_MODEL == "gemini-nuovo-flash"
      and config.TEXT_MODEL == "gemini-nuovo-lite")
check("limiti del modello nuovo: rpd 20, worker 2 audio / 1 testo",
      (config.RPD_TRASCRIZIONE, config.ASR_WORKER, config.WORKER_PARALLELI) == (20, 2, 1))
check("ruolo assente nel file -> resta quello di config.py", config.TRANSCRIBE_MODEL == _snap[1])

_mod.applica(_mod.valida(_nuovo), _CliGet({"gemini-nuovo-lite"}))
check("nome che Google non conosce (refuso) -> resta il vecchio, con i suoi limiti",
      config.ASR_MODEL == _snap[0] and config.RPD_TRASCRIZIONE == _snap[3] and config.ASR_WORKER == _snap[4])
check("...e l'altro ruolo, valido, si applica lo stesso", config.TEXT_MODEL == "gemini-nuovo-lite")
_mod.ripristina()
check("ripristina -> valori di config.py", _stato() == _snap)

# ordine delle fonti: GitHub -> cache -> config.py (rete e cache finte)
_old_net = (_mod._scarica, _mod._leggi_cache, _mod._scrivi_cache)
_scritta = {}
def _rete_giu():
    raise OSError("niente rete")
_mod._scrivi_cache = lambda d: _scritta.update(d)
try:
    _mod._scarica = lambda: _nuovo
    _mod._leggi_cache = lambda: None
    _mod.prepara(_CliGet({"gemini-nuovo-flash", "gemini-nuovo-lite"}), forza=True)
    check("GitHub risponde -> si usa e si salva in cache",
          config.ASR_MODEL == "gemini-nuovo-flash" and _scritta.get("asr", {}).get("model") == "gemini-nuovo-flash")
    _mod._scarica = _rete_giu
    _mod._leggi_cache = lambda: {"text": {"model": "gemini-dalla-cache", "rpm": 15}}
    _mod.prepara(_CliGet({"gemini-dalla-cache"}), forza=True)
    check("niente rete -> ultima copia buona in cache",
          config.TEXT_MODEL == "gemini-dalla-cache" and config.ASR_MODEL == _snap[0])
    _mod._scarica = lambda: {"asr": "rotto"}
    _mod._leggi_cache = lambda: None
    _mod.prepara(None, forza=True)
    check("file rotto e niente cache -> config.py", _stato() == _snap)
    _mod.prepara(None)
    check("una volta per processo: seconda prepara() non rilegge", _stato() == _snap)
finally:
    _mod._scarica, _mod._leggi_cache, _mod._scrivi_cache = _old_net
    _mod.ripristina()
    _mod.invalida()

print("\n#  punto 8 B.5: modello che rifiuta thinking_config -> si riprova senza")
class _CliThinking:
    """Rifiuta thinking_config come gemini-2.5-flash-lite (misurato)."""
    def __init__(self):
        self.chiamate = []
        cli = self
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                cli.chiamate.append(config.thinking_config is not None)
                if config.thinking_config is not None:
                    raise _gerr.ClientError(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                        "message": "The thinking budget 128 is invalid. Please choose a value between 512 and 24576."}})
                return _RispostaOk()
        self.models = models
class _RispostaOk:
    candidates = [type("C", (), {"finish_reason": "STOP"})()]
_old_estrai = transcribe._estrai_transcript
transcribe._estrai_transcript = lambda r: "testo trascritto"
try:
    _ct = _CliThinking()
    _cfg = {"thinking_config": transcribe.types.ThinkingConfig(thinking_budget=128)}
    transcribe._SENZA_THINKING.discard("gemini-prova")
    _t1 = transcribe._genera(_ct, "gemini-prova", None, _cfg, _RepTx(), "test")
    check("rifiuto thinking -> riprova subito senza e riesce", _t1[0] == "testo trascritto"
          and _ct.chiamate == [True, False])
    _ct.chiamate.clear()
    transcribe._genera(_ct, "gemini-prova", None, _cfg, _RepTx(), "test")
    check("la volta dopo non lo manda proprio (una chiamata sola)", _ct.chiamate == [False])
    check("il dizionario di configurazione del chiamante resta intatto", "thinking_config" in _cfg)
finally:
    transcribe._estrai_transcript = _old_estrai
    transcribe._SENZA_THINKING.discard("gemini-prova")

print("\n#  punto 6: frasi per l'utente come codici traducibili (Messaggio)")
from trascrittore.errors import Messaggio, DownloadFallito, Interrotto as _Interrotto
_mm = Messaggio("Ciao {nome}", "py.prova", nome="x")
check("Messaggio e' una stringa normale (CLI/log invariati)", _mm == "Ciao {nome}" and isinstance(_mm, str))
check("Messaggio porta codice e valori", _mm.codice == "py.prova" and _mm.valori == {"nome": "x"})
_df = DownloadFallito(Messaggio("Il video è privato", "py.dl.private"))
check("l'errore ricorda il codice della sua frase", _df.codice == "py.dl.private" and str(_df) == "Il video è privato")
check("errore con frase semplice -> nessun codice", DownloadFallito("testo").codice is None)
check("errore senza argomenti (Interrotto) -> nessun codice", _Interrotto().codice is None)
_mb = transcribe._messaggio_blocco("RECITATION")
check("blocco copyright -> codice + motivo", _mb.codice == "py.blocked.copyright" and _mb.valori == {"motivo": "RECITATION"})
check("blocco: frase italiana invariata", "copyright" in _mb and "RECITATION" in _mb)
check("cookie non validi -> codice", download.valida_cookies(str(non_cookie))[1].codice == "py.cookie.format")
_mnd = ModelloNonDisponibile("gemini-x")
check("ModelloNonDisponibile -> codice + modello", _mnd.codice == "py.err.model.d" and _mnd.valori == {"modello": "gemini-x"})

# Ogni codice usato nel codice Python ha la traduzione IT ed EN nella pagina
_html = (Path(__file__).resolve().parent / "ui" / "index.html").read_text(encoding="utf-8")
_it = _html[_html.index("  it: {"):_html.index("  en: {")]
_en = _html[_html.index("  en: {"):_html.index("\n};", _html.index("  en: {"))]
_k_it = set(re.findall(r"'(py\.[\w.]+)'\s*:", _it))
_k_en = set(re.findall(r"'(py\.[\w.]+)'\s*:", _en))
_usati = set()
for _p in [Path(__file__).resolve().parent / "app.py", *(Path(__file__).resolve().parent / "trascrittore").glob("*.py")]:
    _usati |= set(re.findall(r'"(py\.[\w.]+[\w])"', _p.read_text(encoding="utf-8")))
_usati.discard("py.badfile")
_usati |= {f"py.badfile{q}.{x}" for q in ("1", "N") for x in ("t", "d")}   # composti in app.py
print("\n#  punto 9: versione da una fonte sola (config.VERSION)")
import tomllib as _toml
_pp = _toml.loads((Path(__file__).resolve().parent / "pyproject.toml").read_text(encoding="utf-8"))
check("pyproject: niente versione scritta a mano", "version" not in _pp["project"])
check("pyproject: versione dinamica letta da trascrittore.config.VERSION",
      "version" in _pp["project"].get("dynamic", [])
      and _pp["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "trascrittore.config.VERSION"})
check("config.VERSION e' semver X.Y.Z", re.fullmatch(r"\d+\.\d+\.\d+", config.VERSION) is not None)

check("IT ed EN hanno le stesse chiavi py.*", _k_it == _k_en)
check("ogni codice usato in Python ha la sua traduzione", not (_usati - _k_it))

print("\n#  punto 2: segni del tempo nei documenti (~10 min)")
from trascrittore import tempi as _tempi
check("etichette: 10 min / 1 h / 1 h 10 min / 2 h 10 min",
      [_tempi.etichetta(s) for s in (600, 3600, 4200, 7800)]
      == ["~10 min", "~1 h", "~1 h 10 min", "~2 h 10 min"])
_p95 = [(570.0, 9000)] * 10                                     # 95 min = 10 pezzi da 9:30
_s95 = _tempi.posizioni(_p95)
check("95 min -> segni da ~10 a ~1 h 30 min (9)",
      [e for _, e in _s95] == ["~10 min", "~20 min", "~30 min", "~40 min", "~50 min", "~1 h",
                               "~1 h 10 min", "~1 h 20 min", "~1 h 30 min"])
check("~10 min cade nel 2o pezzo, in proporzione (9000+30/570*9000)",
      abs(_s95[0][0] - (9000 + 30 / 570 * 9000) / 90000) < 1e-9)
check("lezione sotto i 10 minuti -> nessun segno", _tempi.posizioni([(480.0, 5000)]) == [])
check("niente segno nell'ultimo minuto", [e for _, e in _tempi.posizioni([(630.0, 5000)])] == [])
check("niente mappa -> nessun segno", _tempi.posizioni(None) == [])
_muto = _tempi.posizioni([(600.0, 6000), (600.0, 0), (600.0, 6000)])
check("pezzo muto: si tiene conto del silenzio (~10 e ~20 nello stesso punto)",
      [round(f, 3) for f, _ in _muto] == [0.5, 0.5])
check("spezzone che parte al minuto 5: etichette = tempi del VIDEO",
      [e for _, e in _tempi.posizioni([(1800.0, 9000)], 300)] == ["~10 min", "~20 min", "~30 min"])

_tdir = Path(tempfile.mkdtemp())
_parti = ["a" * 100, "", "b" * 50]
_tempi.salva(_tdir, [600.0, 600.0, 600.0], _parti)
_grezza = "\n".join(p for p in _parti if p)
check("mappa salvata e riletta (coerente con la grezza)",
      _tempi.carica(_tdir, _grezza) == [(600.0, 100), (600.0, 0), (600.0, 50)])
check("grezza diversa (mappa vecchia) -> ignorata", _tempi.carica(_tdir, "x" * 5000) is None)
_tempi.salva(_tdir, [600.0, 0.0], ["a", "b"])
check("durata illeggibile -> niente mappa", not (_tdir / _tempi.FILE).exists()
      and _tempi.carica(_tdir, "a\nb") is None)

_frasi = " ".join(f"Frase numero {i} della lezione." for i in range(1, 41))
_ins = _tempi.inserisci(_frasi, [(0.5, "~10 min")])
_righe = _ins.split("\n")
check("segno inserito come riga a se'", "[⏱ ~10 min]" in _righe and len(_righe) == 3)
check("segno all'inizio di una frase, circa a meta' testo",
      _righe[0].endswith(".") and _righe[2].startswith("Frase numero 2")
      and abs(len(_righe[0]) - len(_frasi) / 2) < 40)
check("parole invariate (solo una riga in piu')",
      _ins.replace("\n[⏱ ~10 min]\n", " ") == _frasi)
check("nessun segno -> testo identico", _tempi.inserisci(_frasi, []) == _frasi)
_con_nota = ("Prima frase. Seconda frase.\n"
             f"{config.MARCATORE_ERRORE}: questa parte non è stata tradotta (Gemini era occupato).]\n"
             "Terza frase. Quarta frase.")
_ins_n = _tempi.inserisci(_con_nota, [(0.5, "~10 min")])
check("mai dentro una nota (la riga-nota resta intera)",
      any(r.startswith(config.MARCATORE_ERRORE) and r.endswith("occupato).]") for r in _ins_n.split("\n"))
      and "[⏱ ~10 min]" in _ins_n)
_doppi = _tempi.inserisci("Unica frase corta.", [(0.4, "~10 min"), (0.6, "~20 min")])
check("due segni sulla stessa frase -> uno solo", _doppi.count("[⏱") == 1)

_doc_t = _tempi.inserisci(_frasi, [(0.5, "~1 h 10 min")])
_cr = documents.genera(_doc_t, tmp / "Tempi_IT", "Lezione — Tempi", "nota", ["docx", "txt", "md"], "it")
_paras = [p for p in _Doc(str(_cr[0])).paragraphs if p.text.strip()]
_pt = [p for p in _paras if p.text == "⏱ ~1 h 10 min"]
check("docx: segno come paragrafo a se', piccolo e grigio",
      len(_pt) == 1 and _pt[0].runs[0].font.size.pt == 9
      and str(_pt[0].runs[0].font.color.rgb) == "808080"
      and not any("[⏱" in p.text for p in _paras))
_txt_t = _cr[1].read_text(encoding="utf-8")
check("txt: riga del segno separata dal testo", "\n\n⏱ ~1 h 10 min\n\n" in _txt_t)
check("md: segno in corsivo con la tilde neutralizzata",
      "\n\n*⏱ \\~1 h 10 min*\n\n" in _cr[2].read_text(encoding="utf-8"))

print("\n#  pausa a meta' lezione: blocco senza parlato (vuoto) != errore")
import tempfile as _tf
from trascrittore.errors import NessunParlato
_old_retry, _old_carica, _old_gen = transcribe.con_retry, transcribe._carica_file, transcribe._genera
_old_guardia, _old_durata = transcribe._trascrivi_con_guardia, transcribe.audio.durata
class _CliRisp:
    """Client finto: generate_content torna sempre la risposta data."""
    def __init__(self, risp):
        self.n = 0
        cli = self
        class models:
            @staticmethod
            def generate_content(model, contents, config):
                cli.n += 1
                return risp
        self.models = models
class _CliDel:
    class files:
        @staticmethod
        def delete(name=None): pass
class _RepP:
    def __init__(self): self.righe = []
    def log(self, m): self.righe.append(m)
    def interrotto(self): return False
    def richiesta_trascrizione(self): pass
try:
    # _genera: con_retry ridotto a UNA chiamata (cosi' un errore esce subito, senza attese)
    transcribe.con_retry = lambda azione, *a, **k: azione()
    _muta = _FintaRisposta(candidates=[_FintoCandidato(parts=[], finish_reason="STOP")])
    _cm = _CliRisp(_muta)
    check("vuoto + STOP (pausa) -> testo vuoto, NON errore",
          transcribe._genera(_cm, "m", None, {}, _RepP(), "t") == ("", "STOP") and _cm.n == 1)
    _cm2 = _CliRisp(_FintaRisposta(candidates=[_FintoCandidato(parts=[], finish_reason="FinishReason.STOP")]))
    check("vuoto + FinishReason.STOP (enum vero) -> testo vuoto",
          transcribe._genera(_cm2, "m", None, {}, _RepP(), "t") == ("", "STOP"))
    for _nome, _r in (("nessun candidato", _FintaRisposta(candidates=[])),
                      ("finish MAX_TOKENS", _FintaRisposta(candidates=[_FintoCandidato(parts=[], finish_reason="MAX_TOKENS")])),
                      ("finish OTHER", _FintaRisposta(candidates=[_FintoCandidato(parts=[], finish_reason="OTHER")]))):
        try:
            transcribe._genera(_CliRisp(_r), "m", None, {}, _RepP(), "t")
            check(f"vuoto con {_nome} -> resta errore ritentabile", False)
        except RuntimeError:
            check(f"vuoto con {_nome} -> resta errore ritentabile", True)
    transcribe.con_retry = _old_retry

    # guardia: risposte in sequenza
    transcribe._carica_file = lambda c, p, r: type("F", (), {"name": "files/x"})()
    def _seq(risposte):
        chiamate = []
        def gen(client, model, f, extra, rep, descr):
            chiamate.append(model)
            return risposte[len(chiamate) - 1]
        return gen, chiamate
    _g, _ch = _seq([("", "STOP")] * config.ASR_MAX_TENTATIVI)
    transcribe._genera = _g
    _rp = _RepP()
    _res = transcribe._trascrivi_con_guardia(_CliDel(), Path("x.m4a"), 600, "audio 10/15", _rp)
    check("vuoto a ogni tentativo -> pezzo saltato (testo vuoto)", _res == ("", config.ASR_MODEL))
    check("...dopo TUTTI i tentativi flash-lite, senza fallback",
          _ch == [config.ASR_MODEL] * config.ASR_MAX_TENTATIVI)
    check("...e il registro lo dice (pausa)", any("nessun parlato" in r for r in _rp.righe))
    _g, _ch = _seq([("", "STOP"), ("Buongiorno a tutti, oggi parliamo di ossigenazione.", "STOP")])
    transcribe._genera = _g
    check("vuoto per caso poi testo -> si tiene il testo (vuoto temporaneo recuperato)",
          transcribe._trascrivi_con_guardia(_CliDel(), Path("x.m4a"), 60, "t", _RepP())[0].startswith("Buongiorno")
          and len(_ch) == 2)
    _g, _ch = _seq([("x", "MAX_TOKENS"), ("", "STOP"), ("", "STOP"), ("", "STOP")])
    transcribe._genera = _g
    _res = transcribe._trascrivi_con_guardia(_CliDel(), Path("x.m4a"), 600, "t", _RepP())
    check("runaway + vuoti -> decide il fallback (che puo' tornare vuoto)",
          _ch[-1] == config.TRANSCRIBE_MODEL and _res == ("", config.TRANSCRIBE_MODEL))
    transcribe._genera = _old_gen

    # trascrivi_chunks: pezzo vuoto in mezzo / tutti vuoti / ripresa dalla cache
    transcribe.audio.durata = lambda p: 600.0
    _testi = {"part_000.m4a": "Prima della pausa.", "part_001.m4a": "", "part_002.m4a": "Dopo la pausa."}
    _chiamati = []
    def _guardia_finta(client, c, dur, descr, rep):
        _chiamati.append(c.name)
        return _testi[c.name], config.ASR_MODEL
    transcribe._trascrivi_con_guardia = _guardia_finta
    _wd = Path(_tf.mkdtemp())
    (_wd / "chunks_audio").mkdir()
    _chunks = [_wd / "chunks_audio" / n for n in _testi]
    _raw = transcribe.trascrivi_chunks(None, _chunks, _wd, _RepP())
    check("pezzo muto in mezzo: la lezione va avanti e il testo e' unito senza buchi",
          _raw == "Prima della pausa.\nDopo la pausa.")
    check("pezzo muto salvato in cache (vuoto)",
          (_wd / "chunks_audio" / "part_002.txt").read_text(encoding="utf-8") == "")
    check("segni del tempo: tempi.json scritto anche col pezzo muto", (_wd / "tempi.json").exists())
    _chiamati.clear()
    check("ripresa: il pezzo muto in cache si riusa (nessuna richiesta)",
          transcribe.trascrivi_chunks(None, _chunks, _wd, _RepP()) == _raw and _chiamati == [])
    _testi = {k: "" for k in _testi}
    _wd2 = Path(_tf.mkdtemp())
    (_wd2 / "chunks_audio").mkdir()
    try:
        transcribe.trascrivi_chunks(None, [_wd2 / "chunks_audio" / n for n in _testi], _wd2, _RepP())
        check("nessun parlato in tutta la registrazione -> NessunParlato", False)
    except NessunParlato as _e:
        check("nessun parlato in tutta la registrazione -> NessunParlato", _e.codice == "py.err.nospeech.d")
finally:
    transcribe.con_retry, transcribe._carica_file, transcribe._genera = _old_retry, _old_carica, _old_gen
    transcribe._trascrivi_con_guardia, transcribe.audio.durata = _old_guardia, _old_durata

print(f"\n==== RISULTATO: {ok} PASS, {ko} FAIL ====")
raise SystemExit(1 if ko else 0)
