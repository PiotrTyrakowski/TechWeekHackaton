# Reactor calls: results and checks

Generated 2026-10-31 09:16 by `python report.py` from `runs/*/results.jsonl`: every line is one call to our Reactor agent (team OpenToVibe, slot t07) through the kit's `client.py`, exactly as the client returned it. Rows for every call are also in `reactor_calls.json`.

**Test coverage:** 63 of 146 test questions have a Reactor answer (83 still to ask).

## Summary per run

| run | questions | calls | answered | all checks pass | abstained | median latency | max latency | busy retries | late replies set aside |
|---|---|---|---|---|---|---|---|---|---|
| dev1 | dev (testing) | 22 | 22 | 22 | 3 | 57 s | 138 s | 0 | 0 |
| dev2 | dev (testing) | 7 | 7 | 7 | 0 | 60 s | 69 s | 0 | 0 |
| dev3 | dev (testing) | 1 | 1 | 1 | 0 | 74 s | 74 s | 0 | 0 |
| smoke | test (testing) | 3 | 3 | 3 | 0 | 69 s | 71 s | 5 | 0 |
| test | submission | 55 | 55 | 55 | 4 | 72 s | 165 s | 230 | 1 |
| test2 | submission | 18 | 11 | 11 | 2 | 78 s | 141 s | 31 | 0 |

**All runs:** 106 calls, 99 answered, 99 pass every check.

## Checks

| check | meaning | calls failing |
|---|---|---|
| answered | client status `answered` (no timeout, refusal, closed chat or error) | 7: test2#9, test2#10, test2#11, test2#12, test2#14, test2#15, test2#16 |
| ref | the reply's `# FINAL ANSWER [ref:…]` line carries this question's ref, so it answers this message | 7: test2#9, test2#10, test2#11, test2#12, test2#14, test2#15, test2#16 |
| citations | every cited `[E#]` label is one we sent, and maps to a real session of that history | 7: test2#9, test2#10, test2#11, test2#12, test2#14, test2#15, test2#16 |
| cited | an answer that is not an abstention cites at least one excerpt | 7: test2#9, test2#10, test2#11, test2#12, test2#14, test2#15, test2#16 |
| size | the message we sent was within the 31,000-character limit | 0 |
| abstention | abstained exactly when the answer is `INSUFFICIENT_EVIDENCE` | 7: test2#9, test2#10, test2#11, test2#12, test2#14, test2#15, test2#16 |

A *late reply* is a final answer to the previous question that arrived while the next one was being asked. The client reports it separately and never takes it as the current answer: test#26 (q_7b0aefc8ba1b).

## Reactor and the second reader

62 submission calls carried a DeepSeek draft. Reactor's final answer matches the draft (ignoring labels, case and punctuation) in 57 and differs in 5; Reactor checks the draft against the evidence and does not copy it.

| run | question | draft | Reactor |
|---|---|---|---|
| test#7 | What's the name of my neighborhood in Lisbon? | Príncipe Real [E6] | INSUFFICIENT_EVIDENCE |
| test#31 | What was the name of the French tutor I told you about? | Marc [E16] | Hélène [E9] |
| test#40 | What dial lamp voltage did I end up using in my National R-… | 12-volt [E9][E31] | 6.3-volt [E9] |
| test#41 | What output tube cathode resistor value did I end up using … | 150 ohms [E6][E17][E25] | 180 ohms [E6][E17] |
| test2#17 | What output tube cathode resistor value did I end up using … | 150 ohms [E6][E17][E25] | 180 ohms [E6][E17][E25] |

## Every test call

`smoke` is our first connection test on three test questions; its answers are not used.

`in submission`: this call's answer is the one `predict.py` uses (a later re-ask replaces an earlier answer).

