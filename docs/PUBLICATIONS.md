# Publication list

`/publications/` shows a saved OpenAlex list with local search and sorting by date or citation count. Entries render without JavaScript, and visitors do not contact OpenAlex. Research & work links to the list; Google Scholar remains linked separately. OpenAlex coverage and citation counts differ from Scholar.

The homepage's **Recent papers** box reuses this same snapshot and weekly refresh. It shows the three newest articles, reviews, or preprints by publication date, with direct paper links, dates, and journal names when available. Conference abstracts and other record types stay in the full list. The box links to all publications and the Google Scholar profile, identifies OpenAlex as its source, and shows the last refresh date. It makes no additional API requests and stays hidden when no eligible records are available. New papers appear once OpenAlex indexes them and the next refresh succeeds; this is not a direct Google Scholar feed.

The Update publications GitHub Actions workflow refreshes the data every Monday at 09:23 UTC, on changes to its script/configuration, or from Actions → Update publications → Run workflow. It starts after these files are pushed to main. It commits only `_data/publications.json` and explicitly requests a GitHub Pages build for the existing branch-based deployment. No change to Pages hosting settings is needed. Repository rules must allow the workflow to write main. GitHub can disable scheduled workflows in inactive public repositories; check Actions if the displayed update date becomes stale.

To populate or refresh locally, from the project directory:

```sh
python3 -B scripts/update-publications.py
```

This uses the Python standard library, calls only `api.openalex.org`, and writes only the maintained `_data/publications.json` snapshot (normally under 200 KB). It downloads no dependencies. Review and commit that file after a local refresh. Until the first successful refresh, the page provides the Google Scholar link instead of inventing publication data.

The importer verifies one author ID across three known papers, matching Nathaniel's full name. It refuses ambiguous/missing identity matches, partial pagination, and malformed records before writing the snapshot. API errors preserve the previous list. If an OpenAlex author merge changes the record, review the identity matches before changing the configuration.

Small API queries can run without a key. If OpenAlex returns an authentication/quota error, create a free OpenAlex API key and put it in the repository's Actions secret `OPENALEX_API_KEY`; never commit it. The workflow already reads that optional secret. Pagination uses ordinary page numbers, not keyed cursor paging.

To exclude a misattributed work, add its full OpenAlex URL to `excluded_ids` in `scripts/publications-config.json`. The title patterns already exclude the LASSO stability manuscript as requested. Remove that exclusion only when it is ready to appear publicly. Curated research highlights remain independently managed in Pages CMS.

Validation at implementation: source/diff review and targeted importer checks. The local session blocked API access even after a narrow permission request, so the live author match, initial import, GitHub workflow, and rendered page still need verification. No full site build was run.
