# CME-OPT1 final acceptance checklist

Executed October 4, 2026. Technical acceptance passes; peer approval is external.

| Requirement | Result | Evidence |
|---|---|---|
| Combined source ingested | PASS | Existing CME-1 extraction reused |
| All original image/label bytes preserved | PASS | lineage_audit.json |
| Correct 12-class mapping | PASS | chemical hazard=7, smoke=10; model/YAML match |
| >=150 verified real negative-source examples | PASS | 238 distinct hashes used in output: chemical 142, smoke 96 |
| Observed errors distinguished from visual confusers | PASS | 28 observed +210 could-cause confusers; task section 13 |
| Positives and derivatives excluded from count | PASS | 50 hard-positive sources; 300 derivatives separately recorded |
| New real source collection and verification | PASS | 205 photos, individual licenses/authors, hash-bound AI decisions, all-class absence |
| Source independence and evaluation isolation | PASS | Exact/normal/flipped perceptual checks, capture-day/series and original-photo URL deduplication |
| Color jitter / HSV / sheen / Mosaic / overlay | PASS | 79 /80 /40 /89 /12 outputs |
| Valid Mosaic boxes and smoke semantics | PASS | Geometry tests; overlay only in a real smoke box |
| Training-only expansion | PASS | +505 images; train 5479, val 777, test 334 |
| Dataset-format validation | PASS | 6590 images /10352 annotations, zero invalid/missing/corrupt pairs |
| All 12 classes analyzed and represented | PASS | Before/after image and annotation statistics in every split; counts remain unequal |
| Class balance graph and QC | PASS | Updated graph, QC and 11 real-reference contact sheets |
| Terminal evidence | PASS | Actual commands/output/exit codes; LF-normalized logs |
| Tests | PASS | 12 tests, including hash-bound review and attribution deduplication |
| CME-3 tracking | PASS | CMEOPT1-DATA-002, combined-12class-v3-hardnegative; earlier failure retained |
| Required feature branch | PASS | feature/atlantis-dataset-augmentation, created/pushed during initial work |
| Existing PR | PASS | PR #1; targets current staging; fix commits followed by Ready for Review |
| Peer approval | PENDING | muhammadaliqamar must reassess; author review cannot replace teammate approval |

The >=150 gate follows the supplied causes-or-could-cause definition. It does not
claim >=150 observed detector failures or human-verified annotations. Empty-label
negative photos retain explicit negative-region metadata. Derivatives count zero.

Inherited source-family overlap, incomplete original smoke labels and rounded box
edges remain documented. Outdoor-to-factory transfer and accuracy gains are not
proven. No merge is performed.
