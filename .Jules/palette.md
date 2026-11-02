## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-11-02 - Accessible Dialog Backdrop Dismissal & Heading Association
**Learning:** HTML5 `<dialog>` elements need `aria-labelledby` linking directly to their modal heading ID so screen readers announce the context upon opening. Adding backdrop click-to-close behavior (`e.target === dialog`) provides a natural and expected dismissal method, paired with clear `:focus-visible` styling on the close button for keyboard accessibility.
**Action:** Ensure all dynamically populated modal dialogs bind `aria-labelledby` to their title element and support backdrop click dismissal alongside keyboard shortcuts.
