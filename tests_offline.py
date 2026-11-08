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

print(f"\n==== RISULTATO: {ok} PASS, {ko} FAIL ====")
raise SystemExit(1 if ko else 0)
