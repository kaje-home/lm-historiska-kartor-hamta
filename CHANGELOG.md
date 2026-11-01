# Ändringar

## 0.1.5 (2026-11-01)

- QGIS 4 (Qt6): Sök och hämta fastnade på vokabulären med "svarade inte (200): Okänt fel". Svaret räknades som fel fast det kom fram, eftersom "inget fel" ser ut som ett fel i Qt6 (ärende 2).

## 0.1.4 (2026-11-01)

- Kommun, län och rike behövs inte längre: länet för varje socken tas ur tabellen som följer med pluginet. Kom igång bad om en fil som Lantmäteriet inte levererar som fil (ärende 1).
- Sök och hämta fastnar inte längre på "Vokabulären läses fortfarande in": går läsningen fel står det i panelen varför, och Hämta socknar och trakter försöker igen. En läsning som inte blivit klar på tre minuter släpps (ärende 2).
- Filer som OneDrive eller ett virusskydd håller en stund sparas med nya försök, och tjänstecachen stoppar inget när den inte går att skriva.
- Kom igång och Sök och hämta varnar när arkivet ligger i OneDrive.
- Anropen till Lantmäteriet har en tidsgräns på en minut utan svar.
- QGIS 4 (Qt6): omdirigeringarna sätts på ett sätt som finns i Qt6, och de nya namnen för polygonlager och ritad yta används. supportsQt6 i metadatan.

## 0.1.3 (2026-10-28)

- Inställningar: ett tomt fält visar i grått vad pluginet hittat och använder (Tjänstecache, Socken och stad, Kommun, län och rike, Ortnamnsregistret), i stället för att se ut som om något saknas.

## 0.1.2 (2026-10-27)

- Knapparna säger ordningen: Sök akter och visa kontaktkartan, sedan Ladda ned de kartor du behållit; en rad under förklarar att kontaktkartans bilder är förhandsbilder.
- Efter nedladdningen visas var kartorna hamnade, med knappen Öppna mappen, och ett tydligt besked när inga akter är markerade Behåll.
- En textfil i tjanstecache säger att mappen är arbetsfiler och var kartorna ligger; kontaktkartan säger detsamma.
- Manualen: frågan om små jpg-bilder med konstiga namn.

## 0.1.1 (2026-10-27)

- Kopiera källhänvisning i högerklicksmenyn och som sista kolumn i listan: kartarkiv, karttyp och kartakt med år.
- Fastighetsindelningens filer läses även utan kommunkod i namnet.
- Färre moduler i paketet: bara det hämtningen använder.

## 0.1.0 (2026-10-27)

- Första utgåvan.
