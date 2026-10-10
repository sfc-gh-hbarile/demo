---
name: fpa-variance-review
description: Repeatable FP&A variance review for plan vs actual vs forecast. Use when asked why a margin, revenue, or cost line is off plan, what changed in the forecast, or to draft management commentary. Triggers - variance, below plan, forecast change, margin, management commentary, review package.
---

# FP&A Variance Review

## Instructions

### Method
1. Confirm scope: region, product, period (closed months Jan-Sep 2026 vs open forecast months Oct-Dec 2026), and which forecast version (current FY26_SEP, prior FY26_AUG).
2. Quantify the headline variance with the fpa_analyst tool: actual vs plan in dollars and in margin points.
3. Decompose the variance by product with fpa_analyst (avg_price, total_units, avg_unit_cost, actual and plan):
   - Price effect = (actual price - plan price) x actual units
   - Volume effect = (actual units - plan units) x plan price
   - Unit cost effect = (actual unit cost - plan unit cost) x actual units
   Report the top two drivers by size, by product.
4. Find the business reason in the forecast_note (fpa_analyst) and planning documents (fpa_search). Do not invent reasons; if no source supports a reason, say so.
5. State the outlook: how the current forecast FY26_SEP treats the driver for Q4 2026.
6. Recommend actions and name the owner role.

### Output template
- Headline (one sentence with the number)
- Drivers (table: driver, amount, source)
- Outlook
- Recommended actions
- Status: DRAFT, pending FP&A approval

### Guardrails
- Name the tool used for every number.
- Scenario what-ifs use the run_scenario tool, never ad hoc math.
- Never send or publish a review package without explicit human approval; submit_review_package only creates a PENDING_APPROVAL package.
- State assumptions and data period on every output.
