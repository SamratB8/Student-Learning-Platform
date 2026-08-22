# ADR 0003: Student AI Architecture

- Status: Accepted
- Date: 21 August 2026
- Decision basis: owner-approved AI decision after Phase 0
- Implementation phase: not Phase 1. This record exists so the seams are correct before anything is built.

## Context

Students want AI help with academic material. The platform must provide it without becoming dependent on a model provider, without leaking private data, and without pretending an LLM is a database.

Three different things were being conflated under the word "AI". They have different trust boundaries, different failure modes, and different audiences, so they are separated here.

## Decision

### 1. Quick AI (student-facing, on-device)

Optional lightweight assistance executed in the browser on the user's own device, gated by the device capability profile. Suitable tasks are summarization, explanation, note question answering, revision points, flashcards, and simple quiz generation. Google AI Edge / LiteRT-LM style runtimes are a future candidate; no runtime is selected here.

The website must not depend on Quick AI. If the device cannot run it, or the model fails to load, every academic feature continues to work and the affected control is simply absent or disabled with an honest explanation.

### 2. Continue in ChatGPT (student-facing, handoff)

The flow is:

1. The student selects a question or task.
2. The platform performs authorization first.
3. Retrieval returns only academic context the student is permitted to see.
4. Deterministic code assembles a structured context bundle with source markers `[S1]`, `[S2]`, and so on.
5. The internal AI utility may optionally refine that bundle. This step is skippable by definition.
6. The student previews the prepared prompt and initiates the handoff.
7. The platform copies the prompt to the clipboard and opens ChatGPT in a new tab.
8. The student pastes it into their own ChatGPT account, which produces the answer.

Source modes are `COLLEGE_ONLY`, `COLLEGE_AND_OFFICIAL`, and `COMPREHENSIVE`, matching the canonical note categories.

The platform must never use a student's ChatGPT account as an API, inject into another site's DOM, automate sending on ChatGPT, or accept a user-supplied provider key. There is no bring-your-own-key feature.

Source markers are preserved verbatim in the handoff prompt so the student can trace a claim back to a platform resource.

### 3. Internal AI utility (infrastructure only)

A server-side port, not reachable from any student-facing route and not callable by students. The initial intended adapter is the Gemini Developer API.

Permitted uses are query rewriting, semantic assistance, reranking, ambiguity resolution, context compression, prompt refinement, and content assistance where explicitly allowed.

## The non-negotiable rule

The internal AI utility **complements** deterministic code, rules, retrieval, indexing, and ordinary application logic. It **never replaces** them.

Order of preference:

```text
deterministic code and rules  ->  retrieval, indexing, RAG  ->  optional AI enhancement
```

If the provider fails, is unavailable, changes quota, is disabled, or is rate limited, then the site keeps working, retrieval keeps working, Continue in ChatGPT still produces a usable deterministically prepared prompt, and academic resources remain fully usable. Every call site must have a defined non-AI result, and that result must be correct rather than merely non-crashing.

Never use a model for a task ordinary code performs reliably, cheaply, and deterministically.

## Privacy boundary

The following must never be sent to any AI provider automatically: direct messages, Matrix message history, group chat plaintext, phone numbers, email addresses, user approval records, authentication or session data, OAuth tokens, Matrix keys, administrative or audit records, and unrelated personal information.

Authorization occurs before retrieval, and retrieval occurs before anything reaches an external provider. An authorization failure stops the flow; it never degrades into an unfiltered retrieval.

This ADR does not alter the existing rule that the ChatGPT draft receiver is one-way ingress that can only create drafts.

## Consequences

- Three separate seams are needed: a browser-side capability gate, a deterministic context-bundle builder, and a server-side AI port with an adapter. They must not collapse into one module.
- Every AI-touched code path needs a tested degraded path. "Provider unavailable" is a normal case, not an incident.
- Retrieval quality is the platform's responsibility. A weak index cannot be excused by a strong model.
- Removing all AI must leave a coherent product. This is an acceptance criterion, not an aspiration.

## Rejected alternatives

- A single unified AI service: rejected because it merges three different trust boundaries and encourages sending private data to a provider.
- Server-side generation of student answers: rejected because it makes the platform pay for and be responsible for every answer and creates a hard dependency on a provider.
- Bring your own key: rejected because it makes the platform handle user provider credentials for no product gain.
- Browser automation of ChatGPT: rejected because it violates another service's terms and is inherently fragile.
