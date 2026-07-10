# five-pillars-taxonomy

A keyword-to-pillar classification taxonomy for digital health job roles,
built around the **Five Pillars of Digital Health** framework:

| Pillar | Focus |
|---|---|
| Foundation | Infrastructure — connectivity, hardware, digital maturity |
| Lifeblood | Data — information flow, standards, governance |
| Compass | Leadership & digital strategy |
| Bedside | Clinical practice & informatics |
| Future | Education & training |

The Five Pillars framework was created by [Ufuoma Okpeahior](https://ufuomao.com).
This package is the standalone, versioned implementation of the
classification logic — job title and description in, pillar label out.

It powers the [Five Pillars Digital Health Vacancy Tracker](https://fivepillars.ufuomao.com),
but is designed to be usable independently of that project by anyone
working with NHS or wider digital health workforce data.

## Why a separate package

Job titles across NHS digital health roles are wildly inconsistent —
"Clinical Informatics Officer" and "EPR Trainer" describe closely related
work but share almost no vocabulary. Reliably grouping roles like these
under a shared pillar requires a maintained, documented mapping, not a
one-off script. Keeping that mapping in its own versioned package means:

- it can be tested and regression-checked independently of any scraper
- it can be reused by anyone else working with digital health job data
- changes to the taxonomy are visible in git history, not buried in
  application code

## Install

```bash
pip install five-pillars-taxonomy
```

(Not yet published to PyPI — for now, install from source: see
Development below.)

## Usage

```python
from five_pillars_taxonomy import PillarClassifier

classifier = PillarClassifier()

result = classifier.classify("EPR Trainer")
print(result.primary_pillar)     # "bedside"
print(result.secondary_pillar)   # None
print(result.confidence)         # "high"
print(result.scores)             # {'foundation': 0.0, 'lifeblood': 0.0, ...}
```

You can pass a job description alongside the title for a stronger signal:

```python
result = classifier.classify(
    title="Digital Officer",
    description="Supporting rollout of the trust's EPR and clinical systems",
)
```

Run `python examples/classify_example.py` for a few more worked examples.

## How classification works

Matching is **weighted keyword matching**, not machine learning. This is
deliberate: every classification is explainable — you can always point to
the exact keyword(s) that produced a label — and the taxonomy can be
extended by anyone editing a YAML file, without touching code.

- Each pillar in `taxonomy.yaml` has a list of keywords with weights.
- Title matches count 3x more than description matches.
- A pillar can have `exclude` terms that discount its score when a
  competing, more specific term is present.
- If no pillar clears the minimum score, the result is `"unclassified"`
  rather than a forced best guess.
- If two pillars score closely, both are returned (`primary_pillar` +
  `secondary_pillar`) — many digital health roles genuinely span two
  pillars, and collapsing that to a single label would lose information.

## Known limitations (v0.1.0)

This is a first-pass taxonomy, seeded from national NHS digital workforce
terminology (the DDaT profession framework, the National Competency
Framework for Data Professionals, and common NHS digital job titles) —
not yet validated against a large sample of real postings. Expect to see:

- generic titles ("Digital Officer", "Systems Support") that need more
  context (description text, directorate) to classify confidently
- keyword coverage gaps for newer or less common role titles
- weights that haven't been tuned against real-world classification
  accuracy — they encode reasonable starting assumptions, not measured
  precision/recall

See `tests/fixtures/sample_titles.csv` for the current set of validated
test cases, and `CHANGELOG.md` for how the taxonomy evolves over time.

## Development

```bash
git clone https://github.com/REPLACE_WITH_YOUR_USERNAME/five-pillars-taxonomy
cd five-pillars-taxonomy
pip install -e ".[dev]"
pytest
```

To extend the taxonomy, edit `five_pillars_taxonomy/taxonomy.yaml`, add a
test case to `tests/fixtures/sample_titles.csv`, run `pytest`, and bump
the version in both `taxonomy.yaml` and `CHANGELOG.md`.

## License

MIT — see `LICENSE`. Free to reuse, including commercially, with
attribution.

## Disclaimer

This package classifies publicly available job title and description
text. It is an independent project and is not affiliated with, endorsed
by, or produced in partnership with NHS England, NHS Business Services
Authority, or any NHS organisation.
