# Baseline audit evidence

The latest baseline is `validation.json`, `statistics.json`, the CSVs, and
`validated_terminal_output.txt`. These files contain the accepted documented
0.0001 normalized edge tolerance and 10,000 total annotations.

`validation_terminal_output.txt` records the legacy validator run before fixes.
`strict_validation_terminal_output.txt` records a diagnostic 0.000001 edge check
that rejected 252 exported rounded boxes. `statistics_terminal_output.txt` comes
from that intermediate strict check (9,748 counted annotations); it is retained
as audit history, not the final baseline. Actual edge overflow was measured as
0.00000125 to 0.0000304878. No source labels or evaluation files were edited.

Commands in historical terminal files refer to their actual original evidence
location under `Preprocessing/reports/cme_opt1/before/`; the evidence was later
moved into this task's separate reports folder at the user's request.

`existing_source_family_overlap.csv` records original shared Roboflow filename
families across splits. These are inherited lineage concerns, not newly added
augmentation leakage. See the overlap contact sheet and final lineage audit.

Terminal evidence is normalized to UTF-8/LF and trailing whitespace is removed; captured content is retained. Per-image resolution arrays in JSON are compactly formatted without changing their values.
