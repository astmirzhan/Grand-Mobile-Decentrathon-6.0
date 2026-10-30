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

## Measuring quality

There is no validation set, so we measure ourselves.

### Recall: mutation test (`scripts/mutate_kk.py`)

We take strings the tool considers clean, inject known errors and check that they are found
**with the right type**. One mutation per string, at most 2 per glossary term (as in a real
seeded set), only where ru really contains the term.

| Type | Injected per run | Recall (typed), 5 seeds |
|---|---|---|
| orthography | 10 | 100% |
| suffix_harmony | 10 | 100% |
| glossary_violation | 6 | 100% |
| inconsistent_term | 10 | 74% (60–90%) |
| **total** | 36 | **~92%** |

`inconsistent_term` misses are synonyms placed in long descriptions where the rest of the
sentence gives no statistical signal; we accept this to keep precision high (see below).

### Precision: manual labelling (`scripts/precision_sample.py`)

A random sample of findings is labelled by a native speaker: `1` = real error of this type,
`0` = false alarm, `t` = real error with wrong type.

| Type | Findings on real file | Labelled | Precision |
|---|---|---|---|
| orthography | 19 | TBD | TBD |
| suffix_harmony | 8 | TBD | TBD |
| inconsistent_term | 14 | TBD | TBD |
| glossary_violation | 0 | – | – |

Before tuning, the glossary checks produced 116 findings on the real file, mostly legitimate
paraphrases; after the "established alternative" and strict/non-strict rules — 14
(rival clusters are counted over distinct texts, so duplicated strings do not create a fake rival).
Rule-based rewording covers 6 of 8 `suffix_harmony` findings.

### Native-speaker review

| Reviewer | Strings reviewed |
|---|---|
| Person 3 (kk) | TBD |

## Bonus: Latin transliteration (`scripts/translit_kk.py`)

Official Kazakh Latin alphabet (2021 revision): ә→ä, ғ→ğ, қ→q, ң→ñ, ө→ö, ұ→ū, ү→ü, ш→ş,
ы→y, і→ı, и/й→i (İ in uppercase). Placeholders and tags are untouched; the ARB is rewritten
line by line so `@@comment` sections survive. Strings that grow by > 10% and ≥ 3 characters
(ц→ts, ч→ch, ю→iu, я→ia) are reported for UI length review: 7 strings in the real file.

## Reproduce

```
python -m pytest tests/
python scripts/mutate_kk.py --source intl_ru.arb --target intl_kk.arb --glossary glossary.csv --seed 7
python scripts/precision_sample.py sample --source intl_ru.arb --target intl_kk.arb --glossary glossary.csv --out sample.csv
python scripts/precision_sample.py score sample.csv
python scripts/translit_kk.py intl_kk.arb --out intl_kk_latn.arb --report growth.csv
```
