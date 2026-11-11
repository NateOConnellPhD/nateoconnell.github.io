# Private website workspace

An online editing workspace for `NateOConnellPhD/nateoconnell.github.io`. The public site stays on GitHub Pages; this editor runs separately on Vercel. Jekyll excludes this directory from the website output.

After publishing the login shortcut, open **https://nateoconnell.com/login**. It redirects to https://nateoconnellgithubio-website-editor.vercel.app/, where you sign in with GitHub. No DNS change or new account is needed for that shortcut.

## Working on the website

The opening screen is a conversation about the whole website. You can ask questions, discuss options, change which papers are highlighted and their order, add pages and navigation, change layouts, write posts, edit CSS/JavaScript, change build configuration, or work on the editor itself. Your message appears immediately; assistant replies and progress arrive through an authenticated event stream. You can type your next message while it works, stop the response, and continue the conversation after it finishes. Enter sends; Shift+Enter adds a line. The server supplies the public project and your pending changes to an OpenAI-hosted Linux workspace. The agent can edit files, use terminal tools, research public sources, and run focused builds. Follow-up requests receive the saved conversation and working changes in a fresh workspace.

Saved conversations appear in the left sidebar. The conversation scrolls independently of the message composer, which stays at the bottom. Replies follow the scroll position only while you are near the latest message; **Latest message** returns you there after reading earlier text. On phones, the menu button opens conversation history.

**Files & changes** opens a separate project panel with the folder tree, pending changes, file editor, and any built preview. Files can be created, edited, moved, deleted, and uploaded there. The Content and Drafts tabs retain the structured writing forms, formatting buttons, image picker/paste handler, and optional page-specific writing assistant. Those document drafts are separate from the main chat's working changes. The plus button in the message composer attaches a reference PDF; it does not publish an upload.

For visual work, the cloud agent is instructed to build the actual Jekyll source and export affected rendered pages. The editor displays that private preview in a sandboxed iframe. A missing or failed build is not represented as a successful preview. The preview disables forms and outbound script requests; images may load from the public site. It is a review of selected rendered pages, not a separately deployed staging website or a live Vercel preview of editor-code changes.

Every proposal stays in the private draft repository. Review the complete set of file changes, then use **Publish these changes** to create one public commit and request a GitHub Pages build. The model has no publishing credentials. The server rejects stale reviews or changed public files rather than overwriting them. Files in a public repository are public even when their pages have `published: false`.

## Cloud execution, privacy, and limits

- GitHub sign-in is restricted server-side to your numeric account ID. All private operations require the configured private repository to remain private, non-forked, and owned by NateOConnellPhD. Mutations require same-origin requests and a CSRF token.
- Whole-project work uses the **OpenAI Agents API**, with an OpenAI-hosted sandbox, network access, and no subagents. The API key and GitHub token remain on the Vercel server, outside the sandbox. DNS and external-account settings are not controlled by this application.
- Public source, pending changes, conversation history, and an explicitly attached PDF are sent to OpenAI. Local private context folders, credentials, Git internals, caches, and generated build output are excluded. The agent can edit website code, configuration, workflows, the publication feed, scripts, and this editor; it is not restricted to content fields.
- Conversations and source proposals are saved under `chats/` in the private repository. Built preview bundles are saved there too. Git history retains earlier saved versions. A reference PDF is provided only to its cloud task, not copied into either GitHub repository or automatically replayed on follow-ups.
- Live replies use a filtered event stream, reconnecting within Vercel's function duration limit. The browser also retrieves saved assistant messages and checks task status every five seconds while visible. Stream interruption does not resubmit the user's message. Reopen the saved conversation or select **Check progress** after closing the browser or losing the connection. Only user-facing assistant output is forwarded; reasoning, tool arguments, credentials and raw events are excluded.
- The server imports source changes only from the completed main turn's exported result. It saves the final conversational answer and validated changes before requesting session deletion. If the task fails, available assistant text and the returned error code/session/turn IDs are saved before cleanup. **Error details** exposes those identifiers for diagnosis. Checking an already failed request retrieves its saved outcome; sending another message starts a fresh request with the prior conversation and proposed changes. Cleanup failures remain recorded and can be retried. Closing the browser does not cancel the task or confirm cleanup; use **Stop response** to request cancellation.
- The source exporter preserves existing executable files and rejects symlinks rather than following them. Publication retains unrelated repository files and never force-pushes history. Malformed returned changes do not replace earlier private proposals.
- API model and hosted-container usage is billed to the OpenAI organization behind the key. Available credits may cover it; this app does not establish credit eligibility. The daily request cap counts task starts and writing-assistant requests, including failed attempts. It is **not a dollar or token budget** for an agent task.
- Current transport limits are 800 text files / 1.5 MB of source, 500 KB per text file, 200 pending file changes, 1 MB per changed binary/upload, 1.6 MB of pending changes, 1.8 MB per conversation, and 80 messages. Reference PDFs are limited to 1.5 MB and must also fit the combined cloud request. Existing public assets may be larger: the bootstrap accepts up to 50 MB per asset and 150 MB total. Large existing assets can be deleted or viewed in the manual editor; moving/replacing one over 1 MB requires a different upload path. Limits fail explicitly; the editor does not silently omit oversized source.
- Built preview bundles contain at most 12 pages and 1.5 MB. Generated cloud build output is instructed to stay under 500 MB. These are application checks/instructions, not an operating-system disk quota.

