Set the configured provider key and run the benchmark file:

```bash
export OPENROUTER_KEY=...
uv run benchmark/run.py run benchmark/config.toml
```

Useful filters are `--profile`, `--suite`, `--case`, and `--repetitions`.

Add model variants by adding another `[[profiles]]` table. Add prompt variants
under `[[system_prompts]]`. Each prompt entry has a name and exactly one of
`txt` or `file`:

```toml
[[system_prompts]]
name = "strict"
file = "prompts/strict.txt"

[[system_prompts]]
name = "short"
txt = "You are a scheduling assistant."
```

Profiles select one by name. Trusted expected changes belong in a case's
`reference_actions`; complex expected states can instead use `reference_instance`.

Prompt paths are resolved relative to the benchmark TOML file. A profile must
set `system_prompt` to one of the declared prompt names.

The runner uses bounded defaults (`max_tool_rounds = 16`, a five-minute case
deadline, 30-second solver calls, and 60-second model requests). Override them
in `[run]` or use a profile-specific request timeout when a provider needs a
different limit.
