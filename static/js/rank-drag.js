/* Drag-and-drop rank reordering for gallery cards and compare rows.
   Self-contained - talks to the server directly via POST /listings/{id}/rank
   and then re-submits the filter form to re-render the view. */

// wireRankDrag() below re-runs on every htmx:afterSettle, including swaps
// that never touch #main-content at all (e.g. just opening the drawer) -
// without a per-item bound guard, each such call re-registers a fresh set of
// drag/dragover/drop listeners on the *same*, unchanged elements, so a single
// drop later fires one rank POST per registration that piled up. dragId is
// shared at module scope (only one drag can be in progress at a time) rather
// than re-created per call, so a drag started before a re-wire still resolves
// correctly against items (re)bound after it.
let _dragId = null;
function enableRankDrag(container, itemSelector, idAttr) {
    if (!container) return;
    container.querySelectorAll(itemSelector).forEach((el) => {
        if (el.dataset.rankDragBound) return;
        el.dataset.rankDragBound = "true";
        el.setAttribute("draggable", "true");
        el.addEventListener("dragstart", () => { _dragId = el.getAttribute(idAttr); });
        el.addEventListener("dragover", (e) => e.preventDefault());
        el.addEventListener("drop", (e) => {
            e.preventDefault();
            const targetId = el.getAttribute(idAttr);
            if (!_dragId || _dragId === targetId) return;
            const items = Array.from(container.querySelectorAll(itemSelector));
            const targetIndex = items.findIndex((i) => i.getAttribute(idAttr) === targetId);
            fetch(`/listings/${_dragId}/rank`, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: `value=${targetIndex + 1}&render=drawer`,
            }).then(() => htmx.trigger("#filter-form", "submit"));
        });
    });
}
window.enableRankDrag = enableRankDrag;

function wireRankDrag() {
    enableRankDrag(document.querySelector("#main-content"), "[data-listing-id]", "data-listing-id");
}
document.addEventListener("htmx:afterSettle", wireRankDrag);
document.addEventListener("DOMContentLoaded", wireRankDrag);
