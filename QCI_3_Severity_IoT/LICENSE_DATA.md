The user confirmed on 2026-10-09 that the current use is **noncommercial research
and evaluation**. The prior commercial-permission concern is therefore resolved
for this scope; no publisher email or fabricated permission letter is needed.

Kolektor Group d.o.o. provided and annotated the original images. ViCoS Lab,
University of Ljubljana, publishes [KolektorSDD](https://www.vicos.si/resources/kolektorsdd/)
under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/).
Preserve that attribution and license when sharing the dataset and adapted data;
the repository's software MIT license does not replace the dataset license.
Commercial use requires a separate route through the publisher. This delivery
does not grant commercial rights or claim factory deployment approval.

QCI-1 adaptations: quarantine ambiguous annotation and cross-split duplicates;
curate physical-item-disjoint splits; convert binary source BMP masks to indexed
PNG masks; preserve source images; record hashes and provenance. QCI-2 trains a
binary mask-presence ResNet18 classifier on that curated data and provides real
Grad-CAM attribution. QCI-3 uses those predictions without changing model outputs.
Local recovery archives carry this notice and the dataset provenance reports.

Required citation: Domen Tabernik, Samo Šela, Jure Skvarč, Danijel Skočaj (2019),
“Segmentation-Based Deep-Learning Approach for Surface-Defect Detection”,
*Journal of Intelligent Manufacturing*, [doi:10.1007/s10845-019-01476-x](https://doi.org/10.1007/s10845-019-01476-x).
