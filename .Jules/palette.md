## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.
