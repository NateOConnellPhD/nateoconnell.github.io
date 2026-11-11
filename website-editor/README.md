# Private website editor

A separately hosted editor for `NateOConnellPhD/nateoconnell.github.io`. The public Jekyll site stays on GitHub Pages. This directory is explicitly excluded from Jekyll output. It is not yet a deployed service.

## What it does

- GitHub App sign-in, restricted on the server to one numeric GitHub account ID.
- Forms for blog posts, research entries, talks, biography, CV text, profile links, and homepage/research/contact introductions.
- Markdown writing with formatting buttons and a safe content preview. The preview is not a full Jekyll rendering; mathematical notation and complex Markdown may look different on the final site.
- GPT suggestions for the selected document, optional reference PDF, and explicit accept/discard. The assistant receives only the selected content, request, and intentionally attached PDF. It cannot publish, change visibility, or modify code. Each request is independent; accepted changes become the next request's document context.
- Private draft and image storage in a separate private GitHub repository. No drafts are placed on public branches. Uploads and clipboard-image events are implemented; phone clipboard behavior still needs an actual-device check. The file picker is always available. Larger still images are resized in the browser; GIFs must be under 1 MB.
- Save, review exact changes, publish a single commit, and request a Pages build. Concurrent edits cause a conflict instead of an overwrite. Restoring a previous publication loads it into a private draft for another review/publish cycle.

The current blog draft from the chat has not been copied into this app or published. This version edits content, not layout templates, JavaScript, hosting settings, or the editor's own source. Existing PDF links can be updated; uploading a replacement public CV PDF remains available through Pages CMS.

## Deploy on Vercel

Use a Vercel account you control. No registrar or public-site hosting change is needed. Keep real credentials in Vercel environment variables, never in this repository, browser storage, or chat.

1. **Create private draft storage in GitHub.** Create `NateOConnellPhD/nateoconnell-editor-private`, set it to **Private**, initialize it with a README, and use `main` as its default branch. Do not fork the public website. The server refuses to operate if this repository is public or a fork. Keep it private: its history contains drafts, uploaded images, and request counters.
2. **Import the existing website repository into Vercel as a separate project.** Set Root Directory to `website-editor`, Framework Preset to **Other**, and use the checked-in `vercel.json` configuration. This deploys the editor only. The single pinned `yaml` dependency installs during deployment; no build framework is needed. Deploy once to obtain the project's production `https://…vercel.app` address. Sign-in is intentionally unavailable until configuration is complete. Use Node.js 24 and leave Fluid compute enabled (the configured request limit is 120 seconds).
3. **Register a GitHub App** in GitHub → Settings → Developer settings → GitHub Apps → New GitHub App. Give it a unique name such as “Nate website editor”. Set Homepage URL to the editor's production address. Set **Redirect URI** (called Callback URL in some documentation) to `https://YOUR-EDITOR.vercel.app/api/auth/callback`, with wildcard matching disabled. Leave “Request user authorization (OAuth) during installation” and Device Flow unchecked, and leave Setup URL blank. Disable webhooks. Under repository permissions, grant **Contents: Read and write**, **Pages: Read and write**, and the default **Metadata: Read-only**. No organization or account permissions are needed. Make installation available only on your account. If GitHub requires a private key before installation, generate one under **Credentials → Key pairs → New key** (or **Generate a private key**, depending on the interface). Store the downloaded PEM securely outside the website repository; do not paste it into chat. Then install the app on **only** the public website repository and the private draft repository. This is a GitHub App, not an OAuth App with broad `repo` scopes. Leave user access tokens expiring.
4. **Create a client secret** on the GitHub App's settings page. Copy the Client ID and Client secret into Vercel's production environment variables. The editor uses your short-lived GitHub App user access token; it does not load an app private key or installation ID. A private key generated to satisfy GitHub's installation step does not need to be uploaded to Vercel for this implementation. The client secret and the private key are separate credentials.
5. **Set the remaining environment variables** listed below. Redeploy the Vercel project after setting them. Production secrets should not be shared with untrusted preview deployments.
6. **Connect OpenAI.** Claim the subscription API-credit benefit into the intended API organization, create a project/key there, and set `OPENAI_API_KEY` on Vercel. No key is needed for manual editing. Model availability depends on that API project. The default uses the Responses API with `gpt-5.4-mini`; change `OPENAI_MODEL` to another compatible model if desired.
7. **Sign in and verify the connected flow** using the checklist below. A successful GitHub commit is reported separately from completion of the public-site deployment.

### Environment variables

