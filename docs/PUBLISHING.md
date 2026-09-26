# Publish after local review

The user selected the existing repository [NateOConnellPhD/nateoconnell.github.io](https://github.com/NateOConnellPhD/nateoconnell.github.io), and this checkout's `origin` now points to it. No remote files have been changed, nothing has been pushed, and no DNS settings have been changed.

The user successfully fetched the remote in Terminal. Its default branch is `main`; the inspected tip was `c5f1d44` (`add author profile`). The old source uses Hugo and an Actions deployment workflow. Its Hugo URL is still `https://example.com/`, and its tracked tree has no `CNAME`. Repository visibility, live Pages settings, and DNS have not been verified. The agent's GitHub access remains blocked, but the fetched Git objects can be inspected locally.

## Details to provide

- Domain and DNS provider/registrar.
- Public URLs for the four manuscripts when they become available; these are optional for the initial launch because their current entries are clearly labeled as work in progress.

The biography, profile, headshot, research summaries, selected publications, three talks with materials, web CV, and downloadable CV PDF are already supplied and implemented locally.

## GitHub Pages

Use the existing `nateoconnell.github.io` repository. Its name differs from the account's user-site name (`nateoconnellphd.github.io`), so its expected default project-site URL is `https://nateoconnellphd.github.io/nateoconnell.github.io/`. `_config.yml` now contains that origin and base path. A custom domain will use an empty `baseurl` once supplied and configured.

1. Review the current site locally. The sample posts are unpublished; keep them as drafts or replace them. Check the rendered site on desktop and phone widths.
2. The remote history is already fetched. Keep using this checkout. Repository visibility and Pages availability have not yet been inspected. [GitHub Pages documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/about-github-pages).
3. The user explicitly requested a fresh history, replacing the old Hugo setup. With the reviewed source committed on local `main`, the commands below create one initial commit from its tracked files and replace GitHub's `main`. The old history and the local development commits are not parents of the new commit. [Git orphan branches](https://git-scm.com/docs/git-checkout) and [force-with-lease](https://git-scm.com/docs/git-push).
4. In repository **Settings → Pages**, choose **Deploy from a branch**, `main`, `/ (root)`. GitHub's built-in Jekyll build handles this source. No custom Actions deployment, tokens in source, or backend server is needed. Do not add `.nojekyll`.
5. The repository path is already configured below. GitHub Pages' branch build uses its supported Jekyll stack; the Gemfile is for local development.

Run this sequence once in Terminal to start the new website history:

```sh
cd /Users/noconnell/Websites/Professional_Site &&
git switch main &&
git diff --quiet &&
git diff --cached --quiet &&
git fetch origin --prune &&
website_old_main=$(git rev-parse refs/remotes/origin/main) &&
git checkout --orphan codex/website-initial main &&
git commit -m "Initial professional website" &&
git branch -M main &&
git push --force-with-lease="refs/heads/main:$website_old_main" -u origin main
```

The diff checks stop the sequence if tracked edits have not been committed. The orphan checkout stages the already tracked website files; it does not add ignored private context or generated output. The explicit lease stops the push if GitHub's `main` changes after the fetch. After a successful push, remove the old Hugo upgrade branches:

```sh
git for-each-ref --format='%(refname:strip=3)' 'refs/remotes/origin/chore/upgrade-hugoblox-*' |
while IFS= read -r website_branch; do
  git push origin --delete "$website_branch" || break
done
```

`git rev-list --count main` should report `1`. These commands replace the branch history and delete the old Hugo branch references; they do not purge GitHub's retained objects or pull request records. Select the branch publishing source in step 4; the old Hugo workflow is no longer part of the new tree.

| Site location | `url` | `baseurl` |
| --- | --- | --- |
| Personal GitHub site | `https://nateoconnellphd.github.io` | `""` |
| Selected repository, before a custom domain | `https://nateoconnellphd.github.io` | `/nateoconnell.github.io` |
| Connected custom domain | `https://YOUR-DOMAIN` | `""` |

The layouts prefix internal navigation and CMS image/PDF paths for a project base path. A root-domain personal site remains the simplest publishing target. Set the final `url` before checking the RSS feed and canonical links.

## Connect your existing domain

Use your actual domain and registrar once supplied; do not create a placeholder CNAME file.

1. Verify ownership in GitHub's Pages account settings using its generated DNS TXT record.
2. Set the domain in the repository's **Settings → Pages → Custom domain** before changing routing records. For branch publishing GitHub creates a `CNAME` file; pull that commit into this checkout before subsequent source changes.
3. At the DNS provider, point `www` to `nateoconnellphd.github.io` using a CNAME, without a repository path. For an apex domain, use the provider-supported ALIAS/ANAME or GitHub's documented A records. Keep unrelated email/MX/TXT records intact.
4. Wait for GitHub's DNS check and certificate provisioning, then enable **Enforce HTTPS**.
5. Check both the apex and `www` variants, internal pages, article images, CV download, and RSS.

Use [GitHub's current domain instructions](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site) for the exact records when making the change. No DNS values have been invented for this project.

## Connect Pages CMS

Sign in at [Pages CMS](https://app.pagescms.org), authorize its GitHub App for **only the website repository**, and choose `main`. It reads the existing `.pages.yml`. Complete the actual-device editing and image checks in `EDITING.md` before treating the phone workflow as verified.

## Launch checklist

- Review the supplied content and keep the example blog entries unpublished unless replaced with actual posts.
- Set the final `url` and `baseurl` in `_config.yml`; the site title and description are already populated.
- Check the linked CV PDF and slide downloads. Verify every external work/talk/profile link.
- Turn off `preview_mode` in profile settings only when ready for public indexing.
- Confirm draft entries do not appear at direct URLs, in the blog index, or in the feed.
- Confirm Pages CMS text formatting, image upload, and any desired phone paste behavior.
- Commit source only. Keep `.codex/`, `.codex-tmp/`, gems, and generated output excluded.

GitHub Pages hosts a static public website. Do not use the preview notice, noindex metadata, or the CMS draft switch to protect private material.
