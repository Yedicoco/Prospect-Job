## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-10-26 - Modal Dialog Accessible Name & Focus Restoration
**Learning:** Native `<dialog>` elements in single-page apps often lack an accessible title linkage, causing screen readers to announce the dialog without context. Furthermore, closing the dialog can leave keyboard focus stranded or reset to the `<body>`, disorienting keyboard and screen reader users.
**Action:** Pair `<dialog aria-labelledby="modal-title">` with an `<h2 id="modal-title">` inside modal templates, capture `document.activeElement` when triggering the modal, and restore focus to the triggering element upon dialog dismissal.