| run | # | question | Reactor's answer | cited sessions | latency | checks | in submission |
|---|---|---|---|---|---|---|---|
| smoke | 1 | What is my cat's name? | Pixel [E19] | 1 | 69 s | ✓ |  |
| smoke | 2 | What was the name of that time-tracking app you recommended… | Toggl Track [E4, E6] | 2 | 71 s | ✓ |  |
| smoke | 3 | How many days apart were my son's school play and my daught… | 14 days [E4, E6] | 2 | 67 s | ✓ |  |
| test | 1 | What is my cat's name? | INSUFFICIENT_EVIDENCE [E25] | 1 | 129 s | ✓ |  |
| test | 2 | What was the name of that time-tracking app you recommended… | Toggl Track [E5][E8] | 2 | 104 s | ✓ | ✓ |
| test | 3 | How many ceramic pieces am I putting in the class show? | 5 [E35][E40] | 2 | 92 s | ✓ | ✓ |
| test | 4 | What was the name of that coworking space you recommended t… | INSUFFICIENT_EVIDENCE [E15][E16] | 2 | 72 s | ✓ | ✓ |
| test | 5 | What is the name of the coffee shop I get my morning espres… | Fábrica Coffee Roasters [E9] | 1 | 34 s | ✓ | ✓ |
| test | 6 | What is the name of my ceramics class instructor now? | Ana Ferreira [E3][E29] | 2 | 83 s | ✓ | ✓ |
| test | 7 | What's the name of my neighborhood in Lisbon? | INSUFFICIENT_EVIDENCE | 0 | 77 s | ✓ | ✓ |
| test | 8 | What is the name of the accountant I'm using for my freelan… | Bruno Almeida [E7][E26] | 2 | 72 s | ✓ | ✓ |
| test | 9 | How many days apart were my son's school play and my daught… | 14 days [E12][E15] | 2 | 82 s | ✓ | ✓ |
| test | 10 | What is my current job title? | Director of Clinical Services [E17] | 1 | 52 s | ✓ | ✓ |
| test | 11 | How many watercolour classes do I attend each week? | 2 [E7][E27][E47] | 3 | 72 s | ✓ | ✓ |
| test | 12 | How many different vegetable varieties have I planted in my… | 5 [E1][E12][E18][E20][E27] | 5 | 133 s | ✓ | ✓ |
| test | 13 | What was the name of the restaurant you recommended for din… | Matilda 159 Domain [E7] | 1 | 56 s | ✓ | ✓ |
| test | 14 | What is my younger son's name? | Daniel [E14][E24] | 2 | 70 s | ✓ | ✓ |
| test | 15 | How many days apart were the hospital's 'Run for Health' 5K… | 139 days [E2][E21] | 2 | 47 s | ✓ | ✓ |
| test | 16 | How many days apart were the watercolour society's annual e… | 83 days [E23][E7] | 2 | 90 s | ✓ | ✓ |
| test | 17 | Who teaches my Saturday morning watercolour class now? | Priya Nair [E2][E37] | 2 | 44 s | ✓ | ✓ |
| test | 18 | What is my dog's name? | INSUFFICIENT_EVIDENCE | 0 | 55 s | ✓ | ✓ |
| test | 19 | How many days apart were my trip to Adelaide to visit James… | 71 days [E5][E16] | 2 | 34 s | ✓ | ✓ |
| test | 20 | How much did I add to my used car savings from my March sal… | 37,500 shillings [E2][E16] | 2 | 44 s | ✓ | ✓ |
| test | 21 | How many days apart were starting my Python for Data Analys… | 43 days [E5][E15] | 2 | 64 s | ✓ | ✓ |
| test | 22 | How many gigabytes is my current mobile data plan? | 25GB [E3][E18] | 2 | 77 s | ✓ | ✓ |
| test | 23 | Which Python library did you recommend for my data cleaning… | pandas [E4] | 1 | 60 s | ✓ | ✓ |
| test | 24 | How many days apart were my church choir retreat and my fir… | 14 days [E19][E24] | 2 | 73 s | ✓ | ✓ |
| test | 25 | What is my current monthly rent? | 9,000 shillings a month [E16][E17] | 2 | 165 s | ✓ | ✓ |
| test | 26 | What is my favorite meal? | pilau [E8] | 1 | 56 s | ✓ | ✓ |
| test | 27 | Which code editor did you recommend I use for my Python pra… | Visual Studio Code [E4] | 1 | 82 s | ✓ | ✓ |
| test | 28 | What is my favorite color? | teal [E8] | 1 | 81 s | ✓ | ✓ |
| test | 29 | What was the name of that French flour brand you recommende… | Moulin de Versailles [E6] | 1 | 45 s | ✓ | ✓ |
| test | 30 | What was the name of the milonga in San Telmo I told you ab… | La Catrina [E4] | 1 | 52 s | ✓ | ✓ |
| test | 31 | What was the name of the French tutor I told you about? | Hélène [E9] | 1 | 55 s | ✓ | ✓ |
| test | 32 | How many days after I entered my alfajor recipe in the city… | 104 days [E5][E20] | 2 | 51 s | ✓ | ✓ |
| test | 33 | How much is left in my bakery fund after those transactions… | 23,200 pesos [E2][E13][E37] | 3 | 111 s | ✓ | ✓ |
| test | 34 | How much have I spent on tango shoes in total? | 6,200 pesos [E4][E20][E35] | 3 | 84 s | ✓ | ✓ |
| test | 35 | What did I end up naming my sourdough starter? | Masa [E4][E9] | 2 | 53 s | ✓ | ✓ |
| test | 36 | How many days after I bought my ticket to the Buenos Aires … | 10 days [E23][E28] | 2 | 67 s | ✓ | ✓ |
| test | 37 | How many kilos of dulce de leche did I make in total for th… | 8 kilos [E5][E13] | 2 | 74 s | ✓ | ✓ |
| test | 38 | What AM intermediate frequency did I end up using in my Nat… | 465 kHz [E5][E32] | 2 | 56 s | ✓ | ✓ |
| test | 39 | What speaker impedance did I end up using in my National R-… | 8-ohm [E5][E16] | 2 | 55 s | ✓ | ✓ |
| test | 40 | What dial lamp voltage did I end up using in my National R-… | 6.3-volt [E9] | 1 | 89 s | ✓ | ✓ |
| test | 41 | What output tube cathode resistor value did I end up using … | 180 ohms [E6][E17] | 2 | 72 s | ✓ |  |
| test | 42 | What screen grid resistor value did I end up using in my Na… | 10k-ohm [E18] | 1 | 68 s | ✓ | ✓ |
| test | 43 | What value did you recommend for the audio coupling capacit… | 0.022 µF film capacitor [E10] | 1 | 89 s | ✓ | ✓ |
| test | 44 | What AGC resistor value did I end up using in my National R… | 33k-ohm [E1][E10] | 2 | 72 s | ✓ | ✓ |
| test | 45 | What power supply filter capacitor value did I end up using… | 47 µF [E7][E22] | 2 | 66 s | ✓ | ✓ |
| test | 46 | How many tubes did I end up replacing in my National R-77? | 2 [E4][E23] | 2 | 74 s | ✓ | ✓ |
| test | 47 | By how many ohms did I reduce the volume control resistance… | 250k ohms [E2][E17] | 2 | 151 s | ✓ | ✓ |
| test | 48 | How many orchids have I added to my collection since March? | 6 [E1][E9][E16] | 3 | 84 s | ✓ | ✓ |
| test | 49 | How many laps do I swim each morning these days? | 40 laps [E32][E34] | 2 | 75 s | ✓ | ✓ |
| test | 50 | How many times did my systolic reading exceed 130 in August? | 3 [E29][E32][E37] | 3 | 62 s | ✓ |  |
| test | 51 | How many years did I serve as a firefighter? | 40 years [E4][E18] | 2 | 90 s | ✓ | ✓ |
| test | 52 | How many phone calls did I have with my daughter in August? | 3 [E23][E24][E26] | 3 | 80 s | ✓ | ✓ |
| test | 53 | How many grandchildren do I have? | 2 [E7] | 1 | 68 s | ✓ | ✓ |
| test | 54 | How many cups of coffee do I drink each morning these days? | one cup [E13][E15] | 2 | 91 s | ✓ | ✓ |
| test | 55 | How many kilometers do I walk each evening these days? | five kilometers [E5][E23] | 2 | 90 s | ✓ | ✓ |
| test2 | 1 | How many times did I eat feijoada last month? | INSUFFICIENT_EVIDENCE | 0 | 56 s | ✓ | ✓ |
| test2 | 2 | How many books have I read since March? | 4 [E2][E9][E18] | 3 | 87 s | ✓ | ✓ |
| test2 | 3 | How many days apart were my monstera repotting and my lead-… | 69 days [E4][E16] | 2 | 78 s | ✓ | ✓ |
| test2 | 4 | How many days after submitting my visa application did I bo… | 72 days [E3][E16] | 2 | 78 s | ✓ | ✓ |
| test2 | 5 | How many days after setting up my Montreal flat alerts did … | 45 days [E9][E16] | 2 | 65 s | ✓ | ✓ |
| test2 | 6 | How many days after buying my trail-running shoes did I do … | INSUFFICIENT_EVIDENCE | 0 | 71 s | ✓ | ✓ |
| test2 | 7 | What was the name of the bank you recommended for my year i… | Scotiabank [E15] | 1 | 69 s | ✓ | ✓ |
| test2 | 8 | How many days after sending off my passport renewal did my … | 43 days [E5][E15] | 2 | 141 s | ✓ | ✓ |
| test2 | 9 | How many days after my pre-departure medical check-up did I… | [Errno 8] nodename nor servname provided, or not … | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 10 | How many days after my last day of school before summer did… | [Errno 8] nodename nor servname provided, or not … | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 11 | How many days after getting my sourdough starter did I bake… | [Errno 8] nodename nor servname provided, or not … | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 12 | What was the name of my language exchange partner from Queb… | [Errno 8] nodename nor servname provided, or not … | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 13 | What is my cat's name? | Pixel [E27] | 1 | 80 s | ✓ | ✓ |
| test2 | 14 | What was the name of that coworking space you recommended t… |  | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 15 | What's the name of my neighborhood in Lisbon? |  | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 16 | How many different vegetable varieties have I planted in my… |  | 0 | - | ✗ answered, ref, citations, cited, abstention |  |
| test2 | 17 | What output tube cathode resistor value did I end up using … | 180 ohms [E6][E17][E25] | 3 | 127 s | ✓ | ✓ |
| test2 | 18 | How many times did my systolic reading exceed 130 in August? | 4 [E31][E35][E37][E41] | 4 | 74 s | ✓ | ✓ |