The old single-document writing assistant uses Responses with `store: false`. Hosted-agent sessions use the Agents API session/artifact lifecycle instead; do not assume `store: false` applies to them. API data handling follows the organization's applicable policies. This editor does not save drafts in browser localStorage or a service-worker cache.

## Configure the existing deployment

If the previous editor already signs in, keep its existing Vercel project, private repository, GitHub App, and secrets.

1. Push the new source to the website repository. Vercel's editor project should deploy from `main`, with **Root Directory: website-editor**, **Framework: Other**, Node.js 24, and the checked-in `vercel.json`. The existing pinned `yaml@2.9.1` dependency installs during deployment. No SDK dependency was added for the cloud agent.
2. Keep `OPENAI_API_KEY` set in Vercel Production. A restricted API key must permit **Agents read/write** (`api.agents.read`, `api.agents.write`) and **Responses write** (`api.responses.write`). The organization must have access to the selected model and Agents API. Redeploy after changing environment variables.
3. Whole-project tasks default to `gpt-6-astra`. Set `OPENAI_AGENT_MODEL` if choosing a different supported Agents model. `OPENAI_MODEL` still controls only the individual-document writing assistant.
4. To publish changes under `.github/workflows/`, add **Workflows: Read and write** to the GitHub App's repository permissions and approve the updated installation permissions. Keep **Contents: Read and write**, **Pages: Read and write**, and **Metadata: Read-only**. Continue installing it only on the website and private draft repositories.
5. Run the connected review below before relying on the cloud workflow. Local mocked checks do not establish that the deployed API key, sandbox, Vercel routing, or GitHub permissions work.

For a fresh installation, create `NateOConnellPhD/nateoconnell-editor-private` as a private non-fork repository initialized with a README on `main`. Register a GitHub App, disable webhooks, leave user tokens expiring, and set:

- Homepage: `https://nateoconnellgithubio-website-editor.vercel.app`
- Redirect URI (also called Callback URL): `https://nateoconnellgithubio-website-editor.vercel.app/api/auth/callback`
- Wildcard redirect matching, Device Flow, and user authorization during installation: off. Setup URL: blank.
- Client secret: GitHub App **Credentials**. Client ID is shown on General. If GitHub requires a private key to install the app, generate one under Credentials and store it securely outside the repository. This editor uses the client secret and short-lived user token; it does not need that PEM or an installation ID uploaded to Vercel.

### Environment variables

| Variable | Value |
| --- | --- |
| `APP_ORIGIN` | `https://nateoconnellgithubio-website-editor.vercel.app`, without a trailing slash. |
| `GITHUB_CLIENT_ID` | GitHub App Client ID. |
| `GITHUB_CLIENT_SECRET` | GitHub App client secret from Credentials. |
| `ALLOWED_GITHUB_USER_ID` | Your numeric GitHub account ID, not an app ID or username. |
| `SESSION_SECRET` | 64 hex characters; generate with `openssl rand -hex 32`. Rotation signs out existing sessions. |
| `DRAFT_REPOSITORY` | `NateOConnellPhD/nateoconnell-editor-private`. |
| `OPENAI_API_KEY` | Server-only project key for the intended OpenAI organization. Manual editing does not require it. |
| `OPENAI_AGENT_MODEL` | Whole-project agent; defaults to `gpt-6-astra`. |
| `OPENAI_MODEL` | Individual-document assistant; defaults to `gpt-5.4-mini`. |
| `MAX_DAILY_AI_REQUESTS` | Defaults to 40; range 1–100. Shared request counter resets by UTC date. |

Keep secrets in Vercel environment variables. Do not expose them to the browser, source repository, or untrusted Vercel preview deployments.

## Connected review

