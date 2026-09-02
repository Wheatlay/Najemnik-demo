/* /mapa only: the clustered MapLibre view, its markers, hover popups and the
   mode/basemap/move-pin controls. initMap() is called from map.html once the
   listings JSON is inline. Depends on core.js (brandColor, _activeListingId)
   and drawer.js (openDrawer). */

// Re-runs every time the filter sidebar (or a drawer edit's background
// refresh) swaps #main-content on /mapa. #map is hx-preserve'd, so most of
// the time the previous MapLibre instance is still attached to the live DOM
// and initMap() just feeds it fresh data/markers in place (see the
// getContainer().isConnected branch below) - no teardown, no tile reload, no
// flash. The full teardown-and-rebuild path only runs when there wasn't a
// live map to update (first load on /mapa, or navigating in from a page
// that had no #map at all).
let _currentMap = null;
// _lastView only still matters for that full-rebuild path (e.g. arriving on
// /mapa fresh) - the in-place update path above never touches pan/zoom at
// all, which is strictly better than restoring an approximate saved view.
let _lastView = null;
// Survive re-inits the same way _lastView does, so switching filters or
// editing a listing from the drawer doesn't silently reset the user's chosen
// display mode / basemap back to the defaults.
let _currentDisplayMode = "price";
let _currentBasemapStyle = "liberty";
// Markers are non-draggable by default - an accidental drag used to
// silently overwrite lat/lon (POST /position) with no confirmation and no
// undo. Dragging must be explicitly turned on via the "przesuń pinezkę"
// toggle; persists across re-inits the same way display mode / basemap do.
let _movePinMode = false;

const MAP_STYLES = {
    liberty: "https://tiles.openfreemap.org/styles/liberty",
    bright: "https://tiles.openfreemap.org/styles/bright",
    positron: "https://tiles.openfreemap.org/styles/positron",
};

// Each non-status display mode pairs the raw cost field with its
// cheap/typical/expensive marker color and the cluster-aggregate property
// names computed once in the "listings" source's clusterProperties.
const DISPLAY_MODES = {
    price: { valueKey: "suma", colorKey: "price_color", minProp: "min_suma", maxProp: "max_suma", unitLabel: "/ mies." },
    wejscie: { valueKey: "wejscie", colorKey: "wejscie_color", minProp: "min_wejscie", maxProp: "max_wejscie", unitLabel: "/ wejście" },
    rok: { valueKey: "rok", colorKey: "rok_color", minProp: "min_rok", maxProp: "max_rok", unitLabel: "/ rok" },
};

function formatCompactZl(v) {
    if (v >= 1000) {
        return (v / 1000).toFixed(1) + "k zł";
    }
    return v + " zł";
}

