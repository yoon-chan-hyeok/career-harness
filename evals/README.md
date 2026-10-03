# Public functional regression fixture

`historical_cases.jsonl` contains eight manually authored **synthetic** Korean
cases. The historical filename remains for compatibility; the cases are not
the owner's chat history, application documents, confirmed achievements or
personal model quality evidence. `fixture_origin` and `source_id` explicitly
mark this provenance.

The original imported history is preserved locally under
`private_input/regression/historical_cases.original.jsonl`. It is excluded from
Git and deployment and is not automatically used by the runtime fixture.
Personal correction cases remain authenticated, owner-scoped application data.
Existing saved rule evaluations retain their original dataset hash; promotion
requires revalidation against the current fixture and current source versions.

The privacy gate checks Git-tracked **and untracked stage candidates**, public
fixture provenance, and Docker/Vercel exclusions. This complements manual
content review; it is not a universal personal-data detector.

Comparison and performance improvement experiments remain outside the user's
current scope. These cases only retain the existing functional regression
interfaces; no external model experiment is run by this change.
