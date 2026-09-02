/* Guided tour engine.

   The product's value is spatial - "the ad said 2 100 zł, this number here
   says 3 700 zł" only lands if "here" is a thing you're looking at. So this
   dims the page and cuts a hole around one real control at a time, and
   (mostly) waits for the user to click that control themselves rather than
   driving for them. They finish knowing where things are, not just that they
   exist.

   Three things make this harder here than in a SPA, and shape the design:

   1. #main-content is swapped wholesale on every filter change, sort and
      view switch, and _chrome_oob.html replaces the nav/sidebar out-of-band
      on top of that. Any element a step points at can be destroyed and
      recreated at any moment, so the spotlight re-anchors on htmx:afterSettle
      rather than holding an element reference.
   2. Steps span full page loads (/galeria -> /mapa -> /porownaj2), so the
      position has to live in sessionStorage, not a JS variable.
   3. The target may not exist yet when a step becomes current (an htmx
      response still in flight). Steps therefore *poll* for their target and
      fall back to a centred card rather than hard-locking the tour.

   Scoped to demo listings on purpose: the tour tells the user to change a
   status and open things, and doing that to listings they collected
   themselves would be editing real data to make a point. */

const TOUR_KEY = "tour:state";
const TOUR_SEEN_KEY = "tour:seen";
const TOUR_PAUSED_KEY = "tour:paused";
const TOUR_TARGET_POLL_MS = 120;
const TOUR_TARGET_TIMEOUT_MS = 4000;

let _tourSteps = [];       // set by tour-steps.js
let _tourEls = null;       // {panels, ring, card} once mounted
let _tourPollTimer = null;
let _tourCleanup = [];     // listeners to drop when the tour ends
let _lastEnteredStep = null;  // so onEnter fires once per step, not per re-render

function tourState() {
    try {
        return JSON.parse(sessionStorage.getItem(TOUR_KEY) || "null");
    } catch (e) {
        return null;
    }
}

function setTourState(state) {
    if (state) sessionStorage.setItem(TOUR_KEY, JSON.stringify(state));
    else sessionStorage.removeItem(TOUR_KEY);
}

function tourActive() {
    return tourState() !== null;
}
window.tourActive = tourActive;

function tourPaused() { return localStorage.getItem(TOUR_PAUSED_KEY) === "1"; }

function updateTourLauncher() {
    const launcher = document.getElementById("tour-launcher");
    if (!launcher) return;
    const resumable = tourActive() && tourPaused();
    launcher.classList.toggle("tour-resume-pulse", resumable);
    launcher.href = resumable ? "/galeria?wznow-samouczek=1" : "/galeria?samouczek=1";
    launcher.title = resumable ? "Wznów samouczek" : "Uruchom samouczek";
    launcher.setAttribute("aria-label", launcher.title);
}

function collapseDrawerGroups() {
    Object.keys(localStorage)
        .filter((k) => k.startsWith("grp:"))
        .forEach((k) => localStorage.removeItem(k));
}
window.tourCollapseGroups = collapseDrawerGroups;

function startTour(mode = "choose") {
    localStorage.setItem(TOUR_SEEN_KEY, "1");
    localStorage.removeItem(TOUR_PAUSED_KEY);
    if (mode === "short" && window.TOUR_SHORT_STEPS) _tourSteps = window.TOUR_SHORT_STEPS;
    else if (window.TOUR_LONG_STEPS) _tourSteps = window.TOUR_LONG_STEPS;
    collapseDrawerGroups();
    setTourState({ i: mode === "long" ? 1 : 0, mode });
    renderTour();
    updateTourLauncher();
}
window.startTour = startTour;

function endTour() {
    _lastEnteredStep = null;
    setTourState(null);
    localStorage.removeItem(TOUR_PAUSED_KEY);
    unmountTour();
    updateTourLauncher();
}
window.endTour = endTour;

function pauseTour() {
    if (!tourActive()) return;
    localStorage.setItem(TOUR_PAUSED_KEY, "1");
    unmountTour();
    updateTourLauncher();
}

function resumeTour() {
    if (!tourActive()) return startTour();
    localStorage.removeItem(TOUR_PAUSED_KEY);
    renderTour();
    updateTourLauncher();
}

function currentStep() {
    const st = tourState();
    if (!st) return null;
    return _tourSteps[st.i] || null;
}