1. Sign in through `/login` and check the organized project tree on desktop and your phone. Confirm another GitHub account is denied.
2. Ask which papers are highlighted. Verify your message appears immediately and the assistant's reply appears during the response, before any proposal is imported. Ask a follow-up referring to that answer, then request a changed selection. Inspect the proposed `featured`/`order` values and reopen the conversation. Confirm the source is still only in private storage.
3. Ask to add a temporary page, link it in navigation, and build a preview. Inspect the actual rendered page, check the reported build results, and verify the cloud task terminates and cleanup is confirmed. Discard the proposal without publishing.
4. Exercise an interrupted connection and a stopped task. Check the saved conversation recovers without starting duplicate model work.
5. Edit a source file directly, save, rename it, and discard. Try a non-sensitive image upload/paste on an actual phone; the implementation alone does not verify mobile clipboard support.
6. Only for an intentional public update, review and publish. Confirm the GitHub commit, Pages build, live page, and any Vercel redeployment separately. Publishing editor code changes may redeploy the editor itself.

The original private cross-validation blog draft has not been copied into this workspace or published by this change.

## Local validation

If a chat message was saved but the editor reported a failure immediately after sending, deploy the fix for empty event acknowledgements and reopen that conversation using **Check progress**. The Agents API accepts message and cancellation events with an empty HTTP 202 response, which must not be parsed as JSON. The saved session and idempotency key let the editor recover the original task without creating another session. Acceptance alone does not mean the task has completed. See the [event submission contract](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/events/methods/create).

Focused checks with mocked GitHub/OpenAI services:

```sh
node --test test/site-chat.test.js test/hosted-agent.test.js test/chat-stream.test.js
```

These JavaScript checks do not use credentials, call paid services, build the site, or produce disk output. They exercise project access boundaries, multi-file edits, private persistence, conflict detection, reviewed publication, cloud-task submission/recovery/cancellation, artifact selection, and cleanup. Run `python3 -B test/workspace_test.py` for the runtime exporter: it uses small isolated fixtures under the project's `.codex-tmp/`, mocks network downloads, and removes its fixtures afterward.

The existing YAML-dependent content checks require the pinned dependency. It was unavailable in the local sandbox during this change. No live Agents call, Jekyll build, browser/mobile review, or publication has been performed for this upgrade. Those remain connected validation, not passing local tests.

Local results, November 11, 2026: 18 mocked JavaScript checks and 4 bootstrap/exporter checks passed. Seven changed JavaScript modules parsed, referenced static HTML IDs were present, and the preview policy had no conflicting global CSP rule. Export-test fixtures were removed and their absence verified. No local dependency installation was performed.

The conversation update adds focused checks for live event delivery before completion, stream cancellation, message recovery, retaining failed-request details, ordinary questions with no source edits, and follow-up context. These checks use controlled service responses. A deployed conversation, browser/mobile behavior, and the cause of the previously reported cloud task failure have not been verified by these checks.

## Isolating a failed model connection

`scripts/check-agent.mjs` is an optional live diagnostic, never run by the editor or test suite. Run it explicitly with the same `OPENAI_API_KEY` and, if customized, `OPENAI_AGENT_MODEL` as Vercel. It makes one small billed model request without uploading the website or any conversation. It prints request/session/turn IDs and returned errors, then requests session deletion. It writes no local files and requires no downloaded packages.

The model check supplies initial input and streams the first turn in the creation request, as required for conversation-only sessions. It does not submit a second message. A creation rejection with HTTP 400, 401, or 403 needs no session lookup or cleanup; an uncertain creation still attempts recovery by diagnostic metadata before deletion.

For an authentication rejection, run `node scripts/check-agent.mjs --auth-only` from `website-editor/` first. This mode only reads `/v1/models` and `/v1/agents/sessions?limit=1`, reporting status, request IDs, and errors without printing account data. It never creates a session or runs a model. Models and Agents permissions are separate, so a failed models check alone does not establish that the key is invalid. Successful read access does not establish permission to create sessions or run inference.

The default has no sandbox. If that succeeds, `--hosted` checks an empty hosted sandbox without this website's package installs, assets, or preparation script; that check also incurs sandbox usage. A successful probe establishes only that specific path, not that the editor works. A failed cleanup is reported with the session ID; do not ignore it. Keep the API key out of chat and shell history.

## API references

- [OpenAI Agents sessions](https://developers.openai.com/api/docs/guides/agents-api/sessions), [hosted environments](https://developers.openai.com/api/docs/guides/agents-api/environments/openai-hosted), and [files/artifacts](https://developers.openai.com/api/docs/guides/agents-api/environments/files)
- [Agent-session listing and recovery metadata](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/methods/list)
- [Conversation events](https://developers.openai.com/api/docs/guides/agents-api/sessions/events), [saved conversation items](https://developers.openai.com/api/reference/resources/beta/subresources/agents/subresources/sessions/subresources/items/methods/list), and [failure details](https://developers.openai.com/api/docs/guides/agents-api/errors)
- [GitHub App user tokens and PKCE](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
- [Git tree updates](https://docs.github.com/en/rest/git/trees#create-a-tree) and [non-forced reference updates](https://docs.github.com/en/rest/git/refs#update-a-reference)
- [Vercel Node functions](https://vercel.com/docs/functions/runtimes/node-js)
