# Methodology: Kazakh language checks

Scope of this document: the four Kazakh-specific issue types (`orthography`, `suffix_harmony`,
`glossary_violation`, `inconsistent_term`), the glossary, how we measured them, and the
transliteration bonus. Basic checks, LLM checks and the fix pipeline are described by their owners.

## Key idea: the file is its own reference

The seeded errors are point distortions of an otherwise consistent translation (~5,500 strings).
So we compare each string with the statistics of the whole `intl_kk.arb`, not with
an external dictionary:

* a word seen 1–2 times that becomes a word seen 40 times after swapping one letter is a typo;
* a term translated one way in 85 of 87 strings and another way here is an inconsistency.

This makes every finding explainable with numbers (*«кайта» 1 time, «қайта» 55 times*).

Nobody reads the file by eye: native speakers only review what the tool found.

## Checks

| Type | Method | Severity | Confidence |
|---|---|---|---|
| `orthography` | Word frequency over the kk file. A word with frequency ≤ 2 is a candidate; we try 1–2 swaps from `LETTER_PAIRS` (а→ә, г→ғ, к→қ, н→ң, о→ө, у→ұ/ү, х→һ, и→і). If the variant occurs ≥ 3 times and ≥ 3× more often, it's a typo; the suggestion is the corrected string. Also catches Latin homoglyphs inside Cyrillic words (`бөлімiне`, `көтерілеcің`). | medium | 0.85 / 0.95 |
| `suffix_harmony` | Regex: placeholder immediately followed by a case/number affix from `SUFFIXES` (`{name}-ға`, `{price}ге`, …). The value is inserted at runtime, so a fixed affix is wrong for half of the values. Ordinals (`{place}-орын`) are not affixes and are not flagged. Suggestion: the clause is reworded so the placeholder goes after a colon (`{price}-ге сатып алу → Сатып алу: {price}`); hard cases (two placeholders in one clause, placeholder inside a tag) get no suggestion. | high | 0.9 |
| `glossary_violation` | For *strict* glossary terms (the ones the case names: фракция, отбасы, Grand Coins, бизнес, варн): ru has the term stem, kk has neither the glossary stem nor any `allowed_variants`. If the Russian word was left in kk, the suggestion swaps it for the term. | medium | 0.85 |
| `inconsistent_term` | For other glossary terms with a dominant translation (≥ 80% of strings): a missing string is flagged if it contains a rival word aligned with the term (occurs mostly in strings with the same ru term), if the Russian word was left as is, or, for short strings (≤ 8 words), if the term is near-unanimous (≥ 95% of ≥ 20 strings). The suggestion re-inflects the canonical term with the rival's affixes (`ойнаушыларды → ойыншыларды`). | medium | 0.6–0.85 |

Strings that are empty, identical to ru or have no Cyrillic are skipped: they belong to
`untranslated` / `same_as_source` / `wrong_language`, which have priority in `resolve`.

### Kazakh morphology in code (`locqa/lang/kk.py`)

Words are compared by stem, because endings change: *отбасы / отбасына / отбасының*.

* `stem()` drops alternating final к/қ/п (*көлік → көлігі*) and the soft sign of loans
  (*инвентарь → инвентарыңыз*).
* Short stems (*үй*) match only with a known chain of affixes, so *үй* does not match *үйрену*.
* `harmonize()` / `inflect()` pick the correct affix variant by vowel harmony and the last
  sound (*үй+ге, кітап+қа, адам+ның, жол+дар, жол+мен*). Used to re-inflect suggestions.
* Russian side: endings are stripped with a list of noun/adjective endings, plus fleeting vowels
  (*уровень / уровня*), so *бан* does not match *банк* and *работа* does not match *обработка*.

### Established alternatives are not errors

If a different translation is used in ≥ 3 strings and ≥ 10% of a term's strings, it is an
established variant, not a seeded error. Such cases go to `glossary_audit()` for the linguist
(add to `allowed_variants` or unify), not to the report. This is what removed most false alarms
(e.g. *тіркелгі* for "аккаунт", *автомобиль* used as a loan).

## Glossary

`glossary.csv`: `ru, kk, en, comment, allowed_variants, strict`.

* 104 game terms built from the files themselves: for each Russian term we looked at which Kazakh
  stems co-occur with it across all strings, took the dominant one and checked it by a native speaker.
* `allowed_variants` (separated by `|`) holds player slang and accepted synonyms:
  *варн, мут, фура, ГК/GC*, *сыйақы/марапат/жүлде* for "награда".
* `strict=1` marks the terms named in the case brief; only they produce `glossary_violation`.
* `brands.txt`: names that stay untranslated (Grand Mobile, Grand Coins, GC, VIP…), used by
  `same_as_source`.

