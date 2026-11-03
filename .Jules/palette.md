## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-11-04 - Modal Dialog Accessible Name & Backdrop Dismissal
**Learning:** Native `<dialog>` elements need an accessible name referencing their header via `aria-labelledby="modal-title"` so screen reader users immediately know what modal opened. Additionally, delegating click-outside backdrop dismissal on `<dialog>` provides standard intuitive dismissal for mouse and touch users alongside the close button.
**Action:** Always link dialog containers to their dynamic `<h2>` heading using `aria-labelledby` and bind backdrop click dismissal on dialog elements.
