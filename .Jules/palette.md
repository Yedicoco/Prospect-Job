## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-11-01 - Dynamic Navigation Landmarks & Accessible Modal Dialogs
**Learning:** In SPAs where navigation tabs are dynamically rendered buttons rather than static anchor links, screen readers cannot determine current page location unless `aria-current="page"` is explicitly set and decorative icon glyphs are suppressed with `aria-hidden="true"`. Furthermore, modal `<dialog>` elements require `aria-modal="true"` and `aria-labelledby` referencing the dynamic header `<h2>` to guarantee assistive devices properly announce the dialog and trap context.
**Action:** Always pair dynamic navigation items with `aria-current="page"`, hide cosmetic icons with `aria-hidden="true"`, and label modal `<dialog>` containers using `aria-labelledby` linked to the heading.