/* The tour teaches the drawer one collapsed section at a time, so it needs
   the sections to actually be where it left them. Steps that spotlight the
   whole panel (selector "#drawer-panel") cut a hole around *everything* -
   every section header included - so nothing stopped a click from folding
   the panel open and desynchronising every later step, which then rings a
   heading that has moved or a body that is already showing.

   So: while the tour is running, a section header only responds if the
   current step is the one asking for that exact header. Capture phase and
   stopPropagation, because Alpine's own @click sits on the same element and
   would otherwise still fire. Everything outside the drawer is unaffected -
   the overlay already blocks that by covering it. */
/* Matches the toggles themselves, never their contents - a section's fields
   and tabs stay fully usable while it's open. Drawer group headings carry
   data-tour-group; the "Pytania" card carries data-tour-toggle. */
const TOUR_TOGGLES = "[data-tour-group], [data-tour-toggle]";

function guardDrawerGroups(ev) {
    const toggle = ev.target.closest && ev.target.closest(TOUR_TOGGLES);
    if (!toggle) return;

    const step = currentStep();
    const wanted = step && step.selector ? document.querySelector(step.selector) : null;
    if (wanted === toggle) return;  // this step is the one telling them to click it

    ev.preventDefault();
    ev.stopPropagation();
}

function advanceTour() {
    const st = tourState();
    if (!st) return;
    if (st.i + 1 >= _tourSteps.length) {
        finishTour();
        return;
    }
    setTourState({ ...st, i: st.i + 1 });
    renderTour();
}
window.advanceTour = advanceTour;

function finishTour() {
    setTourState(null);
    unmountTour();
    // A plain alert would be jarring after a guided flow; reuse the card.
    if (!mountTour()) return;
    _tourEls.card.innerHTML = `
        <div class="tour-card-title">Gotowe</div>
        <p class="tour-card-text">
            Możesz teraz przejść po aplikacji własnym tempem. Jeśli zechcesz
            zacząć od nowa, uruchom samouczek ponownie z ikony 🎓 u góry.
        </p>
        <div class="tour-card-actions">
            <button type="button" class="btn" data-tour-action="end">Jasne</button>
        </div>`;
    placeCardCentred();
    hideSpotlight();
}

// --- DOM ---------------------------------------------------------------

function mountTour() {
    if (_tourEls) return _tourEls;
    if (!document.body) return null;  // called before the parser reached <body>
    const mk = (cls) => {
        const el = document.createElement("div");
        el.className = cls;
        document.body.appendChild(el);
        return el;
    };
    // Four panels rather than one overlay with a CSS mask: the gap between
    // them *is* the hole, so the highlighted control stays genuinely
    // clickable while every other pixel is covered and blocked.
    const panels = ["top", "right", "bottom", "left"].map(() => mk("tour-panel"));
    const ring = mk("tour-ring");
    const card = mk("tour-card");
    _tourEls = { panels, ring, card };

    const onClick = (e) => {
        const action = e.target.closest("[data-tour-action]");
        if (!action) return;
        e.preventDefault();
        e.stopPropagation();
        const kind = action.getAttribute("data-tour-action");
        if (kind === "end") endTour();
        else if (kind === "pause") pauseTour();
        else if (kind === "next") advanceTour();
        else if (kind === "tour-mode") startTour(action.dataset.tourMode);
    };
    card.addEventListener("click", onClick);

    const reposition = () => positionTour();
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    document.addEventListener("htmx:afterSettle", renderTour);
    document.addEventListener("click", guardDrawerGroups, true);
    _tourCleanup = [
        () => window.removeEventListener("resize", reposition),
        () => window.removeEventListener("scroll", reposition, true),
        () => document.removeEventListener("htmx:afterSettle", renderTour),
        () => document.removeEventListener("click", guardDrawerGroups, true),
    ];
    return _tourEls;
}

function unmountTour() {
    if (_tourPollTimer) { clearTimeout(_tourPollTimer); _tourPollTimer = null; }
    if (_whenTimer) { clearInterval(_whenTimer); _whenTimer = null; }
    _settleTimers.forEach(clearTimeout);
    _settleTimers = [];
    _tourCleanup.forEach((fn) => fn());
    _tourCleanup = [];
    if (!_tourEls) return;
    [..._tourEls.panels, _tourEls.ring, _tourEls.card].forEach((el) => el.remove());
    _tourEls = null;
    document.body.classList.remove("tour-open");
}

