# OpenToVibe deck (Reactive · TechWeek)

The pitch deck in the visual style of the Bison Fellowship final presentation: General Sans, a dither background, big semibold headlines, glass pill nav. Colours follow the app (sage background, deep green, lime highlights). Only the engine and style were carried over; none of that project's content.

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

1. **OpenToVibe**: Cleans your company's data. Then acts on it.
2. It's all over the place. (five sources: Excel, email, WhatsApp, voice note, paper)
3. And it never stops. (a looping feed of new messages; click: workers, owner, agent)
4. It cleans the mess. (app screenshots: 193 messages → 20 jobs, `assets/app/messages.png`, `jobs.png`)
5. It doesn't wait to be asked. (Spotted · Missing · Next step) Click: Clean data makes it safe to act.
6. No typing. Just talk. (phone video of the voice app, `assets/video/voice-app.mp4`, replayed reading)
7. Plug it in. It organizes. (sources next to the live overview, `assets/app/overview.png`; email and Excel connectors labelled as next)
8. 147× less text for Reactor to read per question.
9. Idea. Harness. Application. (one click per column)
10. Clean data. Proactive agent. Thank you · Team Reactive

Q&A (press Q): Quote or keep (the job card) · Is this only for garages? · Market in Poland · Why not read the whole history.

The G-118 story (Anna, Kuba's voice note) lives in the speaker notes of slide 3.

Details, sources and the numbers kept off the slides are in each slide's `<aside class="notes">`.

## Files

- `engine.css`, `script.js`, `dither.js`: the deck engine taken from the Bison deck (tokens, background, navigation, fragments, Q&A mode, video, print). `script.js` also gained the **N** notes panel.
- `styles.css`: the slide layouts and motion.
- `assets/fonts`: General Sans (Fontshare Free Font License, `LICENSE-FFL.txt`).

To refresh the app screenshot, run the backend (`PORT=8788 python3 backend/server.py`), capture http://127.0.0.1:8788/#overview at 1440×900 @2x once it shows LIVE, crop to the main column and save over `assets/app/overview.png`.

The voice video was recorded from the app at `/voice/` with a fake microphone and stubbed routes: the transcript and result replay an earlier real reading, so no paid API was called and nothing was written to the backend. The app itself still shows its old "fieldbook" name.
