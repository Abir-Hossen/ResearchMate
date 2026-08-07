# ResearchMate

## AI provider configuration

ResearchMate uses a settings-driven AI provider selection flow.

Set the provider with:

- `AI_PROVIDER=groq` for the real Groq-backed provider during local development
- `AI_PROVIDER=mock` for deterministic local testing or offline development

Example:

```env
AI_PROVIDER=groq
```

Use `mock` when you want the application to generate built-in mock learning responses without calling Groq.