// Collapse all four panels to nothing: no dimming, no click-blocking, card
// only. Used while parked on a page this step doesn't belong to.
function clearPanels() {
    if (!_tourEls) return;
    _tourEls.ring.style.display = "none";
    _tourEls.panels.forEach((p) => setRect(p, 0, 0, 0, 0));
}

function hideSpotlight() {
    if (!_tourEls) return;
    // One panel covering everything, no hole - for steps with no target
    // and the closing card, where there's nothing to point at.
    const { panels, ring } = _tourEls;
    ring.style.display = "none";
    const w = window.innerWidth, h = window.innerHeight;
    setRect(panels[0], 0, 0, w, h);
    [1, 2, 3].forEach((i) => setRect(panels[i], 0, 0, 0, 0));
}

function setRect(el, x, y, w, h) {
    el.style.left = x + "px";
    el.style.top = y + "px";
    el.style.width = Math.max(0, w) + "px";
    el.style.height = Math.max(0, h) + "px";
}

// A target's box is often not final at the moment a step renders: smooth
// scrolling is still running, the drawer is mid width-transition, and
// MapLibre positions its markers by transform only once the map settles -
// which is how the spotlight ended up ringing empty space next to the
// "Praca" pin. Re-measure over the next second rather than trying to hook
// every possible settle event.
const SETTLE_MS = [80, 200, 400, 700, 1000];
let _settleTimers = [];

function settleReposition() {
    _settleTimers.forEach(clearTimeout);
    _settleTimers = SETTLE_MS.map((ms) => setTimeout(positionTour, ms));
}

function positionTour() {
    const step = currentStep();
    if (!_tourEls || !step) return;
    if (!step.selector) { hideSpotlight(); placeCardCentred(); return; }

    const target = document.querySelector(step.selector);
    if (!target) { hideSpotlight(); placeCardCentred(); return; }

    const r = target.getBoundingClientRect();
    const pad = step.pad === undefined ? 6 : step.pad;
    const x = r.left - pad, y = r.top - pad;
    const w = r.width + pad * 2, h = r.height + pad * 2;
    const vw = window.innerWidth, vh = window.innerHeight;

    const { panels, ring } = _tourEls;
    setRect(panels[0], 0, 0, vw, Math.max(0, y));                  // above
    setRect(panels[1], x + w, y, Math.max(0, vw - (x + w)), h);    // right
    setRect(panels[2], 0, y + h, vw, Math.max(0, vh - (y + h)));   // below
    setRect(panels[3], 0, y, Math.max(0, x), h);                   // left

    ring.style.display = "block";
    setRect(ring, x, y, w, h);

    placeCardNear(x, y, w, h, vw, vh);
}

function placeCardNear(x, y, w, h, vw, vh) {
    const card = _tourEls.card;
    card.style.display = "block";
    const cw = Math.min(360, vw - 32);
    card.style.width = cw + "px";
    const ch = card.offsetHeight || 160;

    // A target taller than half the viewport (the filter sidebar, the map)
    // has no room above or below, so the card gets clamped and covers the
    // thing it's pointing at. Sit beside it instead - on whichever side has
    // more space.
    if (h > vh * 0.5) {
        const roomRight = vw - (x + w);
        const left = roomRight >= cw + 24
            ? x + w + 12
            : Math.max(12, x - cw - 12);
        card.style.left = Math.max(12, Math.min(left, vw - cw - 12)) + "px";
        card.style.top = Math.max(12, Math.min(y + h / 2 - ch / 2, vh - ch - 12)) + "px";
        return;
    }

    // Prefer below the target, flip above when there isn't room.
    let top = y + h + 12;
    if (top + ch > vh - 12) top = Math.max(12, y - ch - 12);
    let left = x + w / 2 - cw / 2;
    left = Math.max(12, Math.min(left, vw - cw - 12));
    card.style.top = top + "px";
    card.style.left = left + "px";
}

function placeCardCentred() {
    const card = _tourEls.card;
    card.style.display = "block";
    const vw = window.innerWidth, vh = window.innerHeight;
    const cw = Math.min(420, vw - 32);
    card.style.width = cw + "px";
    const ch = card.offsetHeight || 180;
    card.style.left = Math.max(12, vw / 2 - cw / 2) + "px";
    card.style.top = Math.max(12, vh / 2 - ch / 2) + "px";
}

// --- Rendering ---------------------------------------------------------

