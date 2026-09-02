/* Short guided walk through the synthetic portfolio listings. */
const DEMO = '.gallery-card[data-demo="listing-2"]';
const D = "#drawer-panel ";

const LONG_TOUR_STEPS = [
  {title:"Witaj w interaktywnym demo",text:"Wybierz krótki przegląd albo pełny samouczek.",choices:[{mode:"short",label:"Szybki przegląd"},{mode:"long",label:"Pełny samouczek"}]},
  {path:"/galeria",selector:'[data-tour="demo-banner"]',title:"Przykładowe dane",text:"W tym demo pracujesz na trzech przygotowanych ogłoszeniach. Możesz je dowolnie zmieniać lub zresetować sesję."},
  {path:"/galeria",selector:DEMO+' [data-tour="card-cost"]',title:"Ukryte koszta",text:"Ta oferta wyglądała w ogłoszeniu na najtańszą, ale po doliczeniu mediów i opłat za parking przez Najemnika wychodzi na najdroższą."},
  {path:"/galeria",selector:DEMO,advance:"click",clickHint:"Otwórz tę ofertę",title:"Wejdźmy w szczegóły",text:"Tu widać, co składa się na końcową kwotę i czego brakuje w opisie."},
  {path:"/galeria",selector:"#drawer-panel",pad:0,scroll:false,title:"Wszystko w jednym miejscu",text:"Zdjęcia, koszty, lokalizacja, notatki i status są pod ręką."},
  {path:"/galeria",selector:D+'[data-status="Przejrzane"]',advance:"click",clickHint:"Oznacz jako „Przejrzane”",title:"Zmień status",text:"Po przeczytaniu ogłoszenia zmień status. Łatwiej potem wrócić do właściwych ofert."},
  {path:"/galeria",selector:D+".next-step",title:"Co dalej?",text:"Po przejrzeniu oferty zwykle dzwonisz. Dynamicznie pokazujemy kolejny krok na górze."},
  {path:"/galeria",selector:D+'[data-tour="callprep"]',onEnter:()=>{const el=document.querySelector('#drawer-panel [data-tour="callprep"]');const data=el&&window.Alpine&&Alpine.$data(el);if(data)data.open=true;},title:"Pytania do rozmowy",text:"Najemnik podpowiada jakich informacji brakuje i o co zawsze dopytać."},
  {path:"/galeria",selector:D+'[data-status="Umówione na oględziny"]',advance:"click",clickHint:"Oznacz „Umówione na oględziny”",title:"Zmień status",text:"Umówiłeś się na oględziny, zapisz to zmianą statusu."},
  {path:"/galeria",selector:D+".next-step",title:"Co dalej",text:"Po rozmowie interesuje się teraz termin, przy wielu ofertach łatwo go zgubić."},
  {path:"/galeria",selector:D+'[data-tour-group="Mieszkanie"]',advance:"click",clickHint:"Rozwiń „Mieszkanie”",title:"Podstawy oferty",text:"Tutaj są dane wyciągnięte z ogłoszenia: metraż, piętro, pokoje i podobne rzeczy."},
  {path:"/galeria",selector:D+'[data-tour-group-body="Mieszkanie"]',title:"Nie wszystko jest w formularzu",text:"Część danych jest podana wprost w tabelach, a część trzeba odnaleźć w tekście ogłoszenia. To zadanie dla Najemnika."},
  {path:"/galeria",selector:D+'[data-field="pets_allowed"]',title:"Przykład: zwierzęta",text:"To zwykle jest ukryte w opisie. Najeminik jednak znalazł to za ciebie."},
  {path:"/galeria",selector:D+'[data-field="pets_allowed"] .ai-badge',pad:4,title:"Skąd ta informacja?",text:"Znaczek AI oznacza wartość z analizy opisu. Najedź na niego, aby zobaczyć fragment na którym się wzorował. W przypadku błędu zawsze możesz poprawić go ręcznie."},
  {path:"/galeria",selector:D+'[data-tour-group="Koszt miesięczny"]',advance:"click",clickHint:"Rozwiń „Koszt miesięczny”",title:"Tu robi się ciekawie",text:"Cena z nagłówków ogłoszeń z portali to dopiero początek. Najemnik pokazuje realny miesięczny koszt."},
  {path:"/galeria",selector:D+'[data-tour-group-body="Koszt miesięczny"]',title:"Koszty osobno",text:"Odstępne, czynsz, media i parking są rozdzielone, żeby można było uczciwie porównać oferty."},
  {path:"/galeria",selector:D+'[data-field="parking"]',title:"Miejsce parkingowe",text:"Tutaj widać dodatkowe miejsce w garażu podziemnym. Parking potrafi mocno zmienić koszt całej oferty, więc warto mieć go osobno."},
  {path:"/galeria",selector:D+'[data-tour="fees-note"]',title:"Z czego składają się opłaty",text:"Tu widać, co wiadomo o opłatach, a co wymaga doprecyzowania. Szacunki możesz zmienić w ustawieniach."},
  {path:"/galeria",selector:D+'[data-tour-group="Koszt wejścia"]',advance:"click",clickHint:"Rozwiń „Koszt wejścia”",title:"Ile trzeba mieć na start?",text:"To osobna lista jednorazowych wydatków przy podpisaniu umowy."},
  {path:"/galeria",selector:D+'[data-tour-group-body="Koszt wejścia"]',title:"Koszta jednorazowe",text:"Są rozpisane oddzielnie, bo to też pieniądze które musisz wydać."},
  {path:"/galeria",selector:D+'[data-tour="to-map"]',advance:"click",clickHint:"Pokaż na pełnej mapie",title:"Sprawdźmy mapę",text:"Na mapie widać wszystkie oferty i ich pełne koszta."},
  {path:"/mapa",selector:"#map",pad:0,scroll:false,title:"Wszystko w jednym widoku",text:"Kwota na pinezce to koszt miesięczny, możesz zmienić widok w lewym górym rogu."},
  {path:"/mapa",selector:"#map-move-pin-toggle",scroll:false,title:"Pinezka nie musi być idealna",text:"Ogłoszenia rzadko podają dokładny adres. W tym trybie możesz przesunąć lokalizje na prawdziwą."},
  {path:"/mapa",selector:'[data-tour="filters"]',scroll:false,onEnter:()=>{const root=window.Alpine&&Alpine.$data(document.documentElement);if(root)root.sidebarOpen=true;},title:"Filtry, pomiędzy widokami",text:"Tutaj możesz filtrować mape jak i galerię."},
  {path:"/mapa",selector:'#top-nav a[href^="/galeria"]',advance:"click",clickHint:"Wróć do Galerii",title:"Na koniec: porównanie",text:"Wybierzmy kilka ofert i porówanajmy je ze sobą."},
  {path:"/galeria",selector:'[data-tour="compare-toggle"]',advance:"click",clickHint:"Włącz tryb porównania",title:"Zaznaczanie ofert",text:"W tym trybie kliknięcie dodaje ofertę do porównania, zamiast otwierać szczegóły."},
  {path:"/galeria",selector:".grid",scroll:false,advance:"when",when:()=>window.Alpine&&Alpine.store("ui").compareSel.length>=2,clickHint:"Zaznacz co najmniej dwie oferty",nextLabel:"Gotowe",title:"Wybierz dwie lub trzy",text:"Kliknij oferty, które chcesz zestawić. Gdy będą przynajmniej dwie, przejdziemy dalej."},
  {path:"/galeria",selector:'[data-tour="compare-go"]',advance:"click",clickHint:"Kliknij „Porównaj”",title:"Zobacz różnice",text:"Teraz łatwiej ci będzie zdecydować."},
  {path:"/porownaj2",title:"I to jest sedno",text:"Lepsze wartości są podświetlone a wszystkie dane są widoczne naraz."},
];