## Measuring quality and review provenance

The native review consists of 405 distinct candidates in three parts, all checked by one
Kazakh native speaker (`native_1`). The part labels A/B/C are assignment partitions, not
independent reviewers. Exact original CSVs and their SHA-256 hashes are retained privately.

| Original label | Count |
|---|---:|
| Confirmed, correct type | 378 |
| Rejected | 24 |
| Unresolved | 3 |

Agreement among labelled candidates is 378/402 = **94.03%**. A deterministic random sample
of 100 original candidates (seed 7) has 95 confirmations and 5 rejections. This reuses the
native labels; it is neither independent validation nor hidden-test precision. Semantic
candidates that were originally review-only are included in this population.

Human review by type (before filtering or agent corrections):

| Type | Confirmed | Rejected | Unresolved |
|---|---:|---:|---:|
| machine_translation_suspect | 259 | 16 | 2 |
| placeholder_mismatch | 11 | 1 | 0 |
| same_as_source | 26 | 7 | 0 |
| suffix_harmony | 8 | 0 | 0 |
| untranslated | 16 | 0 | 0 |
| wrong_language | 13 | 0 | 0 |
| inconsistent_term | 13 | 0 | 0 |
| length_overflow | 10 | 0 | 1 |
| orthography | 22 | 0 | 0 |

Four additional agent corrections address a rejected placeholder typo and the three
unresolved strings. The same native speaker explicitly confirmed all four on 2026-10-31.
Text-bound confirmation records are preserved in agent_corrections.json; original CSV labels
and historical metrics are never rewritten. All 382 changed values now carry `x-reviewed: true`
and reviewer `native_1`. No changes await native confirmation.

### Synthetic recall

`scripts/compare_baselines.py` uses the same mutations and seeds 7,11,23 for every detector.
There are 11 mutation variants but **7 expected issue types**: orthography, suffix_harmony,
glossary_violation, inconsistent_term, placeholder_mismatch, untranslated and wrong_language.
Do not confuse variant count with taxonomic coverage. The generator starts from strings
considered clean by the reference detector; the resulting distribution favours these rules.
Glossary rules, allowlists and thresholds were tuned on the case data, so this is not a holdout.

Refreshed results, seeds 7,11,23:

| Detector | Typed synthetic recall | Capable issue types | Findings on original case file |
|---|---|---|---:|
| Structural baseline | 20% | 3/11 | 28 |
| Basic rules | 30% (29–30%) | 6/11 | 67 |
| Full offline locqa | 95% (94–96%) | 11/11 | 134 |

The full offline baseline now includes deterministic length checks, so its clean mutation
pool differs from older runs. The previous 98% table used basic+Kazakh+signals without
these length checks and is not the current full-baseline result. The refreshed machine-readable
results are `out/baselines_updated.json` in the private workspace. Capability counts are explicit sets, separate from types actually found in the
mutation test. The full offline baseline includes deterministic appended-tail detection.
Recall on the organizers' hidden planted errors is unknown.

### Structural safety and reproducibility

`locqa validate` checks the **whole** final ARB: names and ordinary placeholder multiplicity,
printf parameters, markup tags, ICU grammar and explicit review metadata for changed values.
Only `other` is mandatory for a plural; one/zero/etc are optional selectors. Apostrophes in
ordinary words do not hide following placeholders. Compact input and multiline metadata are
updated as complete JSON values. Untouched sections and values survive; output replacement
is atomic. Input resource duplicates are warnings with last-value semantics, documented in
`structural_validation.json`.

`finalize.py` checks CSV/source version alignment, rejects duplicate input parts and publishes
only a complete validated build. It preserves the previous result directory. `validate_flutter.py`
first records the original-template failure, then runs standard Flutter on explicit compatible
copies. Original game resource names remain in the main deliverable; three renamed identifiers
are listed in `flutter/key_mapping.json`. No keys are silently dropped.

### Costs and language bonuses

Finalization and validation use no paid LLM calls. Historical `final_split.log` records an
estimated $7.0484 including cached answers for one incomplete pass. This is not a verified
billing total, and repeated cache/run totals must not be added. Provider and GPU invoices were
not available. `cost.json` records this uncertainty and a hash of the evidence log.

The Latin transliterator implements the project's chosen 2021-style mapping; we do not claim
it is the currently enacted official alphabet. It preserves placeholders/tags and reports growth.
The Uzbek bonus is structural only. Dart/Python affix selection matches on 343 shared vectors;
this parity check is not an independent linguistic assessment of every suffix rule.
