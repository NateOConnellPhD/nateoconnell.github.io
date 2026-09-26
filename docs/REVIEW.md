# Local review record

Updated: 2026-09-26

## Implemented

Jekyll source, responsive editorial styling, accessible navigation, CMS schemas for all content, draft defaults, blog filtering/search/topics, feed, CV PDF download, research and talk detail pages, and publishing/editing guides. The profile, biography, headshot, web CV, and three selected talks use the supplied material. The personal biography preserves the user's wording with typo corrections only. No remote font or analytics requests are made by the site.

The research page now contains one public preprint, four manuscripts in progress, and nine selected journal publications. Its **Methods & theory** section contains nine entries; **Clinical research** contains five: PREVENT, UPBEAT, CROWN, the Wells migraine trial, and the E1912 adverse-events paper. Only the public preprint and journal publications have external manuscript links. The original private manuscript PDFs have not been copied into public assets. The pre–post paper carries the user-supplied 300+ citation milestone in methods/theory publications and is not featured on the homepage. The first-author dose-finding publication is included with its DOI and PubMed link.

The homepage leads with the user's name and PhD credential, academic title, institution, and headshot. It shows all five current research highlights, including PASR estimation of cross-validation variance and LASSO coefficient stability, with a student mentorship invitation in the contact section. The header uses an SVG adaptation of the user's double-helix normal-distribution design with a decision tree underneath. The original R files and reference images remain private. The research page has its own longer, CMS-editable introduction. Both sample blog posts are unpublished, so the blog presents an empty state until the first real post is ready.

The preview helper installs Bundler 2.4.22 inside the task directory. This resolves the incompatible dependency selection made by the system's older Bundler. Build and serve launch Jekyll directly from those local gems; the site has no Gemfile plugin groups. This avoids a denied, unnecessary system-directory scan for manual pages. The lockfile includes the local macOS platform and the generic Ruby platform.

## Name, title, and preview refresh (2026-09-26)

- Diagnosed the missing PhD credential as stale generated output: the source already included it in the shared header and homepage heading, but the server was still returning the earlier pages.
- Added PhD to the About introduction and changed “a tenured Associate Professor” to “an Associate Professor.” Tenure remains in the CV. The rest of the approved biography is unchanged.
- Ran one local Jekyll render using the existing installed dependencies to refresh the running preview. Generation completed successfully in 0.111 seconds; no dependency downloads or new server process were needed.
- Verified HTTP responses from the running homepage, About, Research, and CV pages. They now include PhD, the requested About title, the homepage headshot and logo, all five homepage highlights, both research sections with 14 entries, and the CV tenure detail. Confirmed that private context directories are absent from the generated output.
- Retained `.codex-tmp/site-preview/site/` for the user's active preview: 16,512 KiB (about 16.1 MiB). The entire existing preview directory is 103,072 KiB (about 100.7 MiB). The render process finished; the existing user-started server remains running. Browser layout review is still pending.

## Earlier research organization checks (2026-09-26)

