/* Shared state and helpers every other static/js file builds on.
   Loaded first (see base.html) - these are plain classic scripts, not ES
   modules, so everything below shares one global scope with the rest of
   static/js/ and no import/export is involved. Anything used by two or more
   of the other files belongs here; anything used by exactly one belongs in
   that one. */

document.addEventListener("alpine:init", () => {
    // compareMode/compareSel live in the store rather than in an x-data on the
    // gallery, because #main-content is swapped wholesale on every filter
    // change and sort - component state inside it is destroyed each time, and
    // a selection that evaporated when you filtered would be useless.
    Alpine.store("ui", { drawerOpen: false, compareMode: false, compareSel: [] });
});

// Called from the gallery card's hx-trigger filter: in compare mode a click
// selects instead of opening the drawer, so htmx must not fire the drawer
// request at all.
function compareModeOn() {
    return !!(window.Alpine && Alpine.store("ui") && Alpine.store("ui").compareMode);
}
window.compareModeOn = compareModeOn;

// Single point of contact between JS and the brand palette (static/css/
// brand.css) - anywhere a color has to be a real value rather than a CSS
// class (MapLibre markers/circles set via inline style or paint properties)
// resolves it here instead of hardcoding a hex. `fallback` only fires if the
// stylesheet somehow hasn't loaded yet; it should always match brand.css.
function brandColor(varName, fallback) {
    if (!varName) return fallback;
    const v = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    return v || fallback;
}

// --- Cross-view "currently open" highlight ---
// Marks whichever listing the drawer is showing with a ring (gallery card)
// or outline (map marker), so it's obvious at a glance which one you're
// looking at - especially on /mapa where dozens of markers otherwise look
// identical. Driven from JS rather than server-rendered state because the
// same listing can be highlighted simultaneously across two different view
// types (gallery card behind the drawer + map marker), and both need to
// survive the view refreshing itself out from under the drawer after an edit.
let _activeListingId = null;

function applyActiveHighlight() {
    document.querySelectorAll(".gallery-card[data-listing-id]").forEach((el) => {
        el.classList.toggle("listing-active-outline", el.dataset.listingId === String(_activeListingId));
    });
    // Defined in map.js, which only does anything on /mapa - absent elsewhere.
    if (window._highlightMarker) window._highlightMarker(_activeListingId);
}

function setActiveListing(id) {
    _activeListingId = id;
    applyActiveHighlight();
}
window.setActiveListing = setActiveListing;

function clearActiveListing() {
    _activeListingId = null;
    applyActiveHighlight();
}
window.clearActiveListing = clearActiveListing;

// #main-content gets swapped wholesale on every filter/edit refresh, which
// would otherwise silently drop the ring from a freshly re-rendered gallery
// card even though its listing is still the one open in the drawer.
document.addEventListener("htmx:afterSettle", (e) => {
    if (e.detail.target && e.detail.target.id === "main-content") {
        applyActiveHighlight();
        initSettingsPickMap();  // forms.js
        // /ustawienia has no per-listing content (no sidebar, no map/gallery
        // markers to reopen against) - a drawer left open from whatever view
        // the user navigated from no longer refers to anything on screen.
        const path = e.detail.pathInfo && e.detail.pathInfo.requestPath;
        if (path && path.startsWith("/ustawienia") && Alpine.store("ui").drawerOpen) {
            Alpine.store("ui").drawerOpen = false;
            clearActiveListing();
        }
    }
});
