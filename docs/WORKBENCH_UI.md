# Spectrum workbench

The workbench presents project data on the left, a spectrum and its computed
results in the centre, and the active analysis controls on the right. Organic,
relaxation, processing, assignment and advanced workflows share the same project
and selected spectrum. At narrower widths the inspector moves below the plot;
the workflow strip scrolls without widening the page.

## Spectrum interactions

| Control | Behaviour |
| --- | --- |
| Inspect / V | Read the axis coordinate under the pointer. Chemical shift decreases from left to right; elapsed time increases. |
| Zoom / Z | Drag across an interval to magnify it. Either drag direction works. |
| Pan / H | Drag the visible interval while retaining its width, bounded by the spectrum extent. |
| Back | Return to the preceding view; up to 24 view changes are retained per spectrum. |
| Full view / F | Show the entire spectrum and restore display gain to 1. |
| Gain minus / plus | Change displayed intensity scale only. |
| Visible range | Enter two distinct numeric bounds and apply a view. Bounds are ordered and clipped to the spectrum extent. |
| Integrate / I | In the organic workflow, drag to populate a new integral draft. Review the name and bounds, then choose Save integral. |
| Fit region / I | In relaxation, drag to populate the shared integration bounds. Review the explicit delay mapping and model, then choose Integrate & fit mapped traces. |
| Escape | Cancel an active gesture and return to Inspect. |

Keyboard shortcuts ignore text fields, numeric fields, selects and editable text.
The workflow tabs also support Left/Right and Home/End navigation. Numeric bounds
remain available when pointer gestures are unsuitable.

View changes do not create revisions or modify scientific arrays. Display sampling
retains minimum and maximum values, including narrow negative signals. All
integrals and fits use the full-resolution arrays in the numerical core.

## Drafts, saved results and shared edits

An integral brush populates a draft; it does not immediately change a saved region.
Use a saved region's Edit button to update that region's existing identity.
Integral drafts bind to a spectrum and object version. A source change clears the
visual draft. Relaxation bounds are a reusable recipe shared by the explicitly
mapped traces; selecting a different trace does not infer a new delay mapping.
Numeric edits to either set of bounds update its visual draft. Successful integral
or fit submission clears that draft.

Both forms use the same revision-checked commands as MCP. A stale revision fails
and refreshes the project; the frontend does not replay the rejected write.
Result cards retain their source versions, assumptions, uncertainty method and
current/stale status. Restoring a prior state creates a new revision.

## Design and assets

The [editable Figma design](https://www.figma.com/design/i45KoXbN8h7Bc6uX82vAFX?node-id=2-195)
is a synthetic desktop design reference, built from Simple Design System button,
input and tab instances, product colour variables and editable spectrum vectors.
It establishes the visual hierarchy; the running workbench supplies the complete
forms and scientific evidence tables.

The interaction reference is Mnova's
[practical analysis example](https://www.mestrelabcn.com/Manual_HTML_Mnova_15/practical_example.htm),
particularly region selection, separate analysis controls and reusable settings.
The independent NMR project and open numerical core remain the implementation.
The source includes an original interface and a local Inter font under OFL 1.1;
see [third-party notices](../THIRD_PARTY.md). There are no runtime CDN requests.

## Verified increment — 2026-09-25

- Windows CPython 3.12: 92 Python tests passed, including a real MCP subprocess,
  HTTP shared-state edits, offline asset responses, MIME/CSP and the Host boundary.
- Node: five geometry tests passed for axis direction, bounds, pan limits,
  signed extrema and interpolation across a view narrower than sample spacing.
- Ruff, JavaScript syntax and source/wheel build passed. The built wheel contains
  the view module, Inter WOFF2 font and its full licence.
- Actual in-app browser: drag zoom, pan, Back, Full view, numeric view bounds and
  organic brush/save were exercised. A 1.7–2.3 ppm brush saved the expected
  synthetic area of 0.338395 intensity·ppm in revision 8 of a review copy.
- Actual relaxation controls: loaded eight saved trace/delay mappings, displayed
  a negative trace and selected 3.7–4.3 ppm. The brush left revision 8 unchanged;
  explicit submission created revision 9 with T1 = 0.5 s. Numeric-bound changes
  and a second fit verified draft clearing in revision 10. Restoring the initial
  review state created revision 11 with the original two current analyses.
- Keyboard mode switching, input-field shortcut isolation and workflow-tab
  navigation were exercised. Desktop 1440×960, mobile 390×844 and the normal
  812-pixel in-app viewport were inspected. No page-level horizontal overflow
  or browser console errors/warnings were observed; the temporary viewport
  override was reset.
- The Figma frame was visually checked, including the final field and trace
  labels; all text uses Inter. Figma is design evidence, separate from browser
  execution and scientific acceptance.

This increment does not complete the whole first batch. Processed 2D/correlation
editing, graphical structure assignment, image/PDF evidence, condition comparison,
experimental qualification and installed-host delivery remain tracked in
[acceptance](ACCEPTANCE.md). The existing alpha release is a separate source
checkpoint; these UI changes do not update that published release automatically.
