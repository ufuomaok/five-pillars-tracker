# Duration-weighted volume estimate (sensitivity analysis)

**This is an estimate, not a headline figure.** It applies an inverse-probability (Horvitz-Thompson style) correction for length-biased sampling: each captured advert is weighted by `mean_run_gap_days / min(advertised_duration_days, mean_run_gap_days)`, using this quarter's mean scrape interval of 2.8 days as the reference. Short-lived adverts get a bigger weight, since they were less likely to be caught at all. This corrects for the *direction* of the bias described in methodology.md, not its exact magnitude — treat it as a plausible range indicator, not a precise count.

- Raw captured count: 808
- Duration-weighted estimate: 810

| Pillar | Raw count | Weighted estimate |
|---|---|---|
| bedside | 55 | 55 |
| compass | 33 | 33 |
| foundation | 66 | 66 |
| future | 22 | 22 |
| lifeblood | 102 | 102 |
| unclassified | 530 | 532 |