function escapeHtml(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

// Applies the current display mode's look to a marker's DOM element -
// bubble+color for the mode's cost field when the listing has that data,
// otherwise the same plain status-colored dot used in "Status" mode.
// MapLibre's Marker uses the element passed to it directly as its root -
// it doesn't wrap it - and once added to the map it owns that element's
// "maplibregl-marker"/"maplibregl-marker-anchor-center" classes and
// position/transform inline styles for placement. So restyling on a mode
// switch must only touch the specific class/properties this function owns
// (classList.toggle, not className=; style.removeProperty, not
// removeAttribute("style")) or it wipes the marker off its coordinates.
const _MARKER_DOT_PROPS = ["width", "height", "border-radius", "border", "box-shadow", "background"];

function styleMarkerEl(el, l, mode, statusColors) {
    el.textContent = "";
    _MARKER_DOT_PROPS.forEach((p) => el.style.removeProperty(p));
    el.style.removeProperty("--mc");
    const cfg = mode === "status" ? null : DISPLAY_MODES[mode];
    const value = cfg ? l[cfg.valueKey] : null;
    el.classList.toggle("map-price-marker", !!(cfg && value));
    // Plain status dots are 14px, well under a comfortable touch target -
    // map-status-marker adds a CSS ::before hit-area (input.css) rather than
    // enlarging the dot itself: el is MapLibre's own positioned root (see the
    // ownership note above this function), so growing el's real box would
    // require touching properties MapLibre manages, but a pseudo-element
    // only needs el to already be a positioned ancestor, which it is.
    el.classList.toggle("map-status-marker", !(cfg && value));
    if (cfg && value) {
        el.style.setProperty("--mc", brandColor(l[cfg.colorKey], "#71717a"));
        el.textContent = formatCompactZl(value);
    } else {
        el.style.width = "14px";
        el.style.height = "14px";
        el.style.borderRadius = "50%";
        el.style.border = "2px solid white";
        el.style.boxShadow = "0 1px 3px rgba(0,0,0,.4)";
        el.style.background = brandColor(statusColors[l.status], "#71717a");
    }
    el.style.cursor = "pointer";
}

// #map is hx-preserve'd (map_content.html) so a background refresh after a
// drawer edit (or a filter change) keeps the same live MapLibre instance
// instead of tearing it down and reloading tiles from scratch - that
// teardown/rebuild used to be *every* refresh's default path and is what
// caused the visible white flash on any field edit, even ones that don't
// touch location/status at all. State that used to live in initMap()'s own
// closure (hover popup, marker records, current status palette) is promoted
// to module scope so the update path below can reuse it across calls.
let _markerRecords = [];
let _hoverPopup = null;
let _statusColors = {};
let _statusOrder = [];

function buildListingsGeoJSON(withCoords) {
    return {
        type: "FeatureCollection",
        features: withCoords.map((l) => ({
            type: "Feature",
            geometry: { type: "Point", coordinates: [l.lon, l.lat] },
            properties: {
                id: l.id, status: l.status,
                suma: l.suma ?? null, wejscie: l.wejscie ?? null, rok: l.rok ?? null,
            },
        })),
    };
}

// Re-adds the "listings" source and its cluster layers - needed on initial
// load AND after every basemap-style switch, since setStyle() wipes any
// source/layers that aren't part of the new style. The DOM markers are
// untouched by style swaps, so they're never rebuilt here.
function addClusterLayers(map, withCoords) {
    const clusterProperties = {};
    for (const cfg of Object.values(DISPLAY_MODES)) {
        // Listings without that cost field are coalesced to a value that can
        // never win their respective aggregate, so they don't drag min to 0
        // or corrupt max - a cluster where every member lacks the data ends
        // up with min > max, which the hover handler treats as "no price
        // data" for the group.
        clusterProperties[cfg.minProp] = ["min", ["coalesce", ["get", cfg.valueKey], 999999999]];
        clusterProperties[cfg.maxProp] = ["max", ["coalesce", ["get", cfg.valueKey], 0]];
    }
    map.addSource("listings", {
        type: "geojson",
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 40,
        clusterProperties,
        data: buildListingsGeoJSON(withCoords),
    });

    map.addLayer({
        id: "clusters", type: "circle", source: "listings",
        filter: ["has", "point_count"],
        paint: {
            "circle-color": brandColor("--color-accent-500", "#8b5cf6"),
            "circle-radius": ["step", ["get", "point_count"], 16, 5, 22, 15, 28],
            "circle-opacity": 0.85,
        },
    });
    map.addLayer({
        id: "cluster-count", type: "symbol", source: "listings",
        filter: ["has", "point_count"],
        layout: { "text-field": "{point_count_abbreviated}", "text-size": 12 },
        paint: { "text-color": "#fff" },
    });
}

// One DOM Marker per listing, independent of clustering/style - kept in a
// flat list so the display-mode switch can restyle them in place without
// touching the map's sources/layers. Shared by the initial build and the
// no-rebuild update path, since either way the previous batch of markers
// needs replacing with one bound to the freshly fetched listings.
function buildMarkerRecords(map, withCoords, hoverPopup) {
    return withCoords.map((l) => {
        const el = document.createElement("div");
        styleMarkerEl(el, l, _currentDisplayMode, _statusColors);

        const marker = new maplibregl.Marker({ element: el, draggable: _movePinMode })
            .setLngLat([l.lon, l.lat])
            .addTo(map);

        // Only reachable when "przesuń pinezkę" mode is on (marker.draggable
        // is false otherwise, per _movePinMode above) - the server treats
        // reaching this endpoint at all as the user having just confirmed
        // the pin against the real address (see /position's pewnosc_lokalizacji).
        marker.on("dragend", () => {
            const pos = marker.getLngLat();
            // Keep the in-memory listing in sync with where the pin now sits -
            // the hover popup and the click-to-center both read l.lat/l.lon, so
            // without this they'd keep pointing at the pre-drag location until a
            // full refresh (the marker itself is moved by MapLibre already).
            l.lat = pos.lat;
            l.lon = pos.lng;
            fetch(`/listings/${l.id}/position`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: `lat=${pos.lat}&lon=${pos.lng}`,
            });
        });
        el.addEventListener("click", (e) => {
            e.stopPropagation();
            hoverPopup.remove();
            // The drawer resizes the map's own flex container rather than
            // overlaying it (base.html), so MapLibre's ResizeObserver shrinks
            // the visible map area itself once the drawer's width transition
            // finishes - no artificial centering offset needed, just center
            // once the container has actually reached its final size.
            // Already-open drawer -> no width change is coming (just
            // swapping which listing #drawer-body shows), so center now.
            if (Alpine.store("ui").drawerOpen) {
                map.easeTo({ center: [l.lon, l.lat], duration: 400 });
            } else {
                const panel = document.getElementById("drawer-panel");
                const onTransitionEnd = (ev) => {
                    if (ev.propertyName !== "width") return;
                    panel.removeEventListener("transitionend", onTransitionEnd);
                    map.easeTo({ center: [l.lon, l.lat], duration: 250 });
                };
                if (panel) panel.addEventListener("transitionend", onTransitionEnd);
            }
            openDrawer(l.id);
        });
        el.addEventListener("mouseenter", () => {
            const meta = [l.rooms ? `${l.rooms} pok.` : "", l.area_m2 ? `${l.area_m2} m²` : "", l.district || ""]
                .filter(Boolean).join(" • ");
            const costLines = [
                l.suma ? `mies.: ${formatCompactZl(l.suma)}` : "",
                l.wejscie ? `wejście: ${formatCompactZl(l.wejscie)}` : "",
                l.rok ? `rok: ${formatCompactZl(l.rok)}` : "",
            ].filter(Boolean).map((line) => `<div class="map-hover-price">${line}</div>`).join("");
            hoverPopup.setLngLat([l.lon, l.lat])
                .setHTML(
                    `<div class="map-hover-popup">` +
                    (l.photo ? `<img class="map-hover-thumb" src="${escapeHtml(l.photo)}" alt="">` : "") +
                    `<div class="map-hover-body">` +
                    `<div class="map-hover-title">${escapeHtml(l.title || "Bez nazwy")}</div>` +
                    (meta ? `<div class="map-hover-meta">${escapeHtml(meta)}</div>` : "") +
                    costLines +
                    `</div></div>`
                )
                .addTo(map);
        });
        el.addEventListener("mouseleave", () => hoverPopup.remove());
        return { el, listing: l, marker };
    });
}

