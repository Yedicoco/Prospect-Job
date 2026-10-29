## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-10-29 - Main Navigation Landmark & Active Page ARIA Context
**Learning:** In single-page application sidebars, adding `aria-label` to the `<nav>` landmark and dynamically setting `aria-current="page"` on the active navigation item enables screen readers to announce the current location clearly without affecting visual layout or behavior.
**Action:** Ensure `<nav>` elements have descriptive `aria-label` attributes and that active navigation buttons explicitly apply `aria-current="page"`.
