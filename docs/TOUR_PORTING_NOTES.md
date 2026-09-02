# Tutorial changes to port to the full product

This is a functional change log for the guided tour work done in the portfolio
demo. It separates reusable behaviour from demo-specific copy.

## Reusable behaviour

1. **First-visit welcome** — opening `/galeria` starts a welcome card once per
   browser. A `localStorage` marker prevents repeated interruption.
2. **Two routes** — the welcome offers `Szybki przegląd` and `Pełny samouczek`.
   The short route covers the cost, one listing, a status change, and comparison;
   the long route retains the complete guided flow.
3. **Persisted route and step** — tour state in `sessionStorage` includes the
   selected route and current index, so it survives normal navigation.
4. **Pause, not abandon** — the close button saves the unfinished step. The
   top-bar 🎓 control becomes a slow purple-to-black pulse only in this paused
   state and resumes the exact route and step.
5. **Explicit restart** — the normal 🎓 control starts at the route chooser;
   completing a tour clears its paused state.
6. **Safer target handling** — the tour waits briefly for a dynamic HTMX target,
   falls back to an advanceable centred card, and repositions after swaps.
7. **Drawer safeguards** — only the group/toggle requested by the active step is
   clickable, preventing accidental desynchronization of a long tour.

## Content and UI changes

- Rewrote the long-tour Polish copy to be shorter and less product-marketing
  styled. Treat this as draft copy; keep the interaction structure in the full
  product, but review the wording against real product language.
- Corrected the fixture-specific opening-card selector from `demo-2` to
  `listing-2`.
- Added a quick comparison route for recruiters who do not need the full flow.
- Updated the call/viewing question bank to use practical renter language.
- Removed explanatory text below the scheduled-viewing date that repeated what
  the surrounding UI already communicates.
- Fixed the right edge of the inline `notatka` input: its parent and input now
  have matching width, so the input border is not clipped.

## Demo-specific: do not copy blindly

- Synthetic-listing wording, the saved-model-output notice, and the reset-data
  language.
- Resetting a demo clears `tour:state`, `tour:seen`, and `tour:paused` so the
  welcome returns. In the full product, reset should not usually clear a user's
  onboarding preference.
- The exact `listing-2` selector and synthetic price story.

## Files to compare when porting

- `static/js/tour.js` — engine, state, chooser, pause/resume.
- `static/js/tour-steps.js` — short and long route definitions.
- `templates/base.html` — `#tour-launcher` and the paused-tour animation.
- `templates/_field_macros.html` — inline note width fix.
- `core/pipeline/enrich/callprep_bank.py` — question copy only.
