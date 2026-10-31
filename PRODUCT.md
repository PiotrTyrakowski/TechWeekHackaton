# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: the owner of a small Polish trades business.** Garages (car workshops) first; plumbers, electricians, installers and renovation crews next. In the demo this is Marek, who runs Marek's Garage. He keeps the jobs straight, answers clients and pays for the tool. Each job's history is spread across phone calls, voice notes, SMS, WhatsApp and paper order sheets, and nobody joins them up, because the owner is usually under a car.

Other people the product touches (not design priorities):

- **Workers in the field** (Kuba, the mechanic): their hands are busy, so they talk instead of typing. Their only input is a voice note.
- **Clients** (Anna Nowak): they never open the app. They only receive the reply drafted from the job file.
- **Hackathon judges**: the Reactive AI team, plus a jury looking from a B2B sales and VC angle. They see the product only through the decks and the recorded demo.

## Product Purpose

Fieldbook turns what trades people say into an up-to-date job file and an answer for the client. A worker talks, the job card updates with each change quoted from the note, and the owner gets a reply to the client that is drafted from the card.

What success looks like in the demo: Anna's "any news about my car?" gets a correct answer without Marek phoning Kuba or digging through old messages. The answer remembers what she said on Monday: she needs the car before the weekend.

## Positioning

**It only writes what it can quote.** Every change on the card carries the exact words from the note that it came from. Anything the note doesn't mention stays as it was; for example, the price stays at 1,450 PLN.

Behind the card, our retrieval picks only the lines that answer from the whole job history, and Reactor (Reactive AI's model) writes the answer.

## Operating Context

- **The flow** is one screen with three steps: *Kuba talks → The card updates → Anna gets an answer.*
- **Job card fields:** Status, Parts, Price, Ready, Invoice. Status is always one of: Waiting for parts, In progress, Done.
- **The canonical scenario is the garage.** Marek's Garage, job G-118, Anna Nowak's VW Golf VII, timing belt + water pump, 1,450 PLN accepted, Kuba's voice note on Thursday 29 October.
  - The app reads it from `app/src/data/demo.ts`.
  - The backend copy is `backend/scenario/garage.json`; a test fails if the two drift apart.
  - The Lipowa renovation scenario from the team plan v2 was dropped.
- **Language:** the market is Polish businesses, but the pitch and the app are in English. Money is in PLN; phone numbers and plates use Polish formats.
- **Surfaces:**
  - `app/`: a Next.js (React) single screen.
  - `pitch/jury.html` and `pitch/reactive-ai.html`: 1920×1080 decks with speaker notes.
  - `pitch/media/fieldbook-demo.mp4`: recorded from the app with `npm run record`.

## Capabilities and Constraints

- **Voice input:** the microphone level drives the waveform. Chrome's live speech recognition runs when available (en-GB). The audio is also recorded so that `POST /transcribe` can take over, but no backend implements that endpoint yet.
- **Extraction:** the app sends the note to `POST /extract`, and `backend/` asks Reactor. Before any line reaches the card:
  - the quoted words must be in the note;
  - `UNCHANGED` keeps the field as it is;
  - the status must be one of the three;
  - `INSUFFICIENT_EVIDENCE` changes nothing.

  Rejected lines never touch the card.
- **Reactor is slow,** often a minute or more per answer. The app shows "Asking Reactor… Ns" while it waits. It falls back to the scripted note and simple rules when the backend is off, busy or fails.
- **The team shares one Reactor agent.** The backend calls it only with `REACTOR_LIVE=1`, and never while the benchmark run (`solution/run.py --split`) is going.
- **The Reactor access key** is never committed, pasted into a chat or put on a command line. It is set only through the hidden prompt.
- **Terminology:** job, job card / job file, voice note, owner, worker, client. The `quote` field is labelled "Price" on screen.
- **Undecided** (placeholders on the decks, not to be filled with invented values):
  - the final product name (Fieldbook is a working name);
  - the team name;
  - the price per business per month;
  - the ask;
  - contact details;
  - a real tradesperson's quote.

## Brand Commitments

- **Name:** Fieldbook, a working name. No logo exists.
- **Less information (the user's standing rule for decks and app):** one idea per slide or screen — a headline, one visual, a few words. Detail goes into the speaker notes. Prefer one big number over several, and titles over paragraphs.
- **Judges:** show no logos, and don't claim any judge's company as a customer. Don't name the judges' companies on slides.
- **Copy voice:** short, plain and concrete, in trades language. Step titles name who acts ("Kuba talks", "Anna gets an answer").

## Evidence on Hand

- **The demo video** `pitch/media/fieldbook-demo.mp4` (about 23 s) is shown as "Recorded prototype · scripted note". It must be re-recorded whenever the app's look changes.
- **147× less text to read.** Per question, Reactor reads a median of about 11k characters instead of about 1.6M of history, over the 146 Memory Retrieval Challenge test questions. This was measured from the messages `solution/` builds; it is not a scored run. Code and method are in `solution/README.md`.
- **Partial dev check (speaker notes only):** 14 of 15 judged answers right, "I don't know" handled 2/2, evidence F1 0.86. Too small a sample to put on a slide.
- **Market sizes** (jury deck):
  - about 90,000 installers, from GUS data via BOŚ Bank, Oct 2024 (PKD 43.2);
  - about 18–24k car workshops: 17.7k independent (Auto Świat) and 24k (SDCM via PAP).
- **Reply-time stat** (jury deck speaker notes only): more than half of customers expect a reply within the hour, and only one business in five manages it.
- **Absent, so never fabricate:**
  - customers, pilots or testimonials;
  - pricing and the ask;
  - a scored test-split result;
  - Reactor's real live answer to the demo note. The deck lines are labelled as expected until the team has the real answer.

## Product Principles

1. **Quote or keep.** A field changes only when the note says so, and the words that say it stay attached.
2. **Talk, don't type.** The worker's only job is to speak. Nothing asks them to fill in a form.
3. **End in an answer for the client.** Every update leads to a reply the owner can send.
4. **Less on screen.** One idea at a time. Anything that doesn't carry the point goes into the notes.
5. **Only honest numbers.** Every number is measured or sourced, and scripted or recorded material is labelled as such.
