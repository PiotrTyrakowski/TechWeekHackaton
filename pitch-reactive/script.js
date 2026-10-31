/*
 * Deck engine — navigation, fragments, appendix (Q&A) mode, video plumbing,
 * speaker notes (N). Per-slide animation is CSS keyed on `.active`.
 */
(() => {
  "use strict";

  const allSlides = [...document.querySelectorAll(".slide")];
  const mainSlides = allSlides.filter((s) => !s.classList.contains("appendix"));
  const qaSlides = allSlides.filter((s) => s.classList.contains("appendix"));
  const prevButton = document.querySelector("#prev");
  const nextButton = document.querySelector("#next");
  const progress = document.querySelector("#progress");
  const counter = document.querySelector("#counter");
  const helpButton = document.querySelector("#help");
  const helpDialog = document.querySelector("#help-dialog");
  const qaDialog = document.querySelector("#qa-dialog");
  const notesPanel = document.querySelector("#notes");
  const deckWidth = 1280;
  const deckHeight = 720;

  let mode = "main"; // "main" | "qa"
  let iMain = 0; // survives appendix excursions — Q returns exactly here
  let iQa = 0;
  let touchX = null;
  const fragmentSteps = new WeakMap();

  const pad = (value) => String(value).padStart(2, "0");
  const slidesOf = (m) => (m === "qa" ? qaSlides : mainSlides);
  const currentIndex = () => (mode === "qa" ? iQa : iMain);

  // ---------- On-click fragments ----------

  function maxFragmentStep(slide) {
    return Math.max(
      0,
      ...[...slide.querySelectorAll(".fragment")].map((fragment) =>
        Number.parseInt(fragment.dataset.step || "0", 10),
      ),
    );
  }

  function fragmentStep(slide) {
    return fragmentSteps.get(slide) || 0;
  }

  function renderFragments(slide) {
    const current = fragmentStep(slide);
    slide.dataset.currentStep = String(current);
    for (const fragment of slide.querySelectorAll(".fragment")) {
      const step = Number.parseInt(fragment.dataset.step || "0", 10);
      fragment.classList.toggle("is-visible", step <= current);
      fragment.classList.toggle(
        "is-past",
        fragment.classList.contains("fragment-replace") && step < current,
      );
    }
  }

  function stepFragments(delta) {
    const slide = slidesOf(mode)[currentIndex()];
    if (!slide) return false;
    const current = fragmentStep(slide);
    const next = Math.min(Math.max(current + delta, 0), maxFragmentStep(slide));
    if (next === current) return false;
    fragmentSteps.set(slide, next);
    render({ updateHash: false });
    for (const video of slide.querySelectorAll(
      `.fragment[data-step="${next}"] video[data-autoplay-once]`,
    )) {
      video.muted = true;
      video.defaultMuted = true;
      video.loop = false;
      video.play().catch(() => {});
    }
    return true;
  }

  function advance() {
    if (stepFragments(1)) return;
    go(currentIndex() + 1);
  }

  function retreat() {
    if (stepFragments(-1)) return;
    go(currentIndex() - 1);
  }

  // ---------- Hash ----------

  function parseHash(hash) {
    const qa = hash.match(/^#q(\d+)$/i);
    if (qa && qaSlides.length) {
      return { mode: "qa", index: Math.min(Math.max(+qa[1] - 1, 0), qaSlides.length - 1) };
    }
    const main = hash.match(/^#(\d+)$/);
    if (main) {
      return { mode: "main", index: Math.min(Math.max(+main[1] - 1, 0), mainSlides.length - 1) };
    }
    return null;
  }

  // ---------- Speaker notes (N) ----------

  function renderNotes() {
    const slide = slidesOf(mode)[currentIndex()];
    const notes = slide?.querySelector(".notes");
    notesPanel.innerHTML = notes ? notes.innerHTML : "<p>No notes for this slide.</p>";
  }

  function toggleNotes() {
    document.body.classList.toggle("show-notes");
  }

  // ---------- Video plumbing ----------

  for (const video of document.querySelectorAll(".slide video")) {
    const frame = video.closest(".video-frame");
    if (frame) {
      video.addEventListener("play", () => frame.classList.add("playing"));
      video.addEventListener("pause", () => frame.classList.remove("playing"));
      video.addEventListener("ended", () => frame.classList.remove("playing"));
      video.addEventListener("click", () => toggleVideo(video));
      const glyph = frame.querySelector(".video-play");
      if (glyph) {
        glyph.addEventListener("click", () => {
          glyph.blur(); // the glyph fades out; focus must not stay on it or Space pauses instead of advancing
          toggleVideo(video);
        });
      }
    }
  }

  function toggleVideo(video) {
    if (video.paused) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
  }

  function playSilent(video, { loop = false } = {}) {
    video.muted = true;
    video.defaultMuted = true;
    video.loop = loop;

    const start = () => {
      const slide = video.closest(".slide");
      const fragment = video.closest(".fragment");
      const visible =
        !fragment ||
        (fragment.classList.contains("is-visible") && !fragment.classList.contains("is-past"));
      if (slide?.classList.contains("active") && visible) {
        video.play().catch(() => {});
      }
    };
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
      window.setTimeout(start, 160);
    } else {
      video.addEventListener("canplay", () => window.setTimeout(start, 160), { once: true });
    }
  }

  function syncVideos() {
    for (const slide of allSlides) {
      const active = slide.classList.contains("active");
      for (const video of slide.querySelectorAll("video")) {
        const fragment = video.closest(".fragment");
        const visibleFragment =
          !fragment ||
          (fragment.classList.contains("is-visible") && !fragment.classList.contains("is-past"));
        if (!active || !visibleFragment) {
          // Leaving a slide pauses AND rewinds — re-entry is always clean.
          video.pause();
          try {
            video.currentTime = 0;
          } catch {
            /* no metadata yet */
          }
        } else if (video.hasAttribute("data-autoplay-once")) {
          playSilent(video);
        } else if (video.hasAttribute("data-autoplay")) {
          // Short muted loops only — sound never autoplays.
          playSilent(video, { loop: true });
        }
      }
    }
  }

  // ---------- Render ----------

  function render({ updateHash = true } = {}) {
    for (const [m, list] of [
      ["main", mainSlides],
      ["qa", qaSlides],
    ]) {
      const current = m === "qa" ? iQa : iMain;
      list.forEach((slide, index) => {
        const active = mode === m && index === current;
        slide.classList.toggle("active", active);
        slide.classList.toggle("before", index < current);
        slide.setAttribute("aria-hidden", active ? "false" : "true");
      });
    }

    const list = slidesOf(mode);
    const current = mode === "qa" ? iQa : iMain;
    const activeSlide = list[current];
    const activeStep = activeSlide ? fragmentStep(activeSlide) : 0;
    const activeMax = activeSlide ? maxFragmentStep(activeSlide) : 0;
    prevButton.disabled = current === 0 && activeStep === 0;
    nextButton.disabled = current === list.length - 1 && activeStep >= activeMax;

    for (const slide of allSlides) renderFragments(slide);

    // Progress tracks the MAIN talk only; in appendix mode it freezes where
    // you left off, and the counter switches to Q-numbering (§8).
    progress.style.width = `${((iMain + 1) / mainSlides.length) * 100}%`;
    counter.textContent =
      mode === "qa"
        ? `Q${iQa + 1} / Q${qaSlides.length}`
        : `${pad(iMain + 1)} / ${pad(mainSlides.length)}`;

    document.body.dataset.mode = mode;
    const title = list[current]?.dataset.title;
    document.title = (title && title !== "OpenToVibe" ? `${title} — OpenToVibe` : "OpenToVibe");
    if (updateHash) {
      history.replaceState(null, "", mode === "qa" ? `#q${iQa + 1}` : `#${iMain + 1}`);
    }
    renderNotes();
    syncVideos();
  }

  function go(next) {
    const list = slidesOf(mode);
    const target = Math.min(Math.max(next, 0), list.length - 1);
    const current = mode === "qa" ? iQa : iMain;
    if (target === current) return;
    if (mode === "qa") iQa = target;
    else iMain = target;
    fragmentSteps.set(list[target], 0);
    render();
  }

  function enterAppendix(index) {
    if (!qaSlides.length) return;
    mode = "qa";
    iQa = Math.min(Math.max(index, 0), qaSlides.length - 1);
    if (qaDialog.open) qaDialog.close();
    document.body.classList.remove("overview"); // overview hides appendix slides
    render();
  }

  function exitAppendix() {
    mode = "main"; // iMain untouched — lands exactly where the talk left off
    render();
  }

  // ---------- Appendix map (Q) ----------

  (() => {
    const list = qaDialog.querySelector("ol");
    if (!qaSlides.length) {
      const empty = document.createElement("p");
      empty.className = "qa-empty";
      empty.textContent = "No appendix slides.";
      list.replaceWith(empty);
      return;
    }
    qaSlides.forEach((slide, index) => {
      const li = document.createElement("li");
      const row = document.createElement("button");
      row.className = "qa-row";
      row.innerHTML = `<b>${index + 1}</b><span></span>`;
      row.querySelector("span").textContent =
        slide.dataset.question || slide.dataset.title || `Slide ${index + 1}`;
      row.addEventListener("click", () => enterAppendix(index));
      li.append(row);
      list.append(li);
    });
  })();

  // Digits jump while the map is open (document handler skips dialog targets).
  qaDialog.addEventListener("keydown", (event) => {
    const n = Number.parseInt(event.key, 10);
    if (Number.isInteger(n) && n >= 1 && n <= qaSlides.length) {
      event.preventDefault();
      enterAppendix(n - 1);
    }
  });

  // ---------- Chrome ----------

  function fitDeck() {
    const scale = Math.min(window.innerWidth / deckWidth, window.innerHeight / deckHeight);
    document.documentElement.style.setProperty("--deck-scale", String(Math.max(scale, 0.1)));
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }

  function toggleOverview() {
    if (mode === "qa") exitAppendix(); 
    document.body.classList.toggle("overview");
    if (document.body.classList.contains("overview")) {
      // The grid is a bird's-eye pause — nothing should keep playing under it.
      for (const video of document.querySelectorAll(".slide video")) video.pause();
    } else {
      render();
    }
  }

  prevButton.addEventListener("click", (e) => {
    e.currentTarget.blur(); // keep arrow keys on the deck, not the button
    retreat();
  });
  nextButton.addEventListener("click", (e) => {
    e.currentTarget.blur();
    advance();
  });

  helpButton.addEventListener("click", (e) => {
    e.currentTarget.blur();
    helpDialog.showModal();
  });
  for (const dialog of [helpDialog, qaDialog]) {
    dialog.querySelector(".dialog-close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (event) => {
      // Backdrop click only — clicks on the dialog's own padding also target
      // the dialog element, so hit-test against its box.
      if (event.target !== dialog) return;
      const r = dialog.getBoundingClientRect();
      const inside =
        event.clientX >= r.left &&
        event.clientX <= r.right &&
        event.clientY >= r.top &&
        event.clientY <= r.bottom;
      if (!inside) dialog.close();
    });
  }

  // Q toggles the map closed again (the document handler skips dialog targets).
  qaDialog.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() === "q") {
      event.preventDefault();
      qaDialog.close();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return; // browser shortcuts stay browser shortcuts
    if (event.target.closest("dialog")) return; // dialogs own their keys
    const key = event.key.toLowerCase();
    if (
      (key === " " || key === "enter") &&
      event.target.closest("a, button, video, [tabindex]")
    ) {
      return; // let the focused control activate
    }

    if (["arrowright", "pagedown", " ", "enter"].includes(key)) {
      event.preventDefault();
      advance();
    } else if (["arrowleft", "pageup", "backspace"].includes(key)) {
      event.preventDefault();
      retreat();
    } else if (key === "home") {
      event.preventDefault();
      go(0);
    } else if (key === "end") {
      event.preventDefault();
      go(slidesOf(mode).length - 1);
    } else if (key === "f") {
      event.preventDefault();
      toggleFullscreen();
    } else if (key === "o") {
      event.preventDefault();
      toggleOverview();
    } else if (key === "n") {
      event.preventDefault();
      toggleNotes();
    } else if (key === "q") {
      event.preventDefault();
      if (mode === "qa") exitAppendix();
      else if (qaSlides.length) qaDialog.showModal();
    } else if (key === "v") {
      event.preventDefault();
      const video = slidesOf(mode)[mode === "qa" ? iQa : iMain]?.querySelector("video");
      if (video) toggleVideo(video);
    } else if (key === "escape") {
      if (document.body.classList.contains("overview")) toggleOverview();
      else if (mode === "qa") exitAppendix();
    } else if (key === "?") {
      helpDialog.showModal();
    }
  });

  document.addEventListener(
    "touchstart",
    (event) => {
      touchX = event.changedTouches[0]?.clientX ?? null;
    },
    { passive: true },
  );

  document.addEventListener(
    "touchend",
    (event) => {
      if (touchX == null) return;
      if (document.body.classList.contains("overview") || document.querySelector("dialog[open]")) {
        touchX = null; // scrolling the grid / a modal is not a swipe
        return;
      }
      const endX = event.changedTouches[0]?.clientX ?? touchX;
      const delta = endX - touchX;
      touchX = null;
      if (Math.abs(delta) < 55) return;
      go((mode === "qa" ? iQa : iMain) + (delta < 0 ? 1 : -1));
    },
    { passive: true },
  );

  mainSlides.forEach((slide, index) => {
    slide.addEventListener("click", (event) => {
      if (event.target.closest("a, button, video")) return;
      if (document.body.classList.contains("overview")) {
        iMain = index;
        mode = "main";
        fragmentSteps.set(slide, 0);
        document.body.classList.remove("overview");
        render();
      } else if (mode === "main" && iMain === index) {
        advance();
      }
    });
  });

  window.addEventListener("hashchange", () => {
    const parsed = parseHash(location.hash);
    if (!parsed) return;
    mode = parsed.mode;
    if (parsed.mode === "qa") {
      iQa = parsed.index;
      fragmentSteps.set(qaSlides[iQa], 0);
    } else {
      iMain = parsed.index;
      fragmentSteps.set(mainSlides[iMain], 0);
    }
    document.body.classList.remove("overview"); // a deep-link means "show me that slide"
    render({ updateHash: false });
  });

  window.addEventListener("resize", fitDeck, { passive: true });

  const initial = parseHash(location.hash);
  if (initial) {
    mode = initial.mode;
    if (initial.mode === "qa") iQa = initial.index;
    else iMain = initial.index;
  }
  fitDeck();
  render({ updateHash: false });
})();