## Every dev call

| run | # | question | Reactor's answer | gold | latency | checks |
|---|---|---|---|---|---|---|
| dev1 | 1 | What type of vehicle model am I currently working on? | Ford F-150 pickup truck [E3] | Ford F-150 pickup truck | 90 s | ✓ |
| dev1 | 2 | Where is the painting 'Ethereal Dreams' by Emma Taylor curr… | In the bedroom, above the bed [E9] | in my bedroom | 24 s | ✓ |
| dev1 | 3 | What new kitchen gadget did I invest in before getting the … | INSUFFICIENT_EVIDENCE | Instant Pot | 72 s | ✓ |
| dev1 | 4 | Where do I currently keep my old sneakers? | A shoe rack in the closet [E3] | in a shoe rack in my closet | 55 s | ✓ |
| dev1 | 5 | How often do I play table tennis with my friends at the loc… | INSUFFICIENT_EVIDENCE | ABSTAIN | 57 s | ✓ |
| dev1 | 6 | How many points do I need to earn to redeem a free skincare… | 300 points [E6] | 100 | 58 s | ✓ |
| dev1 | 7 | How many pieces of furniture did I buy, assemble, sell, or … | 3 [E3, E14, E17] | 4 | 138 s | ✓ |
| dev1 | 8 | At which university did I present a poster on my thesis res… | Harvard University [E2, E1] | Harvard University | 72 s | ✓ |
| dev1 | 9 | What is the total number of siblings I have? | 4 [E3][E5] | 4 | 64 s | ✓ |
| dev1 | 10 | How many health-related devices do I use in a day? | 3 [E2], [E3], [E8] | 4 | 93 s | ✓ |
| dev1 | 11 | How many days did I spend attending workshops, lectures, an… | 3 days [E11, E15] | 3 days | 61 s | ✓ |
| dev1 | 12 | How many fun runs did I miss in March due to work commitmen… | 2 [E3, E16] | 2 | 45 s | ✓ |
| dev1 | 13 | How old will Rachel be when I get married? | INSUFFICIENT_EVIDENCE | ABSTAIN | 51 s | ✓ |
| dev1 | 14 | Which dessert shop in Orlando had the giant milkshakes? | The Sugar Factory [E2] | The Sugar Factory at Icon Park. | 34 s | ✓ |
| dev1 | 15 | I was going through our previous conversation about high-en… | Veja [E4] | Veja | 57 s | ✓ |
| dev1 | 16 | I'm going back to our previous conversation about music the… | MusicTheory.net [E1] | MusicTheory.net | 53 s | ✓ |
| dev1 | 17 | I'm going back to our previous conversation about tradition… | Nostalgia [E1] | Nostalgia | 37 s | ✓ |
| dev1 | 18 | Which romantic Italian restaurant in Rome was it for dinner? | Roscioli [E8] | Roscioli | 62 s | ✓ |
| dev1 | 19 | How many subjects were in the Music and Medicine study on b… | 38 [E5] | 38 subjects | 20 s | ✓ |
| dev1 | 20 | What is the name of the music streaming service have I been… | Spotify [E3] | Spotify | 64 s | ✓ |
| dev1 | 21 | What play did I attend at the local community theater? | The Glass Menagerie [E7] | The Glass Menagerie | 38 s | ✓ |
| dev1 | 22 | How old was I when my grandma gave me the silver necklace? | 18 [E2] | 18 | 45 s | ✓ |
| dev2 | 1 | How many pieces of furniture did I buy, assemble, sell, or … | 3 [E21, E26] | 4 | 54 s | ✓ |
| dev2 | 2 | How many health-related devices do I use in a day? | 4 [E1, E2, E6, E11] | 4 | 63 s | ✓ |
| dev2 | 3 | How many points do I need to earn to redeem a free skincare… | 300 points [E8] | 100 | 60 s | ✓ |
| dev2 | 4 | Where is the painting 'Ethereal Dreams' by Emma Taylor curr… | In the bedroom, above the bed [E3][E9] | in my bedroom | 64 s | ✓ |
| dev2 | 5 | What type of vehicle model am I currently working on? | Ford F-150 pickup truck [E3][E4] | Ford F-150 pickup truck | 50 s | ✓ |
| dev2 | 6 | What new kitchen gadget did I invest in before getting the … | Instant Pot [E5, E8] | Instant Pot | 69 s | ✓ |
| dev2 | 7 | Where do I currently keep my old sneakers? | Under the bed [E1] | in a shoe rack in my closet | 54 s | ✓ |
| dev3 | 1 | Where do I currently keep my old sneakers? | A shoe rack in the closet [E3] | in a shoe rack in my closet | 74 s | ✓ |
