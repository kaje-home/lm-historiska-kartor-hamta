"""Vilken utgåva av pluginet som körs. Samma moduler bygger två plugin (2026-10-26,
användaren: "skulle man kunna bryta ut den och göra en egen plugin av det men naturligtvis
ha kvar det i det stora verktyget"):

* hela verktyget (`lm_historiska_kartor`): BARA_HAMTNING = True -- Kom igång, Gallra,
  Rektifiera, Inställningar;
* hämtningen för sig (`lm_hamtning`, byggd av `verktyg/bygg_hamtning.py` ur samma kod):
  BARA_HAMTNING = True -- Kom igång, Sök och hämta, Inställningar; utan rektifiering,
  automatik, läsning, API-nyckel och Geotorget-konto.

Byggskriptet skriver om den här filen i kopian. Ingen annan modul får läsa flaggan
för något annat än att dölja det som inte finns i utgåvan."""
BARA_HAMTNING = True
