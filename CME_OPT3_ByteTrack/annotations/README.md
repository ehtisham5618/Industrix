# Factory event annotations

Source: [Twentse textielindustrie-948017.ogv](https://commons.wikimedia.org/wiki/File:Twentse_textielindustrie-948017.ogv),
NOF/NIAM / Netherlands Institute for Sound and Vision, 1949.
License: [CC BY-SA 3.0 Netherlands](https://creativecommons.org/licenses/by-sa/3.0/nl/deed.en).
The benchmark reads the first continuous 600 seconds without looping or cutting
between source sections. The worker transcodes this section to H.264 MP4
(`ffmpeg -t 600 -crf 18 -preset veryfast -an`) for reproducible decoder support;
both comparison paths use the same derivative bytes and original media times.
The original movie includes titles, transport, exterior views and
production-floor operations; it is an edited historical documentary, not
continuous modern CCTV. The source is cached outside Git.

Annotations were produced independently of detector predictions by visually
reviewing five-second contact sheets across the segment and one-second sheets
around production-floor worker intervals. `no helmet` means visible workers at
production machinery without a visible hardhat under the existing demonstration
class policy. Cloth caps are not hardhats. This does not establish that hardhats
were legally required in the historical factory. Interval endpoints have up to
one second of uncertainty; the report must disclose this and cannot use them to
claim a precise two-second operational latency pass. The conservative latency
gate includes one second of onset uncertainty. Do not hide missed intervals.

Normal chimney exhaust is not labeled as a safety incident. No fire, chemical
spill or water-leak incident was visually verified in this section. Intervals
are scene-level labels; they do not support MOT ground-truth ID-switch or
individual-person fragmentation measurements. Those metrics remain unavailable.
Predictions are never used as truth. Factory-frame defect labels are unavailable.

The required project-specific `data/test_factory_clip.mp4` was absent. This
public source is a documented factory-domain audit while an operationally
verified factory clip remains preferable. Source frames/contact sheets stay
local; evaluation uses the licensed original. Annotation metadata is provided
under CC BY-SA 3.0 Netherlands.
