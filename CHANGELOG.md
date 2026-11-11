# Changelog

## 1.3.0
- Scegli il formato dei documenti nelle Impostazioni: Word, testo semplice (.txt) e/o Markdown (.md).
  Anche da riga di comando (`--formats docx txt md`) e su Colab (campo FORMATS).
- Al primo avvio l'app parte nella lingua del computer (italiano, altrimenti inglese) e la schermata
  di benvenuto ha il suo selettore IT|EN.
- Con l'interfaccia in inglese anche avvisi, messaggi di errore e finestre per scegliere i file sono in
  inglese, e cambiano lingua insieme all'interfaccia.
- Le parti che Gemini non è riuscito a ripulire o tradurre sono segnalate da un riquadro ben visibile
  (con la fine della parte grezza indicata), nella lingua del documento.
- Se Google ritira uno dei modelli Gemini usati dall'app, l'app se ne accorge subito, si ferma con un
  messaggio chiaro (invece di riprovare a vuoto) e il lavoro già fatto resta salvato.
- I modelli da usare possono essere cambiati a distanza (file `modelli.json` nel repo): se Google ne
  ritira uno, l'app passa al sostituto senza bisogno di una nuova versione.
- La versione da riga di comando si installa anche con Python 3.11 (prima serviva il 3.12).
- Segni del tempo nei documenti ("⏱ ~10 min", "⏱ ~20 min", … "⏱ ~1 h 10 min") per ritrovare
  più o meno un punto della lezione nel video. Sono approssimati: servono per orientarsi.
- Risolto: una lezione con una pausa lunga (circa 10 minuti in cui nessuno parla ma la registrazione
  continua) finiva in errore. Ora la pausa viene semplicemente saltata. Se invece in tutta la
  registrazione non parla nessuno, l'app si ferma con un messaggio chiaro.
- Webex senza cookie: si può incollare il link diretto della registrazione (`hls.m3u8`, copiato dal
  browser con F12 → Rete). La guida è nell'app. Questi link scadono, quindi l'app li scarica subito
  all'avvio della coda; se è scaduto lo dice chiaramente.
- Nelle Impostazioni c'è il tasto "☕ Fai una donazione" (PayPal), accanto a "Segnala un problema".
- Colab: guida passo passo per i cookie di Webex (o per il link diretto), il file dei cookie viene
  trovato con qualunque nome, e i link prendono il titolo del video (prima si chiamavano tutti
  "Lecture" e i documenti si sovrascrivevano).

## 1.2.1
- Risolto un problema per cui l'avviso di nuova versione poteva non comparire.

## 1.2.0
- Interfaccia bilingue Italiano/Inglese e tema scuro.
- Nuovo look (colore indaco, icona) e pannello Impostazioni rinnovato.
- Messaggi di errore chiari + pulsante "Riprova" sulle lezioni non riuscite.
- Se una parte non viene ripulita, nel Word resta comunque la trascrizione grezza.
- Maggiore robustezza su contenuti particolari; trascrizione fedele anche del linguaggio colorito.

## 1.1.0
- Aggiornamento automatico (avviso quando esce una versione nuova).
- Versioni per Windows (.exe), macOS (.dmg), riga di comando e Google Colab.
