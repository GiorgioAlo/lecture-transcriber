# Come pubblicare una nuova versione

Checklist per distribuire un aggiornamento dell'app agli amici. L'app ha
l'**auto-update** (Step 3): all'avvio controlla le Release su GitHub e, se ce n'è
una più nuova, mostra un banner "Scarica". Quindi basta pubblicare una Release con
un **tag più alto** e il nuovo `.exe`: gli amici lo vedranno da soli.

Repo delle Release: **https://github.com/GiorgioAlo/lecture-transcriber**

---

## 1. Alza il numero di versione (nel codice)

File: `trascrittore/config.py` → riga `VERSION = "..."`. È l'**unico** posto: il
pacchetto della CLI (`pyproject.toml`, versione dinamica), l'exe e il .dmg la leggono da lì.

Usa **semver** `MAJOR.MINOR.PATCH`:
- **PATCH** (`1.1.0` → `1.1.1`): correzioni di bug.
- **MINOR** (`1.1.0` → `1.2.0`): funzioni nuove.
- **MAJOR** (`1.1.0` → `2.0.0`): cambiamenti grossi.

⚠️ Il numero **nuovo deve essere più alto** di quello già distribuito, altrimenti
il banner non scatta mai (l'app confronta la propria versione col tag della Release).

## 2. Controlla che i test passino

```
cd C:\whisper_test
PYTHONPATH=. & C:\Users\giorg\anaconda3\envs\trascrittore\python.exe tests_offline.py
```
Deve finire con `==== RISULTATO: N PASS, 0 FAIL ====`.

Gli stessi test girano anche da soli su GitHub (workflow **Test**: Windows + Python 3.11
e Linux + Python 3.12) a ogni push su `main` e ogni lunedì. Prima di rilasciare controlla
che l'ultimo commit su GitHub abbia la **✓ verde** (tab "Actions" o accanto al commit).

## 3. Ri-builda l'.exe

```
cd C:\whisper_test
& C:\Users\giorg\anaconda3\envs\trascrittore\python.exe -m PyInstaller packaging/app.spec --distpath packaging/dist --workpath packaging/build --noconfirm
```
Risultato: `packaging\dist\Trascrivi Lezioni.exe` (~134 MB). La versione dentro
l'exe è quella messa al passo 1 (il build la legge da `config.VERSION`).

Prova veloce: apri l'exe → **Impostazioni** → "Versione app" deve mostrare il numero nuovo.

## 4. Pubblica la Release su GitHub (dal sito, niente git)

1. Vai su https://github.com/GiorgioAlo/lecture-transcriber/releases → **Draft a new release**.
2. **Choose a tag** → scrivi `v<NUMERO>` (es. `v1.1.1`) → *"Create new tag on publish"*.
   - La `v` davanti ci vuole; il numero deve combaciare con `config.VERSION`.
3. **Release title**: `Versione <NUMERO>`.
4. **Describe this release**: scrivi cosa è cambiato (è il changelog che l'amico legge nel banner).
5. **Attach binaries**: trascina `packaging\dist\Trascrivi Lezioni.exe` e aspetta il 100%.
6. **Publish release**.

> NON modificare le Release vecchie: ogni versione è una Release nuova con tag nuovo.
> GitHub rinomina l'asset in `Trascrivi.Lezioni.exe` (punti al posto degli spazi): è normale.

## 5. Il .dmg per Mac arriva da solo

Appena la Release è **pubblicata**, GitHub fa partire il workflow **build-macos**
(tab "Actions"): costruisce il `.dmg` su un Mac di GitHub e lo **allega da solo** alla
stessa Release (`Trascrivi-Lezioni-macOS.dmg`). Ci mette ~10 minuti. Non serve fare nulla:
basta controllare che finisca con la ✓ verde.

> Se fallisce o va rifatto: tab Actions → **build-macos** → *Run workflow* → scrivi il tag
> (es. `v1.3.0`): ricostruisce il `.dmg` e lo sostituisce nella Release.

## 6. Verifica finale

- La nuova Release risulta **Latest**, non *Draft* né *Pre-release*.
- Ha **due** asset: il `.exe` (~134 MB) e, dopo ~10 minuti, il `.dmg`.
- (Opzionale) chi ha una versione precedente, riaprendo l'app, vede il banner entro
  qualche secondo (il controllo è max 1 volta al giorno per PC).

---

## Note / trappole

- **Google Form "Segnala un problema"** (link in `config.URL_FORM_SEGNALAZIONE`):
  deve restare **Pubblicato** con rispondenti = **Chiunque**, altrimenti i visitatori
  vedono *"Questo documento non è pubblicato"* (HTTP 401). Si pubblica dal pulsante
  **Pubblica** nel form.
- **In sviluppo** (`python app.py`) il pulsante "Aggiorna motore di download" torna
  "non è possibile aggiornare": è **normale**, in dev non c'è il `yt-dlp.exe` standalone
  (si usa il modulo pip). Nell'exe impacchettato funziona.
- **SmartScreen**: l'exe non è firmato → al primo avvio Windows mostra "Ulteriori
  informazioni → Esegui comunque". Vale la pena spiegarlo agli amici.
- Il controllo aggiornamenti è silenzioso su ogni errore (niente rete, GitHub giù):
  non disturba mai e non blocca l'avvio.

## Cambiare modello Gemini SENZA release (`modelli.json`)

Se Google ritira un modello (le schede dicono *"Google ha ritirato un modello che
l'app usa"*; nel log c'è il nome e spesso il sostituto suggerito da Google):

1. Scegli il sostituto guardando la pagina **limiti** di AI Studio: deve avere
   RPM/RPD **diversi da 0** sul free tier. L'app verifica solo che il nome esista,
   NON la quota (un modello a 0/0/0 "esiste" lo stesso e bloccherebbe tutti).
   Preferisci un flash-lite (RPD 500); gli altri flash hanno RPD 20.
2. Modifica `modelli.json` nella radice del repo: `model`, `rpm`, `rpd` del ruolo
   (`asr` = trascrizione, `fallback` = trascrittore di riserva, `text` = pulizia e
   traduzione), e pubblicalo su `main`. Le app lo leggono all'avvio e a ogni coda.
3. Aggiorna anche `trascrittore/config.py` con gli stessi valori: il test offline
   *"modelli.json == config.py"* fallisce finché non coincidono (così una release
   futura non riporta indietro il modello).

⚠️ Pubblicare su `main` aggiorna subito anche **Colab** (si installa da `main`):
se su `main` ci sono commit non ancora rilasciati, arrivano anche quelli.
