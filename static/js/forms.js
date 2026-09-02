/* Form-input behaviours that aren't specific to any one view: the
   /ustawienia location picker and textarea auto-height. Depends on core.js
   (brandColor). */

// --- /ustawienia: click-to-place a commute reference point ---
// No geocoding in this app, so a name + a map click is the whole "address
// entry" flow - the click just fills the hidden lat/lon inputs the add-point
// form already has.
let _settingsPickMap = null;
function initSettingsPickMap() {
    const el = document.getElementById("settings-pick-map");
    if (!el || !window.maplibregl) return;
    if (_settingsPickMap) { _settingsPickMap.remove(); _settingsPickMap = null; }
    const map = new maplibregl.Map({
        container: "settings-pick-map",
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [19.0, 50.26],
        zoom: 11,
    });
    map.addControl(new maplibregl.NavigationControl());
    _settingsPickMap = map;
    let marker = null;
    map.on("click", (e) => {
        const { lat, lng } = e.lngLat;
        document.getElementById("commute-point-lat").value = lat;
        document.getElementById("commute-point-lon").value = lng;
        document.getElementById("commute-point-submit").disabled = false;
        if (marker) marker.remove();
        marker = new maplibregl.Marker({ color: brandColor("--color-accent-600", "#7c3aed") }).setLngLat([lng, lat]).addTo(map);
    });
}
window.initSettingsPickMap = initSettingsPickMap;
document.addEventListener("DOMContentLoaded", initSettingsPickMap);

// --- Textarea auto-height (fees_note / smart-field notes / any long text field) ---
// Server-rendered content and htmx swaps both need this re-applied, since a
// textarea's scrollHeight is only knowable once its content is in the DOM.
function autosizeTextarea(el) {
    // offsetParent is null for anything inside a display:none subtree (the
    // drawer's collapsed sections, the compare table's hidden columns).
    // Measuring there yields scrollHeight 0 and would pin the element at
    // 0px, which is what made every smart field in a collapsed section
    // render as a 10px sliver once sections started collapsed by default.
    if (el.offsetParent === null) return;
    el.style.height = "auto";
    // scrollHeight excludes border, but box-sizing is border-box here, so
    // assigning it straight to style.height leaves the box one border-width
    // short of its own content - invisible where .autosize also has
    // overflow:hidden (the drawer), but a permanent 1-2px scrollbar with
    // visible up/down arrows anywhere overflow-y is auto (the compare table).
    const borderHeight = el.offsetHeight - el.clientHeight;
    el.style.height = (el.scrollHeight + borderHeight) + "px";
}
function autosizeAllTextareas(root) {
    (root || document).querySelectorAll("textarea.autosize").forEach((el) => {
        autosizeTextarea(el);
        if (!el.dataset.autosizeBound) {
            el.dataset.autosizeBound = "true";
            el.addEventListener("input", () => autosizeTextarea(el));
        }
    });
}
window.autosizeAllTextareas = autosizeAllTextareas;
document.addEventListener("DOMContentLoaded", () => autosizeAllTextareas());
document.addEventListener("htmx:afterSettle", (e) => autosizeAllTextareas(e.target));
