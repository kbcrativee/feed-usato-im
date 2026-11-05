# Feed usato — International Motors

File CSV delle auto usate in vendita, nel formato del catalogo veicoli di Meta, ricavato dalle pagine
**pubbliche** dell'elenco usato di internationalmotors.it (nessun dato privato, nessun account di terzi).
Si aggiorna da solo ogni notte (GitHub Actions); il codice è `genera-feed-usato.py`.

Indirizzo del file (da mettere in Meta → Gestore delle vendite → Origine dati → Aggiornamenti programmati, ogni giorno):

    https://raw.githubusercontent.com/kbcrativee/feed-usato-im/main/feed-usato-meta.csv

Se il sito non risponde o legge meno di 20 auto, lo script non sovrascrive il file e la corsa risulta fallita.