| Variable | Value |
| --- | --- |
| `APP_ORIGIN` | Exact production editor origin, e.g. `https://YOUR-EDITOR.vercel.app`, without a trailing slash. |
| `GITHUB_CLIENT_ID` | Client ID from the GitHub App. |
| `GITHUB_CLIENT_SECRET` | Client secret from the GitHub App. |
| `ALLOWED_GITHUB_USER_ID` | Your numeric account ID. See the `id` field at `https://api.github.com/users/NateOConnellPhD`. Do not use a repository or app ID. |
| `SESSION_SECRET` | 64 hex characters generated with `openssl rand -hex 32`. Rotating this value signs out existing sessions. |
| `DRAFT_REPOSITORY` | `NateOConnellPhD/nateoconnell-editor-private`. |
| `OPENAI_API_KEY` | Key from the API organization receiving your credits. Optional until enabling AI. |
| `OPENAI_MODEL` | Defaults to `gpt-5.4-mini`; must support Responses structured outputs and PDF input when attaching PDFs. |
| `MAX_DAILY_AI_REQUESTS` | Defaults to 40, allowed range 1–100. The server persists the count in private storage, resetting by UTC date. This is a request cap, not a guaranteed dollar cap. Each request also has input-size and output-token limits. Failed attempts count toward the cap. |

The application sets `store:false` on Responses requests. This does not promise zero retention by OpenAI; API data handling follows the account's applicable policies. PDFs are sent inline for the selected request and are not saved into either GitHub repository by the editor. Drafts and draft images are stored in the private repository and its history. The application uses no browser localStorage or service-worker cache for them.

### Optional `edit.nateoconnell.com` address

After the production deployment works, add `edit.nateoconnell.com` to the Vercel project's domains. At Namecheap, add **only the `edit` DNS record** Vercel specifies. Preserve the existing apex and `www` records for GitHub Pages. Then update `APP_ORIGIN`, the GitHub App homepage/callback, and redeploy. Use the custom editor domain consistently; cookies are host-specific. Cloudflare is not required.

## Connected review before first public edit

1. Confirm your account can sign in and a different GitHub account cannot.
2. Create a throwaway private draft, save, sign out/in, and reopen it. Confirm nothing was written to the public repository.
3. Upload/paste a non-sensitive image from desktop and your actual phone. Check that it survives reopening the draft. Check the upload picker when clipboard pasting is unavailable.
4. Make one small GPT request. Confirm accepting a suggestion only edits the working draft, and that OpenAI usage appears in the intended organization. Reject/discard another suggestion.
5. Open an existing page, edit it, and inspect both content preview and exact changes. A disposable draft on the private repository is suitable for exercising this without publishing.
6. For the first intentional public change, review and publish, confirm the GitHub commit and Pages deployment, and check the live page. Test “Restore previous version” by loading it into a private draft first.

User approval to build this app does not constitute a successful deployment, connected login test, or approval to publish a blog post. No accounts, repositories, credentials, domains, or paid API calls have been created/configured by the implementation itself.

## Local checks

With Node 24 and the pinned YAML dependency available:

```sh
node --test test/security.test.js
node --test test/content.test.js
```

The security checks use mocked services; they do not contact GitHub/OpenAI or write files. Content checks read only editable website source files, use mocked publication calls, and generate no site output. Live credentials and a connected deployment are required to verify OAuth, Vercel routing, GitHub permissions, real API responses, and Pages deployment end to end.

Implementation review, November 10, 2026:

- Previously completed: 16 targeted security/publishing checks passed, and JavaScript syntax was checked.
- After approval for the dependency and local review, all 24 existing editable documents passed the editor's field/body validation. This compatibility check used the installed system Ruby YAML parser to read the source, then passed the fields and body to the editor's actual `validateDocument` function. It did not test the editor's YAML parser or serialization.
- The pinned `yaml@2.9.1` download was blocked because `registry.npmjs.org` is outside the session's network allowlist. The three YAML-dependent content tests remain unrun.
- Desktop/mobile-width browser review could not start: the browser tool's Node runtime was denied access to `/System/Library/OpenSSL/openssl.cnf`. The bundled Playwright runtime was also unreadable under the current filesystem permissions. No visual or clipboard behavior has been verified.
- No live login, paid API call, publication, or actual-phone clipboard test has been performed. No site content was changed during this review. The empty task-owned `.codex-tmp/editor-review` directory was removed; no disposable output remains.

The review approval is already granted. Resume the YAML and browser checks once the required dependency and browser runtime are accessible; do not treat these environment blocks as passing tests.

## Design references

- [GitHub App user authorization and PKCE](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [GitHub tree updates](https://docs.github.com/en/rest/git/trees#create-a-tree) and [non-forced reference updates](https://docs.github.com/en/rest/git/refs#update-a-reference)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [file inputs](https://developers.openai.com/api/docs/guides/pdf-files), and [API credit benefit](https://help.openai.com/en/articles/20001626-api-credits-benefit-for-eligible-chatgpt-subscriptions)
- [Vercel Node functions](https://vercel.com/docs/functions/runtimes/node-js)
- [YAML parser](https://eemeli.org/yaml/)