// Not rebound per initMap() call - reads _markerRecords fresh each time it
// runs, so it stays correct whether the last call took the full-build or
// the in-place update path.
function highlightMarker(id) {
    _markerRecords.forEach((r) => {
        r.el.classList.toggle("marker-active", r.listing.id === id);
    });
}
window._highlightMarker = highlightMarker;

// Only visible in "status" mode, since that's the one mode where the marker
// color isn't self-explanatory (a price bubble states its own number; a
// status dot's color needs a key to read).
function renderStatusLegend() {
    const legendEl = document.getElementById("map-status-legend");
    if (!legendEl) return;
    if (_currentDisplayMode !== "status") {
        legendEl.classList.add("hidden");
        return;
    }
    legendEl.classList.remove("hidden");
    legendEl.innerHTML = _statusOrder.map((status) => (
        `<div class="map-status-legend-item"><span class="map-status-legend-dot" style="background:${brandColor(_statusColors[status], "#71717a")}"></span>${escapeHtml(status)}</div>`
    )).join("");
}

// --- Reference points ("Praca", "Szkoła"…) from /ustawienia ---
// Drawn deliberately unlike a listing: a labelled teal pill rather than a
// price bubble or status dot, so it can't be mistaken for somewhere you
// could rent. They're not clickable and never enter _markerRecords, which
// means the display-mode switch, the highlight and the drag-to-move-pin
// toggle all ignore them - none of those concepts apply to a fixed place.
let _commuteMarkers = [];

