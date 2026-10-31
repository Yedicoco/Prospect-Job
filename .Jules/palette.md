## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-10-31 - Accessible Modal Dialog Labelling & Focus Restoration
**Learning:** Native `<dialog>` elements require explicit labeling (`aria-labelledby` linking to the header title ID) and `aria-modal="true"` to ensure screen readers announce the modal context immediately upon display. Furthermore, capturing the trigger element before opening the dialog and restoring keyboard focus upon closing prevents focus loss back to the body document root, which disrupts screen reader and keyboard user workflows.
**Action:** Always ensure modal headers have an ID tied to the `<dialog>` container via `aria-labelledby`, and restore focus to the opening element when the modal is dismissed.
