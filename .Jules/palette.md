## 2026-10-25 - Search and filter ARIA labels & Live Toast Regions
**Learning:** Adding explicit `aria-label` attributes to unlabeled search inputs and dropdown filters significantly improves accessibility for assistive technologies without altering visual layout. Additionally, adding `aria-live="polite"` and `aria-atomic="true"` to dynamic toast containers ensures screen readers announce status notifications immediately.
**Action:** Always verify that input fields and dropdown filters have descriptive ARIA labels, and ensure notification popups are decorated with ARIA live region attributes.

## 2026-10-28 - Required Field Visual Indicators & Async Form Submission Feedback
**Learning:** Combining native HTML `required` attributes with visual asterisks (`<span class="req" aria-hidden="true">*</span>`) prevents screen readers from redundantly announcing "asterisk" while giving sighted users immediate visual feedback. Additionally, updating submit button text to "Transmission en cours…" during async form submission prevents double submissions and gives immediate feedback.
**Action:** Use `aria-hidden="true"` on visual form field indicators and update submit button text and disabled state during async operations.
