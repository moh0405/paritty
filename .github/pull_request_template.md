## What and why

## Checklist
- [ ] Tests added or updated; `make test` is green locally
- [ ] `cd frontend && npx tsc --noEmit && npm run lint` is clean (if the UI changed)
- [ ] New migration? number is in my range; noted here so others run `make migrate` and `make golden`: 
- [ ] Deviation from the spec recorded in `docs/DECISIONS.md`
- [ ] No secrets, no real patient data, no arm data in prompts or blinded responses
- [ ] UI changes viewed in a browser (attach a screenshot), or say "not viewed"
