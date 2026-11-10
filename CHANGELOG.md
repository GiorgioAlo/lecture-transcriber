# Changelog

## 1.3.0 (in preparazione)
- Scegli il formato dei documenti nelle Impostazioni: Word, testo semplice (.txt) e/o Markdown (.md).
  Anche da riga di comando (`--formats docx txt md`) e su Colab (campo FORMATS).
- Al primo avvio l'app parte nella lingua del computer (italiano, altrimenti inglese) e la schermata
  di benvenuto ha il suo selettore IT|EN.
- Le parti che Gemini non è riuscito a ripulire o tradurre sono segnalate da un riquadro ben visibile
  (con la fine della parte grezza indicata), nella lingua del documento.
- Se Google ritira uno dei modelli Gemini usati dall'app, l'app se ne accorge subito, si ferma con un
  messaggio chiaro (invece di riprovare a vuoto) e il lavoro già fatto resta salvato.

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
