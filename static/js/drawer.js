/* The detail drawer: opening it, keeping the view behind it in sync, and the
   small single-marker map embedded inside it. Depends on core.js
   (setActiveListing, brandColor). */

function openDrawer(listingId) {
    setActiveListing(listingId);
    htmx.ajax("GET", `/listings/${listingId}/drawer`, { target: "#drawer-body", swap: "innerHTML" })
        .then(() => { Alpine.store("ui").drawerOpen = true; });
}
window.openDrawer = openDrawer;

// Any edit made *inside* the drawer (field patch, rank, status pill, star
// rating, tag suggestion) re-renders the drawer itself via its own response,
// but the gallery card / compare row / map
// marker sitting behind it in #main-content is a separate DOM subtree that
// never gets touched - so it silently goes stale until a manual reload.
// Refresh the whole list/table/map behind the drawer after any such edit,
// the same way the "delete" and "ingest finished" flows already do.
document.addEventListener("htmx:afterRequest", (e) => {
    const target = e.detail.target;
    if (!target || target.id !== "drawer-body" || !e.detail.successful) return;
    const path = e.detail.pathInfo && e.detail.pathInfo.requestPath;
    if (!path || path.endsWith("/drawer")) return; // just opening it - nothing changed yet
    const form = document.getElementById("filter-form");
    if (form) {
        htmx.trigger(form, "submit");
    } else {
        // /panel has no filter sidebar/form (its lists aren't filterable), so
        // there's nothing to re-submit - refetch the current URL straight
        // into #main-content instead, the same target the form would use.
        htmx.ajax("GET", window.location.pathname + window.location.search, { target: "#main-content", swap: "innerHTML transition:true" });
    }
});

// A field edit re-renders the *entire* #drawer-body from scratch (see
// above), which replaces the scrollable #drawer-panel's content wholesale -
// without this, editing anything scrolls the drawer back to the top (or,
// once autosize recalculates textarea heights below the fold, effectively
// "jumps" further down than where you were). Opening the drawer fresh
// should still start at the top, so this only kicks in for edits, not the
// initial GET .../drawer load.
let _drawerScrollTop = null;
document.addEventListener("htmx:beforeSwap", (e) => {
    if (!e.detail.target || e.detail.target.id !== "drawer-body") return;
    const path = e.detail.pathInfo && e.detail.pathInfo.requestPath;
    const panel = document.getElementById("drawer-panel");
    _drawerScrollTop = (panel && path && !path.endsWith("/drawer")) ? panel.scrollTop : null;
});
document.addEventListener("htmx:afterSettle", (e) => {
    if (!e.detail.target || e.detail.target.id !== "drawer-body" || _drawerScrollTop === null) return;
    const panel = document.getElementById("drawer-panel");
    if (panel) panel.scrollTop = _drawerScrollTop;
    _drawerScrollTop = null;
});

// The mini-map div is hx-preserve'd (see initMiniMap below) so re-rendering
// the *same* listing's drawer keeps its live map instance instead of
// rebuilding it. But switching to a *different* listing swaps in a
// differently-id'd container, and the old one (along with its WebGL canvas)
// is simply dropped from the DOM rather than preserved - without this sweep
// its maplibregl.Map instance would leak (browsers cap concurrent WebGL
// contexts at ~16, so a handful of drawer visits would start breaking maps).
document.addEventListener("htmx:afterSettle", (e) => {
    if (!e.detail.target || e.detail.target.id !== "drawer-body") return;
    Object.keys(_miniMaps).forEach((id) => {
        if (!document.getElementById(id)) {
            _miniMaps[id].map.remove();
            delete _miniMaps[id];
        }
    });
});

// --- Mini-map (single marker, embedded in the drawer) ---
// Shows a listing's location without leaving the current page/view. Its
// container is hx-preserve'd (detail_drawer.html) for the *same* listing
// across drawer re-renders, so a field edit that doesn't touch lat/lon/status
// can skip touching the map entirely instead of tearing down and reloading
// tiles - that rebuild-on-every-edit is what used to flash the mini-map on
// something as unrelated as a phone number change.
let _miniMaps = {};

function _miniMapMarkerEl(color) {
    const dot = document.createElement("div");
    dot.style.width = "16px";
    dot.style.height = "16px";
    dot.style.borderRadius = "50%";
    dot.style.border = "2px solid white";
    dot.style.boxShadow = "0 1px 3px rgba(0,0,0,.4)";
    dot.style.background = brandColor(color, "#8b5cf6");
    return dot;
}

function initMiniMap(containerId, lat, lon, color) {
    const existing = _miniMaps[containerId];
    const el = document.getElementById(containerId);
    if (existing && el && el.isConnected) {
        if (existing.lat === lat && existing.lon === lon && existing.color === color) {
            return; // nothing this map cares about actually changed
        }
        if (existing.lat === lat && existing.lon === lon) {
            // Only the status (marker color) changed - swap the marker, leave
            // the map/canvas/tiles untouched.
            existing.marker.remove();
            existing.marker = new maplibregl.Marker({ element: _miniMapMarkerEl(color) })
                .setLngLat([lon, lat]).addTo(existing.map);
            existing.color = color;
            return;
        }
        // Coordinates actually changed (pin dragged elsewhere) - fall through
        // to a full rebuild, same as when there's no live instance yet.
        existing.map.remove();
        delete _miniMaps[containerId];
    } else if (existing) {
        existing.map.remove();
        delete _miniMaps[containerId];
    }
    if (!el || !window.maplibregl) return;
    const map = new maplibregl.Map({
        container: containerId,
        style: "https://tiles.openfreemap.org/styles/liberty",
        center: [lon, lat],
        zoom: 14,
        attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    const marker = new maplibregl.Marker({ element: _miniMapMarkerEl(color) })
        .setLngLat([lon, lat]).addTo(map);
    _miniMaps[containerId] = { map, marker, lat, lon, color };
}
window.initMiniMap = initMiniMap;
