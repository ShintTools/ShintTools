# ShintTools Core Scripts

Standalone tools for validation and testing. These run against a live Core instance.

## validate_agent.py

**Sprint C end-to-end validation**: tests `/agent/plan` and `/agent/review` SSE streaming against live Docker Core.

### Setup

```bash
# Install dependencies
pip install httpx requests

# Make executable (optional)
chmod +x validate_agent.py
```

### Usage

```bash
# Default: expects docker-compose.yml in current directory
python validate_agent.py

# Specify docker-compose location
python validate_agent.py --docker-compose-file ../docker-compose.yml

# Increase timeout for slow machines
python validate_agent.py --timeout 120
```

### What It Tests

1. **POST /agent/plan** — Plan endpoint with known C++ issues (nullptr, div-by-zero, sleep-in-tick)
   - Measures latency (baseline: <100ms)
   - Checks if plan found issues correctly

2. **POST /agent/review** — Review endpoint with SSE streaming
   - Measures latency (baseline: <10s)
   - Counts SSE events (thinking, tool_call, tool_result, done)
   - Captures final answer

3. **Latency check** — Validates performance against baselines

### Output

JSON report with:
- `summary`: pass/fail for each test + overall
- `plan`: issues found, timing, errors
- `review`: events received, timing, final answer preview
- `latencies`: measurements vs baselines

### Test Code

The script includes inline C++ with intentional issues:

```cpp
// CS001: GetWorld() can return nullptr
UWorld* World = GetWorld();
AActor* Result = World->SpawnActor<AActor>();

// CP005: Sleep in game thread
FPlatformProcess::Sleep(0.1f);

// CS004: Division by zero
int32 Divisor = 0;
int32 Result = 100 / Divisor;

// CP003: Large Tick body
void Tick() {
    for (int32 i = 0; i < 10000; ++i) { ... }
}
```

### Troubleshooting

- **"Core not ready"**: Check that Docker/MongoDB are running. Run `docker ps` to verify.
- **"/agent/plan returned 403"**: API key issue. The script uses empty key (uses default tier).
- **Timeout on /agent/review**: LLM model not loaded. Check that `core/models/*.gguf` exists.
- **SSE parsing errors**: Ensure the endpoint returns proper SSE format (`data: {...}\n\n`).