window.TOUR_SHORT_STEPS = [
  {path:"/galeria",selector:'[data-tour="demo-banner"]',title:"Przykładowe dane",text:"To trzy przygotowane ogłoszenia. Możesz je swobodnie zmieniać i zresetować sesję."},
  {path:"/galeria",selector:DEMO+' [data-tour="card-cost"]',title:"Pełny koszt",text:"Cena z ogłoszenia nie zawsze mówi wszystko. Najemnik zbiera w jednym miejscu czynsz, media i parking."},
  {path:"/galeria",selector:DEMO,advance:"click",clickHint:"Otwórz tę ofertę",title:"Sprawdź szczegóły",text:"Zobacz rozpisane koszty, brakujące informacje i status oferty."},
  {path:"/galeria",selector:D+'[data-status="Przejrzane"]',advance:"click",clickHint:"Oznacz jako „Przejrzane”",title:"Zapisz postęp",text:"Status pomaga nie wracać przypadkiem do ofert, które masz już za sobą."},
  {path:"/galeria",selector:'[data-tour="compare-toggle"]',advance:"click",clickHint:"Włącz tryb porównania",onEnter:()=>{const ui=window.Alpine&&Alpine.store("ui");if(ui)ui.drawerOpen=false;},title:"Porównaj oferty",text:"Zaznacz dwie oferty, aby zestawić ich koszty obok siebie."},
  {path:"/galeria",selector:".grid",scroll:false,advance:"when",when:()=>window.Alpine&&Alpine.store("ui").compareSel.length>=2,clickHint:"Zaznacz co najmniej dwie oferty",nextLabel:"Dalej",title:"Wybierz dwie oferty",text:"Kliknij dwie karty, które chcesz porównać."},
  {path:"/galeria",selector:'[data-tour="compare-go"]',advance:"click",clickHint:"Kliknij „Porównaj”",title:"Wynik",text:"W tabeli łatwo zobaczysz, gdzie naprawdę są różnice."},
  {path:"/porownaj2",title:"To najważniejsze",text:"Pełne koszty i dane są widoczne obok siebie. Resztę możesz już sprawdzić samodzielnie."},
];

registerTourSteps(LONG_TOUR_STEPS);
