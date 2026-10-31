# Fieldbook deck (Reactive · TechWeek)

The pitch deck in the visual style of the Bison Fellowship final presentation: General Sans, a silver dither background, big semibold headlines, one orange accent per slide, glass pill nav. Only the engine and style were carried over; none of that project's content.

Plain HTML, CSS and JS. No build, no network requests. Open `index.html` directly, or serve the folder:

```bash
python3 -m http.server 5191 --directory pitch-reactive
```

(`.claude/launch.json` has this as `pitch-reactive`.)

## Keys

→ / Space next · ← back · **N** speaker notes · **F** fullscreen · **O** overview · **Q** prepared answers · **?** help. Print to PDF gives one slide per page.

## Slides

The main feature is cleaning a small business's scattered data into one job file. Because the file is clean, the agent can act proactively (Reactive, but proactive). Voice is an extra way in.

For a ~3-minute talk:

1. **Fieldbook**: Cleans your company's data. Then acts on it.
2. It's all over the place. (a pile of spreadsheets, email threads, PDFs, photos, WhatsApp, SMS, voice notes, paper)
3. "Good morning, any news about my car?" Click: Marek is under a car. Kuba has the answer.
4. It cleans the mess. (raw sources → one file: dated, cited, newest wins)
5. Anna gets an answer. Click: She said that on Monday. It remembered.
6. It doesn't wait to be asked. (Spotted · Missing · Next step, the backend's conflict / unknown / action fields) Click: Clean data makes it safe to act.
7. Plus: No typing. Just talk. (voice app, ElevenLabs)
8. Messy in. Clean out. (Collect → Clean → Act)
9. Plug it in. It organizes. (emails, Excel, notes, chats, voice notes flow into a live screenshot of the current app, `assets/app/overview.png`; email and Excel connectors labelled as next)
10. 147× less text for Reactor to read per question.
11. Idea. Harness. Application. (one slide for the three judging rows; one click per column)
12. Clean data. Proactive agent. Thank you · Team Reactive

Q&A (press Q): Quote or keep (the job card) · Is this only for garages? · Market in Poland · Why not read the whole history.

The old "people who fix things" and "one car, five channels" slides live on in the speaker notes of slides 2 and 3.

Details, sources and the numbers kept off the slides are in each slide's `<aside class="notes">`.

## Files

- `engine.css`, `script.js`, `dither.js`: the deck engine taken from the Bison deck (tokens, background, navigation, fragments, Q&A mode, video, print). `script.js` also gained the **N** notes panel.
- `styles.css`: the Fieldbook slide layouts and motion.
- `assets/fonts`: General Sans (Fontshare Free Font License, `LICENSE-FFL.txt`).

To refresh the app screenshot, run the backend (`PORT=8788 python3 backend/server.py`), capture http://127.0.0.1:8788/#overview at 1440×900 @2x once it shows LIVE, crop to the main column and save over `assets/app/overview.png`.
