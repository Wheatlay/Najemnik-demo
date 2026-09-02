/* Editor for the six money fields (kaucja, parking, piwnica, notariusz,
   prowizja, OC). See core/domain/money_field.py for what's stored.

   A cycling status pill (tak/nie/brak informacji), plus kwota (numbers
   only, unrolls open only for "tak") and notatka (free prose, always
   available - "Brak, ale zapytać ponownie" is legitimate) as separate
   boxes. The save re-renders the drawer server-side, which destroys this
   component and rebuilds it from stored state - so what you see after
   saving is what the database actually holds, never an optimistic guess.

   Chosen after trying four other shapes on real data (a free-text single
   box, click-to-edit-then-select, a merged pill, others) - see git history
   on the money-fields branch for what didn't work and why. */
function moneyField(cfg) {
    const ORDER = ["tak", "nie", "brak_informacji"];
    return {
        status: cfg.status,
        amount: cfg.amount,
        note: cfg.note,
        // Whether the kwota wrapper should stop clipping. Only true once its
        // width transition has genuinely finished landing on "tak" - while
        // sliding (either direction) it must keep clipping, or the input
        // (and its focus ring) would burst out past the still-growing box.
        //
        // A static "only clip on the x-axis" CSS rule can't do this: per
        // spec, setting overflow-x to anything but visible forces the
        // browser to silently recompute overflow-y as auto too (verified -
        // an element with only overflow-x:hidden set reports
        // getComputedStyle().overflowY === "auto"), and auto clips a
        // box-shadow exactly like hidden does. So the ring's top/bottom
        // stayed clipped even after switching to overflow-x-hidden - there
        // is no CSS-only way to clip one axis and not the other for
        // something that isn't scrollable content. Toggling the clip
        // entirely, in step with the transition actually finishing, is the
        // one thing that works.
        revealed: cfg.status === "tak",

        /* "tak" means "you're on the hook" for an obligation field (kaucja,
           prowizja...) but "you have one" for an amenity field (parking,
           piwnica) - cfg.trueBucket (from FieldDef.bool_colors, the exact
           tuple select_bool fields already use for the same purpose) says
           which. Kept as a getter rather than stored state so it can never
           drift out of sync with `status`. */
        get pillBucket() {
            if (this.status === "brak_informacji") return "unknown";
            const isTak = this.status === "tak";
            const trueBucket = cfg.trueBucket || "pay";
            const falseBucket = trueBucket === "free" ? "pay" : "free";
            return isTak ? trueBucket : falseBucket;
        },

        setStatus(next) {
            this.status = next;
            if (next !== "tak") this.amount = "";
            // note is deliberately untouched - "Brak, ale zapytać ponownie"
            // is a legitimate thing to want regardless of status.
            this.revealed = false;  // clip immediately - a new slide just started
            //
            // save() re-renders the whole panel, and a local round trip
            // usually beats the kwota box's 200ms slide - the DOM gets
            // replaced by an already-settled copy before the CSS transition
            // has drawn more than a frame or two, which reads as "no
            // animation". Waiting matches the slide's own duration so the
            // reactive width change gets to actually play first.
            setTimeout(() => this.save(), 220);
        },

        /* Bound to @transitionend on the kwota wrapper, filtered to the
           width property so a color/other transition on the same element
           doesn't fire this early. Only stop clipping if the field that
           just finished sliding is still the one we expect - re-clicking
           mid-transition fires a new transitionend for the OLD animation
           after status has already moved on, and revealing then would be
           wrong. */
        onSlideSettled(propertyName) {
            if (propertyName === "width") this.revealed = this.status === "tak";
        },

        cycle() {
            this.setStatus(ORDER[(ORDER.indexOf(this.status) + 1) % ORDER.length]);
        },

        save() {
            htmx.ajax("PATCH", cfg.url, {
                source: this.$el,   // inherits base.html's hx-headers (CSRF)
                target: cfg.target,
                swap: cfg.swap,
                values: {
                    key: cfg.key,
                    render: cfg.render,
                    status: this.status,
                    amount: this.status === "tak" ? this.amount : "",
                    note: this.note,
                },
            });
        },
    };
}