function renderCard(step, targetFound) {
    const card = _tourEls.card;
    const st = tourState();
    const n = st ? st.i + 1 : 1;
    const total = _tourSteps.length;

    const waiting = (step.advance === "click" && targetFound) || !gateOpen(step);
    const actions = step.choices
        ? step.choices.map((choice) => `<button type="button" class="btn" data-tour-action="tour-mode" data-tour-mode="${choice.mode}">${choice.label}</button>`).join("")
        : waiting
        ? `<span class="tour-card-hint">${step.clickHint || "Kliknij podświetlony element"}</span>`
        : `<button type="button" class="btn" data-tour-action="next">${step.nextLabel || "Dalej"}</button>`;

    card.innerHTML = `
        <div class="tour-card-head">
            <span class="tour-card-step">${n} / ${total}</span>
            <button type="button" class="tour-card-close" data-tour-action="pause" title="Wstrzymaj samouczek">✕</button>
        </div>
        <div class="tour-card-title">${step.title}</div>
        <p class="tour-card-text">${step.text}</p>
        <div class="tour-card-actions">
            ${actions}
        </div>`;
}

let _whenTimer = null;

function gateOpen(step) {
    if (step.advance !== "when" || typeof step.when !== "function") return true;
    try {
        return !!step.when();
    } catch (e) {
        return false;
    }
}

function armWhenAdvance(step, targetFound) {
    if (_whenTimer) { clearInterval(_whenTimer); _whenTimer = null; }
    if (step.advance !== "when" || typeof step.when !== "function") return;
    const startedAt = tourState().i;
    let last = null;
    const tick = () => {
        const st = tourState();
        if (!st || st.i !== startedAt) { clearInterval(_whenTimer); _whenTimer = null; return; }
        const ok = gateOpen(step);
        // Re-render only when the answer changes, so the card isn't rebuilt
        // four times a second under the user's cursor.
        if (ok !== last) {
            last = ok;
            renderCard(step, targetFound);
            positionTour();
        }
    };
    tick();
    _whenTimer = setInterval(tick, 250);
}

function armClickAdvance(step, target) {
    if (step.advance !== "click" || !target) return;
    if (target.dataset.tourArmed === String(tourState().i)) return;
    target.dataset.tourArmed = String(tourState().i);
    // Capture phase and no preventDefault: the app's own handler still runs,
    // so the click both does its real job and moves the tour along.
    target.addEventListener("click", function onceHandler() {
        target.removeEventListener("click", onceHandler, true);
        // Synchronously, not on a timer: steps whose target is a link
        // navigate immediately and would kill a pending timeout, leaving
        // the next page parked on the previous step. The next step polls
        // for its own target, so arriving "too early" is already handled.
        advanceTour();
    }, true);
}

function renderTour() {
    if (!tourActive()) { unmountTour(); return; }
    if (tourPaused()) { unmountTour(); updateTourLauncher(); return; }
    const step = currentStep();
    if (!step) { endTour(); return; }

    if (!mountTour()) return;
    document.body.classList.add("tour-open");

    // Step belongs to another page - let the user get there; the tour picks
    // up again on load because its position is in sessionStorage.
    //
    // Parked means *not blocking*: dimming a page the tour has no step for
    // (say the user wandered to /konto mid-tour) traps them behind an
    // overlay whose only escape is the card's ✕. Show the card, leave the
    // page usable, and say where to go back to.
    if (step.path && window.location.pathname !== step.path) {
        clearPanels();
        renderCard({ ...step, advance: "next" }, false);
        _tourEls.card.querySelector(".tour-card-text").textContent =
            `Ten krok samouczka jest na stronie ${step.path}. Wróć tam, żeby go zobaczyć.`;
        placeCardCentred();
        return;
    }

    if (_tourPollTimer) { clearTimeout(_tourPollTimer); _tourPollTimer = null; }

    // Once per arrival at this step, before we look for the target: a step
    // may need to reveal what it's about to point at.
    const st = tourState();
    if (typeof step.onEnter === "function" && _lastEnteredStep !== st.i) {
        _lastEnteredStep = st.i;
        try { step.onEnter(); } catch (e) { /* never let copy break the tour */ }
    }

    const deadline = Date.now() + TOUR_TARGET_TIMEOUT_MS;

    const startedWaiting = Date.now();
    let showedWaiting = false;

    const attempt = () => {
        if (!tourActive()) return;
        const target = step.selector ? document.querySelector(step.selector) : null;
        if (step.selector && !target) {
            if (Date.now() < deadline) {
                // Say something while we wait. Without this the previous
                // step's panels stayed frozen on screen for up to four
                // seconds - the page dimmed, nothing highlighted, no card
                // that made sense - which reads as the tour having died.
                if (!showedWaiting && Date.now() - startedWaiting > 500) {
                    showedWaiting = true;
                    clearPanels();
                    renderCard({ ...step, advance: "next" }, false);
                    _tourEls.card.querySelector(".tour-card-text").textContent =
                        "Czekam, aż ten element pojawi się na ekranie…";
                    placeCardCentred();
                }
                _tourPollTimer = setTimeout(attempt, TOUR_TARGET_POLL_MS);
                return;
            }
            // Never arrived. Show the text with a way forward rather than
            // leaving a dimmed screen and no exit.
            clearPanels();
            renderCard({ ...step, advance: "next" }, false);
            placeCardCentred();
            return;
        }
        if (target && step.scroll !== false) {
            target.scrollIntoView({ block: "center", behavior: "smooth" });
        }
        renderCard(step, !!target);
        positionTour();
        armClickAdvance(step, target);
        armWhenAdvance(step, !!target);
        settleReposition();
    };
    attempt();
}
window.renderTour = renderTour;

