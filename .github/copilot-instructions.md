# Copilot Instructions: Git Commit Message Guidelines

## Purpose

Write clear, consistent, and meaningful Git commit messages that explain **what changed and why**. Commit messages serve as long-term documentation for the codebase and should help future developers understand decisions quickly.

---

## Core Principles

* **Write for future readers**
  Assume the reader has no context. Explain the intent behind the change, not just the change itself. ([Phoenix Portfolio][1])

* **Be clear and concise**
  Keep messages short but descriptive. Avoid vague wording like “fix stuff.” ([Phoenix Portfolio][1])

* **Focus on why, not just what**
  The code diff shows what changed—your message should explain why it changed. ([Phoenix Portfolio][1])

* **One commit = one logical change**
  Do not mix unrelated changes in a single commit. ([Phoenix Portfolio][1])

---

## Commit Message Structure

Follow a three-part structure:

```
<subject>

<body>

<footer>
```

### 1. Subject Line (Required)

* Keep under **50 characters** (max 72)
* Use **imperative mood** (e.g., “add”, “fix”, “remove”)
* Describe what the commit does

✅ Examples:

```
add caching for API responses
fix null pointer in data loader
remove deprecated functions
```

---

### 2. Body (Optional)

* Explain **why** the change was made
* Provide context, reasoning, or trade-offs
* Wrap text at ~72 characters
* Separate from subject with a blank line

---

### 3. Footer (Optional)

* Reference issues, tickets, or breaking changes
* Example:

```
BREAKING CHANGE: API now requires authentication token
Refs: #123
```

---

## Conventional Commits Format (Recommended)

Use structured prefixes for consistency:

```
type(scope): description
```

### Common Types

* `feat` → New feature
* `fix` → Bug fix
* `docs` → Documentation changes
* `refactor` → Code restructuring
* `test` → Adding or updating tests
* `chore` → Maintenance tasks

### Examples

```
feat(api): add batch prediction endpoint
fix(auth): handle token expiration edge case
docs(readme): add installation guide
refactor(data): extract validation logic
```

---

## Best Practices

* Keep commits **small and focused**
* Use meaningful, descriptive language
* Reference related issues when applicable
* Ensure messages are readable in `git log --oneline`
* Clean up commit history before merging (e.g., squash WIP commits)

---

## What to Avoid

❌ Vague messages:

```
fix bug
update code
```

❌ Work-in-progress commits:

```
WIP
temp fix
```

❌ Mixing unrelated changes in one commit

❌ Overly long or unclear subject lines

---

## Quick Checklist

Before committing, ensure:

* [ ] Subject is clear and under 50 characters
* [ ] Uses imperative mood
* [ ] Explains **what + why**
* [ ] Contains only one logical change
* [ ] No vague or placeholder text

---

## Summary

A good commit message:

* Is **clear, concise, and descriptive**
* Explains **intent and reasoning**
* Follows a **consistent structure**
* Helps others understand the codebase without reading diffs

Investing a few extra seconds in writing a good commit message saves hours of confusion later. ([datacamp.com][2])

[1]: https://fynix.dev/blog/git-commit-message-guide?utm_source=chatgpt.com "Complete Git Commit Message Guide | Phoenix."
[2]: https://www.datacamp.com/tutorial/git-commit-message?utm_source=chatgpt.com "Git Commit Message: The Rules, Examples, and Conventions | DataCamp"