- Added an explicit research area to all 14 entries and the Pages CMS schema. Section links expose both areas from the top of the page. Publication-status filters are scoped to methods/theory so they cannot hide the clinical highlights.
- Verified the UPBEAT citation and study description against the [linked JAMA Network Open article](https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2852964), the CROWN citation and design against its [PubMed record](https://pubmed.ncbi.nlm.nih.gov/37890547/), and PREVENT against the [Hundley paper](https://pubmed.ncbi.nlm.nih.gov/36908314/). CROWN is identified as a published study design, without claims about completed outcomes. The PREVENT role statement and existing Wells and JCO citations were retained from the previously reviewed site content.
- Rendered just the Research page in memory with the installed Jekyll/Liquid dependencies and its real includes. Checked all nine methods/theory entries, the five clinical studies in requested order, study labels, section anchors, scoped filters, valid CMS area choices, unique ordering, and unchanged homepage selection. A first attempt stopped on a missing optional HTML parser; the successful check used the existing dependencies without installing anything.
- Reviewed source differences and whitespace. No full site build, browser interaction, or generated files in that pass. The preview remained stale until the subsequent refresh recorded above.

## Earlier homepage, name, and logo checks (2026-09-26)

- Verified the PhD credential in the profile and homepage heading, the existing homepage portrait asset, and exactly five featured papers in display order: random forests, CV variance theory, PASR estimation, LASSO coefficient stability, and adaptive dose optimization. The homepage no longer caps featured entries at three.
- Strictly parsed the modified homepage and header Liquid templates. Reviewed the source diff, including responsive header wrapping and portrait layout. The approved About prose is unchanged.
- Generated the 17,464-byte SVG from the supplied normal-density and helix equations using a dependency-free Ruby script. Checked valid XML, two strands with 200 samples each, 100 paired rungs, seven decision-tree nodes, unclipped geometry, and no embedded or external raster images or scripts. The thinner sampling of base pairs and adjusted line weights are intended for the small header size.
- A PNG conversion attempt with the system image tool failed because it could not read SVG. It produced no image, and the empty `.codex-tmp/homepage-update/` directory was removed and its absence verified. No new raster rendering or browser layout review passed.
- At the end of that pass, the existing server responded at `http://127.0.0.1:4000/` but still served the previous render. The subsequent refresh is recorded above.

## Earlier content checks (2026-09-26, before the homepage changes)

- Parsed five site/CMS/data YAML files and the research, post, talk, and CV front matter using the existing local Ruby dependencies. All eight CMS content paths exist.
- Checked all 12 research entries against the CMS type choices, required metadata, unique display order, and public-link availability. Confirmed three homepage highlights, with the pre–post paper excluded from those highlights and its citation milestone retained.
- Confirmed the requested LASSO title, both example posts marked unpublished, exactly three talks, the timestamp-free SLDS URL, and the presence of the headshot, CV PDF, and two slide files.
- Strictly parsed 20 Liquid templates and rendered the new research filter controls in memory. The controls expose all work, selected publications, preprints, and work in progress; empty categories are omitted.
- Confirmed the private reference folder remains ignored and excluded from Jekyll output. The manuscript entries do not link to private files. The approved About source has no diff in this pass.
- No dependency installation, full site build, browser interaction, or mobile CMS check was performed in this pass. No temporary files or generated output were created.

## Earlier checks (2026-09-25, before the latest content)

- Preserved the existing website permission configuration and disabled global Git configuration for project commands.
- Parsed site/CMS/data YAML and Markdown front matter; checked all seven CMS content paths, metadata fields, and template includes.
- Compared CMS configuration against official Pages CMS documentation and inspected current rich-text source for enabled image paste/drop and repository upload handling. This is source evidence, not a hosted-editor or mobile-device test.
- Corrected upcoming-talk handling to use `event_date`, independent of Jekyll's publication date.
- Confirmed Ruby 2.6.10, RubyGems 3.0.3.1, project Git access, and an HTTP 200 response from the RubyGems index.
- Installed all 30 dependencies with project-local Bundler 2.4.22. Re-ran the install helper against the completed bundle successfully.
- Rendered the site with Jekyll 3.10.0. Both serve attempts completed generation but failed to bind the local server socket.
- Checked 12 generated HTML pages and 183 local links/assets, fragment targets, absence of unrendered Liquid, valid Atom XML, example-post exclusion from the feed, source/configuration exclusion from published output, and absence of a CV download link before a PDF is supplied.
- Performed a targeted render with `/preview` as the base path. All 171 root-relative generated links/assets resolved under that prefix, including the Markdown article image.
- Reviewed the helper's shell syntax and the Git diff. No browser interaction or visual layout test passed.

## Pending

- Automated visual review: the browser tool cannot start because reading `/System/Library/OpenSSL/openssl.cnf` is denied.
- The original agent-owned server attempts were denied local binding; the user subsequently started a working manual preview at `127.0.0.1:4000`. Its helper uses `--no-watch`, so source edits require a new render before they appear in the browser.
- Confirm desktop and phone layouts, navigation, search/filter interactions, and live draft exclusion. Draft behavior has had source review only.
- Verify Pages CMS against the user's connected GitHub repository and on the user's real phone, including direct image pasting.
- Visually review the latest rendered pages and exercise the research filters in a browser. The current render and HTTP checks do not establish visual layout or interaction behavior.
- Connect the website source repository, GitHub Pages, and the existing domain after local review. The real personal content and CV are already present.

## Cleanup and boundaries

All dependency downloads, caches, compiled native gems, and rendered files were confined to `.codex-tmp/site-preview/`. The largest sampled directory size was 86,784 KiB (about 85 MiB), below the approved 150 MB budget. All task commands finished; both server starts failed, so no preview server remained running.

That original agent-owned directory and its contents were removed, and its absence was verified at the time. The user subsequently restored `.codex-tmp/site-preview/` for manual preview; those existing dependencies and preview files are now retained for that purpose. They are not disposable output from the current content pass. No global configuration or unrelated personal folders were inspected or changed.
