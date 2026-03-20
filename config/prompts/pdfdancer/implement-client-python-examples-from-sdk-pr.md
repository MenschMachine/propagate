Implement the Python examples changes required by the approved upstream work.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$API_PR_NUMBER" --repo MenschMachine/pdfdancer-api
fi
SDK_PR_NUMBER="$(propagate context get :client-python-pr-number --task implement-client-python | xargs)"
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-python --json title,body,url,headRefName,baseRefName
gh pr diff "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-python
```

If revising, also inspect `:review-check-results` and `:review-comments`.

Keep changes scoped to Python examples or sample applications that must reflect the approved client changes.
Run the examples you change and make sure they work.
Do not make changes to GitHub workflow files.

## Starting the API Server

Use the upstream API PR for the matching server image:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  API_PR_NUMBER="$(propagate context get :api-pr-number --task implement-pdfdancer-api | xargs)"
else
  API_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
fi
```

```shell
docker pull ghcr.io/menschmachine/pdfdancer-api:pr-${API_PR_NUMBER}
docker run \
    -e PDFDANCER_API_KEY_ENCRYPTION_SECRET="$(openssl rand -hex 16)" \
    -e FONTS_DIR=/tmp/fonts \
    -e METRICS_ENABLED=false \
    -e SWAGGER_ENABLED=true \
    -v /tmp/fonts:/home/app/fonts \
    --rm \
    -p 8080:8080 \
    ghcr.io/menschmachine/pdfdancer-api:pr-${API_PR_NUMBER}
```

If port `8080` is occupied, use another port and point the examples at that URL.
Prefer testing against this local docker instance instead of any cloud environment.
Use `PDFDANCER_API_TOKEN=42` when authenticating against the API.

## Using the Upstream SDK Version

Always use a virtual environment.
Use the exact upstream SDK PR head commit when testing example dependency wiring:

```bash
SDK_PR_NUMBER="$(propagate context get :client-python-pr-number --task implement-client-python | xargs)"
SDK_SHA="$(gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-python --json commits --jq '.commits[-1].oid')"
pip install git+https://github.com/MenschMachine/pdfdancer-client-python.git@${SDK_SHA}
```

If this repository uses `requirements.txt`, record the dependency like this:

```text
git+https://github.com/MenschMachine/pdfdancer-client-python.git@${SDK_SHA}
```
