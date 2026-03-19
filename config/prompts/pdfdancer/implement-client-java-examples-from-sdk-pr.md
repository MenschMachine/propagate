Implement the Java examples changes required by the approved upstream work.

Read:

```bash
BACKEND_PR_NUMBER="$(propagate context get :source-backend-pr-number --task triage-backend-pr | xargs)"
SDK_PR_NUMBER="$(propagate context get :client-java-pr-number --task implement-client-java | xargs)"
gh pr view "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend --json title,body,files,url,headRefName,baseRefName
gh pr diff "$BACKEND_PR_NUMBER" --repo MenschMachine/pdfdancer-backend
gh pr view "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-java --json title,body,url,headRefName,baseRefName
gh pr diff "$SDK_PR_NUMBER" --repo MenschMachine/pdfdancer-client-java
```

If revising, also inspect `:review-check-results` and `:review-comments`.

Keep changes scoped to Java examples or sample applications that must reflect the approved client changes.
