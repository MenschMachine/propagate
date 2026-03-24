Implement the `pdfdancer-api-docs` changes required by this workflow.

Read:

```bash
SOURCE_REPOSITORY="$(propagate context get :signal.repository | xargs)"
if [[ "$SOURCE_REPOSITORY" == "MenschMachine/pdfdancer-backend" ]]; then
  SOURCE_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
else
  SOURCE_PR_NUMBER="$(propagate context get :source-api-pr-number --task triage-api-pr | xargs)"
  gh pr view "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api --json title,body,files,url,headRefName,baseRefName
  gh pr diff "$SOURCE_PR_NUMBER" --repo MenschMachine/pdfdancer-api
fi
propagate context get :api-pr-number --task implement-pdfdancer-api || true
propagate context get :client-typescript-examples-pr-number --task implement-client-typescript-examples || true
propagate context get :client-python-examples-pr-number --task implement-client-python-examples || true
propagate context get :client-java-examples-pr-number --task implement-client-java-examples || true
```

If those upstream PR numbers exist, treat the approved upstream PRs as the source of truth for what landed. If they do not exist, this is the docs-only branch and the source PR is the only upstream input.

Always inspect prior revision context before making changes:

```bash
propagate context get :revision-reason || true
propagate context get :review-findings || true
propagate context get :review-check-results || true
propagate context get :pr-comments || true
```

The `:pr-comments` value is a JSON object with `comments` (issue-style) and `review_comments` (line-specific diff comments).

Do not make changes to GitHub workflow files.

## Documentation Inputs

- Check the exact upstream SDK and examples PR heads for the feature set and usage patterns that actually landed in this workflow.
- Do not document speculative future behavior beyond what is present in the current upstream PRs.
- Pay attention to e2e tests and examples in the upstream repositories; they are the most concrete source for usage patterns.

## Guidelines

1. Document the new features in their sections. If a feature is big or important enough to deserve it's own page, create it.
2. Always update the version sdk-versions.md
3. Update the glossary if appropriate
4. Double check all code samples in this documention if they need to be updated

## SDK Dependency Reference

When documentation needs install or dependency examples, prefer exact upstream PR head commits:

```bash
TS_PR_NUMBER="$(propagate context get :client-typescript-pr-number --task implement-client-typescript || true)"
PY_PR_NUMBER="$(propagate context get :client-python-pr-number --task implement-client-python || true)"
JAVA_PR_NUMBER="$(propagate context get :client-java-pr-number --task implement-client-java || true)"
```

For Python, use:

```text
git+https://github.com/MenschMachine/pdfdancer-client-python.git@<SDK_SHA>
```

For TypeScript, use:

```shell
npm install github:MenschMachine/pdfdancer-client-typescript#<SDK_SHA>
```

For Java, use JitPack with the exact upstream commit:

```kotlin
implementation("com.pdfdancer.client:pdfdancer-client-java:<SDK_SHA>")
```