// --- Introspection, for the admin dev panel (static/js/devtools.js) ------
// The tour is the one part of this app with no server-side state to inspect
// and no test coverage, so being able to jump straight to step 14 instead of
// clicking fourteen times is the difference between fixing a step in a
// minute and in ten.
function tourStepInfo() {
    const st = tourState();
    return {
        active: st !== null,
        index: st ? st.i : null,
        total: _tourSteps.length,
        step: st ? _tourSteps[st.i] : null,
    };
}
window.tourStepInfo = tourStepInfo;

function tourGoto(i) {
    const idx = Math.max(0, Math.min(i, _tourSteps.length - 1));
    setTourState({ i: idx });
    renderTour();
    return tourStepInfo();
}
window.tourGoto = tourGoto;

// Steps are registered by tour-steps.js, which loads after this file.
//
// Both scripts live in <head> (base.html), so at the moment this runs
// document.body can still be null and mountTour()'s appendChild would throw.
// Wait for the parser when that's the case rather than moving the tags to
// the end of <body>, which would leave the tour a frame behind everything
// else on the page.
function registerTourSteps(steps) {
    _tourSteps = steps;
    window.TOUR_LONG_STEPS = steps;
    const existing = tourState();
    if (existing && existing.mode === "short" && window.TOUR_SHORT_STEPS) {
        _tourSteps = window.TOUR_SHORT_STEPS;
    }

    /* ?samouczek=1 starts the tour on arrival - the entry point used by
       /pomoc and the account menu, which are rendered by pages that can't
       call startTour() directly (the FAQ runs outside the app shell, and a
       plain link can't run JS on the destination). The parameter is stripped
       straight away so a reload, a shared link or a back-button press
       doesn't silently restart the tour on top of whatever the user is
       doing. */
    const params = new URLSearchParams(window.location.search);
    const wantsTour = params.get("samouczek") === "1";
    const wantsResume = params.get("wznow-samouczek") === "1";
    if (wantsTour || wantsResume) {
        const url = new URL(window.location.href);
        url.searchParams.delete("samouczek");
        url.searchParams.delete("wznow-samouczek");
        window.history.replaceState({}, "", url);
    }

    // Auto-welcome belongs to the demo's gallery entry point only. Other
    // pages (for example Help) must remain usable when opened directly.
    const firstVisit = window.location.pathname === "/galeria"
        && localStorage.getItem(TOUR_SEEN_KEY) !== "1";
    if (!wantsTour && !wantsResume && !tourActive() && !firstVisit) return;
    const boot = () => {
        if (wantsTour || firstVisit) startTour();
        else if (wantsResume) resumeTour();
        else renderTour();
        updateTourLauncher();
        const launcher = document.getElementById("tour-launcher");
        if (launcher && !launcher.dataset.tourBound) {
            launcher.dataset.tourBound = "1";
            launcher.addEventListener("click", (event) => {
                if (tourActive() && tourPaused() && window.location.pathname === "/galeria") {
                    event.preventDefault();
                    resumeTour();
                }
            });
        }
    };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot, { once: true });
    } else {
        boot();
    }
}
window.registerTourSteps = registerTourSteps;
