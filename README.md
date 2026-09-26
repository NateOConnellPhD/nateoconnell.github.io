# Personal research website

A locally developed Jekyll website for GitHub Pages, with Pages CMS for browser-based editing. A pale blue-to-green background, serif typography, dark blue text, and green accents; no remote fonts, analytics, or frontend dependencies.

## Current status

The local site contains Nathaniel O’Connell’s profile, approved biography, headshot, downloadable CV, three selected talks, five current research manuscripts, and nine selected publications. The research page separates methods and theory from clinical research. Its five clinical highlights are PREVENT, UPBEAT, CROWN, the Wells migraine trial, and the E1912 adverse-events paper. The two sample blog posts are unpublished drafts, ready to replace when writing the first post.

The current source rendered successfully with Jekyll. Browser layout review is still pending; start the preview server below when reviewing locally. The local `origin` points to the user's existing `NateOConnellPhD/nateoconnell.github.io` repository. The user fetched its history in Terminal, and the fetched `main` contains a Hugo site with Actions deployment, an `example.com` URL placeholder, and no tracked `CNAME`. The new site is configured for the repository's GitHub Pages project path. Replacement and pushing remain for the user to run in Terminal; no hosting or domain settings have been changed.

See `docs/REVIEW.md` for what was actually checked and any remaining limitations.

## Sections

- **Home:** name, academic title, headshot, research introduction, all five current research papers, latest posts, and contact.
- **About:** biography, portrait, and research interests.
- **Research:** separate methods/theory and clinical sections, with section jump links, study labels, individual pages, and publication-status filters within methods/theory.
- **Talks:** dates, abstracts, PDF/PowerPoint slides, recordings, and event links.
- **CV:** an editable web CV and the supplied downloadable PDF.
- **Blog:** Markdown articles, images, topics, search, and an Atom feed at `/feed.xml`.

Navigation and content work without JavaScript. JavaScript adds local filtering and search. Layouts include keyboard focus, a skip link, image descriptions, print styles, and narrow-screen layouts.

## First local review

Requires Ruby 2.6 or newer and RubyGems 3.0.1 or newer. The install command downloads Bundler 2.4.22 into the project's temporary directory, so it also works with macOS's older system Bundler. The Gemfile uses Jekyll 3.10.0 to match GitHub Pages. No local dependencies are installed by creating this project.

After authorizing dependency installation and a local build:

```sh
cd /Users/noconnell/Websites/Professional_Site
sh scripts/site install
sh scripts/site serve
```

Visit `http://127.0.0.1:4000`. Stop with Control+C. The server has file watching disabled; restart after changes. `sh scripts/site build` produces a one-off local build without a server. Both commands override the GitHub project base path so the local preview stays at `/`; GitHub Pages builds with the published path in `_config.yml`.

The helper confines downloaded dependencies, Bundler settings, temporary files, and generated site files to `.codex-tmp/site-preview/`. The local review used a 150 MB budget and sampled about 85 MiB at its largest. Initial installation compiles native gems and can take several minutes. Do not install a new runtime or change global settings automatically. When using the restricted Codex profile, system Ruby dependencies, Git metadata, and local server sockets may require specifically scoped permissions.

Build and serve launch Jekyll directly from the project-local gems, avoiding Bundler's optional system manual-page directory scan. This site uses no Gemfile plugin groups; revisit the launcher if adding those later.

After review, stop the preview process and remove only `.codex-tmp/site-preview/` and task-owned `.codex-tmp/site-setup/` if present. Keep the source and any resulting `Gemfile.lock` in Git. Do not commit generated files or `.codex/`.

## Editing after GitHub is connected

Open [Pages CMS](https://app.pagescms.org), select the repository and branch, and use the entries in its sidebar. The supplied `.pages.yml` already defines the editor. No local server is needed for normal publishing.

See [the editing guide](docs/EDITING.md) for posts, images, drafts, and CV updates, and [the publishing guide](docs/PUBLISHING.md) for GitHub Pages and your existing domain.

## Source map

| Content | File or folder |
| --- | --- |
| Name, introduction, portrait, research interests, contact | `_data/profile.yml` |
| Homepage headings and section introductions | `_data/home.yml` |
| Methods/theory and clinical introductions | `_data/research.yml` |
| Biography | `_pages/about.md` |
| CV and PDF path | `_pages/cv.md` |
| Blog posts | `_posts/YYYY-MM-DD-title.md` |
| Publications, projects, and other work | `_research/` |
| Talks | `_talks/` |
| Uploaded images | `assets/images/` |
| Uploaded PDFs | `assets/files/` |
| Talk slides | `Presentations/` |
| CMS fields | `.pages.yml` |
| Site URL, base path, and generator defaults | `_config.yml` |
| Presentation | `_layouts/`, `_includes/`, `assets/css/site.css` |
| Header logo | `assets/images/normal-helix-logo.svg`, generated by `ruby scripts/build-logo.rb` |

`preview_mode: true` displays a preview notice and discourages search indexing. It is not access control. Example blog entries are unpublished and excluded from the website and feed. They remain visible in the repository and CMS; replace their contents and turn off their `example` flag before publishing them. Original reference manuscripts stay in the ignored and Jekyll-excluded `Context_not_for_upload/` folder.
