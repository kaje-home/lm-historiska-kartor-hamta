# LM Historiska kartor – hämta

Ett tillägg till QGIS som söker lantmäteriakter i Lantmäteriets arkiv Historiska kartor för ett område, låter dig gallra dem och laddar ner kartbladen som TIFF till ett arkiv med register. Det är ett fristående tillägg, inte från Lantmäteriet: frågor om pluginet hör hemma i förrådets ärenden på GitHub, inte hos Lantmäteriets support. Det kräver QGIS 3.40 eller nyare.

Det här är hämtningsdelen av ett större verktyg för att rektifiera historiska kartor i QGIS, som fortfarande byggs. Den här delen går att använda för sig redan nu; rektifieringen kommer senare som ett eget tillägg.

## Läs detta först

**Tjänsten är inofficiell.** Pluginet pratar med samma bakända som webbsidan [historiskakartor.lantmateriet.se](https://historiskakartor.lantmateriet.se) själv använder. Det finns inget offentligt gränssnitt för det här, och Lantmäteriet kan ändra eller stänga tjänsten när som helst utan förvarning. Då slutar pluginet fungera tills det är anpassat. Allt som rör tjänsten ligger i en enda modul (`tjanst.py`), så en ändring är avgränsad.

**Pluginet är hyggligt mot tjänsten.** Ett anrop i taget, en paus mellan anropen, och en cache på disk så att inget hämtas två gånger. Det laddar bara ner det du själv har gallrat fram, och bara kartsidorna, inte textsidorna. Sök inte större områden än du behöver, och kör inte flera QGIS samtidigt mot tjänsten.

**Villkoren för bilderna är dina att följa.** Kartorna visas fritt på Lantmäteriets webbplats; vad du får göra med nedladdade bilder styrs av Lantmäteriets villkor för Historiska kartor. Kolla dem innan du sprider bilder vidare.

## Första gången: Kom igång

*Kom igång…* i menyn visar vad som finns och vad som saknas, med en knapp för varje sak:

- **Arkiv**: en mapp där registret (`register.gpkg`) och kartorna läggs. Välj en tom mapp, eller en som pluginet redan skrivit i.
- **GDAL med ZSTD**: kartorna lagras förlustfritt; alla officiella QGIS-byggen från 3.40 har det.
- **Referensdata**: en mapp på din dator där du lägger de lager du laddar ner från Lantmäteriet. Skapa gärna en tom mapp, t.ex. `Lantmäteriet`, och välj den; pluginet hittar lagren i den på namn, i undermappar också. Allt nedan hämtas från Geotorget (geotorget.lantmateriet.se), Lantmäteriets sida för geodata. Du behöver ett konto där; det är gratis. Varje rad i Kom igång har knappen *Öppna Geotorget*, som går till rätt produktsida, och raden säger steg för steg vad du ska göra.
- **Socken och stad** (behövs): socknarnas gränser. Produkten *Socken och stad Nedladdning, vektor*, hela Sverige, gratis och utan prövning. Packa upp och lägg filen `sockenstad.gpkg` i referensdatan. Utan den kan arbetsområdet bara anges som socknar på namn.
- **Kommun, län och rike** (bra att ha): Lantmäteriets kommun- och länsgränser, så att socknar med samma namn i flera län skiljs åt av sig själva. Produkten *Kommun, Län och Rike Nedladdning*, gratis, beställs en gång på Geotorget utan prövning; filen läggs i referensdatan. Kommunvalet i *Välj…* fungerar även utan den, för tabellen socken → kommun följer med pluginet (CC BY 4.0).
- **Trakter** (valfritt): en trakt är ett byområde som arkivet sorterar akterna under, ungefär en by med sin utmark. Känner pluginet till trakternas lägen kan ett ritat område säga vilka trakter det rör. Pluginet tar dem ur den första av dessa som finns:
  1. **Eget traktlager**, om du har ett: pekas ut under *Alla inställningar…*
  2. **Fastighetsindelningen**: Lantmäteriets fil *Fastighetsindelning Nedladdning, vektor* har ett färdigt lager med trakternas ytor, med samma namn som arkivet använder. Den är gratis men inte öppna data: Lantmäteriet prövar ansökan, det tar några veckor. När du fått klartecken laddar du ner filen för din kommun, packar upp den (`fastighetsindelning_kn2380.gpkg`, siffrorna är kommunens kod) och lägger den i referensdatan. Pluginet läser bara traktnamn och gränser ur den, aldrig fastighetsbeteckningar eller ägare, och ingenting ur den följer med pluginet.
  3. **Ortnamnsregistret**: produkten *Ortnamn Nedladdning, vektor*, hela Sverige, gratis och utan prövning (med Geotorget-kontot); lägg filen `ortnamn_se.gpkg` i referensdatan. Den ger trakternas lägen som punkter, och byar och gårdar att söka på.

  Utan något av dem får du ändå socknarna i området, och arkivets egna trakter att bocka i under varje socken; sökning på namn och på aktbeteckning behöver inget av det.

## Sök och hämta

1. **Arbetsområde.** Välj ett sätt:
   - **By, gård eller trakt på namn**: skriv namnet, så slås det upp bland arkivets egna trakter i hela landet, och socknen och trakten bockas i. Det kräver inget nedladdat register. Finns namnet inte som trakt men du har ortnamnsregistret (Ortnamn Nedladdning), slås byar och gårdar upp där, och en ruta om 1 km runt varje träff blir arbetsområdet.
   - **Aktbeteckning**: skriv en eller flera beteckningar, t.ex. `23-HÄG-10` (REG) eller `Y22-2:1` (LMS). Socknen tas ur beteckningen och bara de angivna akterna gallras.
   - **Socknar på namn**: skriv socknen, eller tryck **Välj…** och gå län → kommun → socknar. Välj län, så visas länets alla socknar; markera en eller flera kommuner, så visas bara deras socknar. Bocka i de du vill ha, eller *Bocka i alla*. Kommunlistan är till för den som inte vet socknen. Tabellen socken → kommun följer med pluginet (ur Lantmäteriets Socken och stad och Kommun, län och rike, CC BY 4.0); gränserna är dagens, så en socken över en kommungräns står under båda kommunerna.
   - **Indexrutor 5 km**, **en ritad yta** eller **objekt i ett polygonlager**.
   Pluginet räknar fram vilka socknar och trakter som berörs och låter dig bekräfta; trakterna tas ur det egna traktlagret, annars fastighetsindelningen, annars ortnamnsregistret (se Kom igång), och kolumnen *Källa* i listan säger varifrån. Knappen heter *Hämta socknar och trakter*, eller *Visa socknarna* när du valt socknar på namn: då fylls listan ur arkivets vokabulär och inget hämtas. En trakt är ett byområde som arkivet sorterar akterna under, ungefär en by med sin utmark; ”alla akter i socknen” och enskilda trakter utesluter varandra. *Ta bort markerade* (eller Delete) tar bort socknar och trakter ur listan; att bocka ur räcker annars, bara ibockat söks.
2. **Sökning.** Akterna söks i båda arkiven, Lantmäterimyndigheternas (REG) och Lantmäteristyrelsens (LMS), en socken i taget. Akter utan karta gallras bort; resten sorteras efter åtgärd. Laga skifte, storskifte, avvittring och skattläggning kommer först.
3. **Gallring.** Varje akt får ett beslut: behåll, kasta eller vänta. Osäkra träffar är gula: normaliserade namn, byar i en akts lista, trakter som arkivet sorterat under en grannsocken.
4. **Kontaktkartan.** Knappen *Sök akter och visa kontaktkartan* söker akterna och visar deras kartsidor som små förhandsbilder, med beteckning, år och åtgärd. Där bedömer du varje akt: ✓ Behåll, ? Osäker eller ✕ Kasta. Förhandsbilderna är bara till för att välja; de ligger i pluginets arbetsmapp `tjanstecache` och är inte kartorna.
5. **Nedladdning.** Knappen *Ladda ned de kartor du behållit* hämtar kartsidorna i akter med Behåll som TIFF i full upplösning, lagrar dem med ZSTD och kontrollerar dem bildpunkt för bildpunkt. Efteråt visas var de hamnade, med knappen *Öppna mappen*. Bocka i *även textakten* så sparas varje akts protokoll och beskrivning som PDF bredvid kartorna. *Spara listan…* skriver allt som gallringen fann till en CSV-fil: beteckning, år, åtgärd, socken, trakter, sidor, beslut och två länkar till akten hos Lantmäteriet, PDF:en och webbsidans visare. Listan föreslås i arkivmappen och efteråt visas var den hamnade. I kontaktkartans högerklicksmeny finns samma två länkar: *Öppna akten som PDF hos Lantmäteriet* och *Öppna akten på Lantmäteriets webbsida*, och *Kopiera källhänvisning*, som lägger kartarkiv, karttyp och kartakt med år i urklipp, färdiga att klistra in i en rapport. Samma uppgifter finns som sista kolumn i listan, på en rad. Filnamnen följer mallen `{atgard}_{ar}_{beteckning}_{socken}_s{sida}.tif` i `<arkiv>/kartor/<socken>/`. Sidor som redan finns hoppas över, så en avbruten hämtning fortsätter där den slutade.

**Åtgärderna.** Raden *Åtgärder* ovanför knapparna väljer vilka slags förrättningar som tas med. Förvalet är alla; den som bara vill ha skifteskartor bockar ur resten. Stjärnan ★ i kontaktkartan markerar laga skifte, storskifte, avvittring och skattläggning, de förrättningar som brukar ha de bästa kartorna.

**Åren.** Fälten *Årtal (fr.o.m.)* och *Årtal (t.o.m.)* på samma rad begränsar till ett intervall, t.ex. 1820–1870. Ett tomt fält betyder ingen gräns åt det hållet; lämnas båda tomma tas alla år. Akter utan känt år behålls. Gallringen gör det innan den hämtar metadata, så det kostar inga anrop till tjänsten.

## Ordlista

- **Akt**: en förrättning i arkivet, med kartblad och textsidor, under en beteckning som `23-HÄG-10` (Lantmäterimyndigheternas arkiv, REG) eller `Y22-2:1` (Lantmäteristyrelsens arkiv, LMS).
- **Gallra**: välja bort akter man inte vill ha, så att bara de intressanta laddas ner. Varje akt får ett beslut: behåll, kasta eller vänta.
- **Kontaktkartan**: översikten med en miniatyr per behållen akt, som en kontaktkopia i ett fotolabb.
- **Trakt**: ett byområde som akterna sorteras under i arkivet; ungefär en by med sin utmark.
- **Socken**: den gamla kyrksocknen, arkivets geografiska indelning.
- **Textakt**: aktens sidor som inte är kartor, protokoll och beskrivningar.
- **REG och LMS**: de två arkiven, Lantmäterimyndigheternas respektive Lantmäteristyrelsens. Samma förrättning kan finnas i båda.

## Registret

`register.gpkg` i arkivet är en GeoPackage-databas med akterna (beteckning, åtgärd, år, socken, trakter, metadata från arkivet), deras sidor, filerna på disk med storlek och kontrollsumma, och dina beslut. Det går att öppna i QGIS som vilken GeoPackage som helst.

## Vanliga frågor

**Jag valde socknar på namn och tryckte på knappen, men inget hämtas.** Rätt: då fylls listan i steg 2 ur arkivets vokabulär, som pluginet redan har. Knappen heter därför *Visa socknarna*. Akterna hämtas först när du trycker *Sök akter och visa kontaktkartan*.

**Vad är en trakt, och varför kan jag inte bocka i både ”alla akter i socknen” och en trakt?** En trakt är ett byområde som arkivet sorterar akterna under, ungefär en by med sin utmark. ”Alla akter i socknen” betyder hela socknen; enskilda trakter smalnar av. De två utesluter varandra, annars skulle ”alla” tyst vinna.

**Socknen finns i flera län, vilken menar jag?** Skriv namnet med länet inom parentes, som i listan: `Ås (Jämtlands län)`. Eller tryck *Välj…* och gå län → kommun → socknar.

**Jag vet inte vilken socken gården ligger i.** Tryck *Välj…* vid Socknar på namn, välj län och klicka på kommunen: då visas kommunens socknar. Gränserna är dagens, så en socken över en kommungräns står under båda kommunerna.

**Gallringen säger ”Inga akter kvar”.** Titta på sammanfattningen: *annan åtgärd* betyder att åtgärdsraden utesluter dem (bocka i fler, eller alla), *annat år* att årtalsfälten gör det (töm dem), *kastade tidigare* att du kastat dem i en tidigare omgång (de visas aldrig igen).

**Kontaktkartan är tom, eller miniatyrerna kommer långsamt.** De hämtas en akt i taget från Lantmäteriet, i bakgrunden; statusraden räknar (”miniatyrer 12 av 230 hämtade”). Hundratals akter tar minuter. Du kan börja bedöma de som kommit; stäng inte fönstret.

**Hur väljer jag ett enda årtal?** Skriv samma år i *Årtal (fr.o.m.)* och *Årtal (t.o.m.)*. Tomt fält är ingen gräns; båda tomma ger alla år. Akter utan känt år behålls alltid.

**Kom igång säger att Kommun, län och rike saknas. Behövs den?** Bara för att skilja socknar med samma namn i flera län automatiskt, och för kommunvalet i *Välj…* följer tabellen redan med pluginet. Vill du ha filen: beställ produkten *Kommun, Län och Rike Nedladdning* på Geotorget (avgiftsfri, fliken Beställning, utan juridisk prövning), ladda ner geopackaget med ditt konto och lägg det i referensdatan.

**Nedladdningen från Lantmäteriet nekas (401 eller 403).** Kartbilderna i det här pluginet hämtas från den öppna webbsidans tjänst och kräver inget konto. Ett 401 eller 403 gäller Geotorget-produkter: behörigheten ges per produkt, beställs på Geotorget med samma konto, och kan dröja en kvart efter beställningen.

**Tjänsten svarar långsamt eller inte alls.** Pluginet pratar med webbsidans egen bakända, som är inofficiell och kan ändras eller stängas. Det gör ett anrop i taget med paus emellan och sparar allt det fått på disk, så ett nytt försök senare börjar där det slutade. Vänta en stund och tryck igen.

**Var hamnar det jag laddar ner?** I arkivmappen du angav under Inställningar: kartsidorna som TIFF under `kartor/<socken>/`, textakterna som PDF bredvid, listan där du sparade den, och registret med dina beslut i `register.gpkg`.

**Jag hittar bara små jpg-bilder med konstiga namn, och kvaliteten är dålig.** Det är kontaktkartans förhandsbilder i mappen `tjanstecache`, inte kartorna. Kartorna i full upplösning hämtas av knappen *Ladda ned de kartor du behållit*: markera först ✓ Behåll på akterna i kontaktkartan, tryck sedan på knappen. De hamnar som TIFF i `kartor/<socken>/` med åtgärd, år och beteckning i filnamnet, och efteråt visas var de ligger.

**Hur anger jag kartan som källa?** Högerklicka på akten i kontaktkartan och välj *Kopiera källhänvisning*. Då hamnar tre rader i urklipp: kartarkiv (Lantmäterimyndigheternas eller Lantmäteristyrelsens arkiv), karttyp och kartakt med år, t.ex. `Kartakt: Y12-16:1/1709`. Det är den form Fornreg vill ha, och den duger som fotnot var som helst. Arkivet syns också på beteckningen: `23-HÄG-10` är Lantmäterimyndigheternas arkiv, `Y22-2:1` Lantmäteristyrelsens.

**Får jag använda kartorna?** Pluginet hämtar det du gallrat fram, inget mer. Vad du sedan får göra med bilderna styrs av Lantmäteriets villkor för Historiska kartor, inte av pluginet; läs dem på lantmateriet.se.

**Ortnamnsregistret saknas, är det fel?** Nej, det är valfritt. Det behövs bara när du söker på en by eller gård som inte är en trakt i arkivet, och när ett ritat område ligger där varken eget traktlager eller fastighetsindelning finns.

**Kom igång säger att fastighetsindelningen saknas. Måste jag ha den?** Nej. Den ger trakternas ytor, så att ett ritat område kan säga vilka trakter det rör. Utan den tas trakternas lägen ur ortnamnsregistret, och utan det bockar du i trakter ur arkivets lista under socknen, eller tar alla akter i socknen. Vill du ha den: raden i Kom igång säger steg för steg hur, och knappen går till produktsidan.

**Kan pluginet inte ha trakterna med sig från början?** Nej. Trakternas ytor kommer ur Lantmäteriets fastighetsindelning, som kräver prövning och har villkor om personuppgifter, så de får inte spridas med pluginet. Varje användare hämtar sin egen fil och pluginet läser den på plats. Tabellen socken → kommun följer däremot med, för den är byggd ur öppna data.

## Felanmälan och källkod

Något som inte fungerar, eller en fråga: skriv ett ärende i förrådet på GitHub (adressen står i pluginets metadata och i QGIS insticksprogramhanterare). Där finns källkoden, ärendemallarna och proven.