function renderCommutePoints(map, points) {
    _commuteMarkers.forEach((m) => m.remove());
    _commuteMarkers = (points || []).map((p) => {
        const el = document.createElement("div");
        el.className = "map-commute-marker";
        el.textContent = p.name || "Punkt";
        el.title = `${p.name || "Punkt"} - Twój punkt odniesienia (Ustawienia)`;
        return new maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(map);
    });
}

function initMap(listings, statusColors, focusId, statusOrder, commutePoints) {
    _statusColors = statusColors;
    _statusOrder = statusOrder;
    const withCoords = listings.filter((l) => l.lat && l.lon);
    const focusPoint = focusId ? withCoords.find((l) => l.id === focusId) : null;

    // #map is hx-preserve'd, so a live map survives the swap that triggered
    // this call - update its data/markers in place instead of tearing down
    // and rebuilding the whole MapLibre instance (which reloads tiles and
    // flashes white). getContainer().isConnected is false when the previous
    // page didn't have a #map at all (e.g. navigated in from /galeria), which
    // falls through to the full-build path below same as a first load.
    if (_currentMap && _currentMap.getContainer().isConnected) {
        const map = _currentMap;
        const source = map.getSource("listings");
        if (source) source.setData(buildListingsGeoJSON(withCoords));
        _markerRecords.forEach((r) => r.marker.remove());
        _markerRecords = buildMarkerRecords(map, withCoords, _hoverPopup);
        renderCommutePoints(map, commutePoints);
        highlightMarker(_activeListingId);
        renderStatusLegend();
        if (focusPoint) {
            map.easeTo({ center: [focusPoint.lon, focusPoint.lat], zoom: 15 });
            if (window.openDrawer) openDrawer(focusPoint.id);
        }
        return;
    }

    if (_currentMap) {
        _lastView = { center: _currentMap.getCenter().toArray(), zoom: _currentMap.getZoom() };
        _currentMap.remove();
        _currentMap = null;
    }
    const initialCenter = focusPoint ? [focusPoint.lon, focusPoint.lat]
        : _lastView ? _lastView.center
        : withCoords.length ? [withCoords[0].lon, withCoords[0].lat] : [19.0, 50.26];
    const initialZoom = focusPoint ? 15 : _lastView ? _lastView.zoom : withCoords.length ? 12 : 10;
    const map = new maplibregl.Map({
        container: "map",
        style: MAP_STYLES[_currentBasemapStyle],
        center: initialCenter,
        zoom: initialZoom,
    });
    map.addControl(new maplibregl.NavigationControl());
    _currentMap = map;

    // Reused for both the individual-marker and cluster hover popups - kept
    // to a single instance so rapid mouse movement across markers doesn't
    // leave duplicate popups behind, and closed on click so it never blocks
    // the click-to-open-drawer / click-to-expand-cluster interactions.
    const hoverPopup = new maplibregl.Popup({
        closeButton: false, closeOnClick: false, offset: 12, className: "map-hover-popup-wrap",
        maxWidth: "400px",
    });
    _hoverPopup = hoverPopup;

    // Cluster click/hover handlers are registered once, outside
    // addClusterLayers(), so repeated basemap switches don't stack
    // duplicate listeners on top of each other.
    map.on("click", "clusters", (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ["clusters"] });
        const clusterId = features[0].properties.cluster_id;
        map.getSource("listings").getClusterExpansionZoom(clusterId, (err, zoom) => {
            if (err) return;
            map.easeTo({ center: features[0].geometry.coordinates, zoom });
        });
    });

    map.on("mouseenter", "clusters", () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mousemove", "clusters", (e) => {
        const p = e.features[0].properties;
        let priceLine = "";
        if (_currentDisplayMode !== "status") {
            const cfg = DISPLAY_MODES[_currentDisplayMode];
            const hasPrice = p[cfg.minProp] <= p[cfg.maxProp];
            priceLine = hasPrice
                ? `<div class="map-hover-price">${formatCompactZl(p[cfg.minProp])} – ${formatCompactZl(p[cfg.maxProp])} ${cfg.unitLabel}</div>`
                : "";
        }
        hoverPopup.setLngLat(e.lngLat)
            .setHTML(`<div class="map-hover-popup"><div class="map-hover-title">${p.point_count} ogłoszeń w tym miejscu</div>${priceLine}<div class="map-hover-meta">Kliknij, aby przybliżyć</div></div>`)
            .addTo(map);
    });
    map.on("mouseleave", "clusters", () => {
        map.getCanvas().style.cursor = "";
        hoverPopup.remove();
    });

    _markerRecords = buildMarkerRecords(map, withCoords, hoverPopup);
    renderCommutePoints(map, commutePoints);
    highlightMarker(_activeListingId);

    map.on("load", () => {
        addClusterLayers(map, withCoords);
        if (focusPoint && window.openDrawer) {
            openDrawer(focusPoint.id);
        }
    });

    renderStatusLegend();

    const modeGroup = document.querySelector('.map-seg-group[data-group="mode"]');
    if (modeGroup) {
        const buttons = modeGroup.querySelectorAll(".map-seg-btn");
        const applyActive = () => buttons.forEach((b) => b.classList.toggle("active", b.dataset.mode === _currentDisplayMode));
        applyActive();
        buttons.forEach((b) => b.addEventListener("click", () => {
            _currentDisplayMode = b.dataset.mode;
            applyActive();
            renderStatusLegend();
            _markerRecords.forEach((r) => styleMarkerEl(r.el, r.listing, _currentDisplayMode, _statusColors));
        }));
    }

    const basemapGroup = document.querySelector('.map-seg-group[data-group="basemap"]');
    if (basemapGroup) {
        const buttons = basemapGroup.querySelectorAll(".map-seg-btn");
        const applyActive = () => buttons.forEach((b) => b.classList.toggle("active", b.dataset.style === _currentBasemapStyle));
        applyActive();
        buttons.forEach((b) => b.addEventListener("click", () => {
            _currentBasemapStyle = b.dataset.style;
            applyActive();
            map.setStyle(MAP_STYLES[_currentBasemapStyle]);
            map.once("styledata", () => addClusterLayers(map, withCoords));
        }));
    }

    const movePinBtn = document.getElementById("map-move-pin-toggle");
    if (movePinBtn) {
        const applyActive = () => {
            movePinBtn.classList.toggle("active", _movePinMode);
            movePinBtn.setAttribute("aria-pressed", String(_movePinMode));
        };
        applyActive();
        movePinBtn.addEventListener("click", () => {
            _movePinMode = !_movePinMode;
            _markerRecords.forEach((r) => r.marker.setDraggable(_movePinMode));
            applyActive();
        });
    }
}
window.initMap = initMap;
