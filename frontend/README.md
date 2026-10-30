# Porządek MVP

Lekka aplikacja bez frameworka i zależności. Otwórz przez HTTP, nie przez file://.

Uruchomienie: `npm run dev`, następnie http://localhost:4173.
Testy silnika: `npm test` (Node 20+).

## Działa

- Import JSONL/JSON (do 5 MB), deduplikacja po source_id, odrzucenie kolizji ID.
- Odtwarzanie wycen, akceptacji, wykonania i wpłat z wiadomości.
- Pulpit, interaktywny graf w stylu Neo4j, historia pól, źródła, wyszukiwanie i plan działań.
- Graf klient → zlecenie → aktualne ustalenie reaguje na import, nowe wiadomości i zegar raportu. Obsługuje filtr zlecenia, przeciąganie węzłów, zoom i przejście do źródeł; brak tożsamości pozostaje osobnym węzłem. Link bezpośredni: http://localhost:4173/#jobs. Graf nie wymaga bazy Neo4j.
- Ręcznie dodawane wiadomości z kontekstem zlecenia, szablony kontaktu.
- Cztery zdarzenia replay, jawny zegar raportu, eksport stanu, localStorage.

## Granice MVP

Dane są syntetyczne. Regułowy parser obsługuje wybrane polskie sformułowania, nie dowolną mowę. Nie jest walidowanym parserem produkcyjnym. Nie używa expected.json ani map source_id → zlecenie. Nową cenę proponuje właściciel; klient akceptuje bieżącą ofertę. To pojedynczy workspace zapisany na danym urządzeniu; bez synchronizacji, logowania aplikacyjnego i podłączenia komunikatorów. Import nie wykonuje OCR ani transkrypcji.

Reactor NIE jest podłączony. Pytanie o brak i szkice kontaktu są jawnymi lokalnymi regułami. Kolejny krok: serwerowy adapter Reactora, schema validation i kolejka. Klucza API nie wolno wkładać do kodu przeglądarki. Funkcję compute można zastąpić ekstrakcją modelową zachowując kontrakt jobs/tasks/gaps/totals/evidence/history. Wysyłka do klienta nie jest realizowana; kopiowanie szkicu nie zamyka sprawy.

Kontrakt SourceMessage: source_id, sent_at (ISO 8601), raw_text, channel, author_role (owner/customer/worker/supplier), thread_id, contact_key, conversation_title. Opcjonalne attachments i jawnie wybrany job_context. Wersja demonstracyjna raportuje zlecenia z archiwum od 25.10.2026 do wybranego dnia.

Stan początkowy dużego demo na 30.10.2026: 20 150 PLN wycen, 26 900 PLN uzgodnionych prac, 3750 PLN prac wykonanych bez wpłaty oraz 9150 PLN potwierdzonych wpłat; 13 zadań i 4 braki identyfikacji. Przyszłe zdarzenia nie są importowane przed ich odtworzeniem. Zamknięcie wyceny tworzy kolejny krok ustalenia terminu. Liczby są wartościami etapów, nie zyskiem ani udowodnioną korzyścią produktu. Wpłata to potwierdzenie zapisane przez właściciela, bez integracji bankowej.

## Widok codzienny V3

Domyślnie Klienci i zlecenia pokazuje pełne nazwy, kwotę, słowny status i następny krok. Sprawy wymagające działania są pierwsze. Przygotuj wiadomość otwiera działający szkic do skopiowania. Wskaż klienta obsługuje nieprzypisaną notatkę. Widok powiązań zachowuje graf z kółkami, filtrowaniem i zoomem pod osobnym przyciskiem. Widok działa na tym samym modelu co pulpit, nie na oddzielnej makiecie.

## Widok V4

Skrócony interfejs: klient, zlecenie, kwota, status i jeden przycisk działania. Zakres, historia i oryginały są w szczegółach. Graf pozostaje pod przyciskiem Graf powiązań, scenariusz demo jest zwinięty. Logika przetwarzania danych pozostaje ta sama.

## Wygląd V5

Ciemny pasek nawigacji, jasny obszar roboczy, akcent limonkowy i wyraźne kwoty. Tekst i funkcje z V4 zachowano. Animacje respektują prefers-reduced-motion; zmiana kwoty wyróżnia faktycznie przeliczony rekord.

## Dane i graf V6

`dist/demo.json`: 208 dostarczonych wpisów, 192 unikalne źródła i 16 powtórek. Wiadomości tworzą 20 zleceń: wyceny, korekty cen, stare oferty w cytatach, akceptacje, ustalanie terminów, wykonanie i potwierdzenia wpłat. Są też literówki, podobne adresy, niejednolite nazwy kontaktów, szum od dostawcy i ekipy oraz cztery notatki bez ustalonego klienta. To przygotowane dane syntetyczne, nie próbka od prawdziwej firmy.

Graf ma 65 węzłów (firma, 20 klientów, 20 zleceń, 20 aktualnych ustaleń i 4 nieprzypisane notatki) oraz 60 relacji. Na szerokim ekranie rozchodzi się promieniście od firmy, na małym zachowuje pionowe gałęzie. Filtr wyróżnia wybrane zlecenie, a kliknięcie prowadzi do historii i oryginalnych źródeł. Notatki bez klienta pozostają osobno, bez zmyślonych powiązań.

Prosty widok pokazuje najpierw 6 spraw wymagających działania i 3 pozostałe. Przycisk „Wszystkie zlecenia (20)” rozwija resztę. Pulpit pokazuje 3 działania, pełna lista jest w Planie działań. Większy zestaw demonstracyjny uzupełnia starsze demo w localStorage, zachowując dodane wiadomości i odtworzone zdarzenia. Obcy import nie jest automatycznie uzupełniany demo.

`dist/demo-small.json` zachowuje pierwotną próbkę 60 wpisów dla testów regresji. Testy sprawdzają też duży zestaw, deduplikację, rozdzielenie podobnych adresów, aktualne kwoty po cytatach, replay, migrację zapisanego stanu i spójność grafu.
