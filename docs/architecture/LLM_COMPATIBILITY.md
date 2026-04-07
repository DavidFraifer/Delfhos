# LLM Compatibility & Local Model Support (v0.6.1+)

Delfhos works with **any LLM** via unified provider support and OpenAI-compatible endpoints.

## Supported Providers

### Cloud Providers (Native Support)

```python
from delfhos import Agent

# Google Gemini
agent = Agent(tools=[...], llm="gemini-2.5-flash")

# OpenAI (GPT)
agent = Agent(tools=[...], llm="gpt-4o")

# Anthropic (Claude)
agent = Agent(tools=[...], llm="claude-4-6-sonnet")
```

**Environment Variables:**
- `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) for Gemini
- `OPENAI_API_KEY` for OpenAI models
- `ANTHROPIC_API_KEY` for Claude

### Local & Custom Endpoints (OpenAI-Compatible)

Use `LLMConfig` for **any OpenAI-compatible endpoint**. This enables:

- **Local models** (Ollama, LM Studio)
- **Enterprise servers** (vLLM, TGI)
- **Third-party APIs** (Groq, Together, Anyscale, local Anthropic servers, etc.)

```python
from delfhos import Agent, LLMConfig

# Local Ollama
agent = Agent(
    tools=[...],
    llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")
)

# Enterprise vLLM
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="mistral-7b-instruct",
        base_url="https://llm.corp.internal/v1",
        api_key="bearer-token-here"
    )
)

# Groq (third-party OpenAI-compatible)
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk_..."
    )
)

# Together AI (open-source model inference)
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="meta-llama/Llama-3-70b-chat-hf",
        base_url="https://api.together.xyz/v1",
        api_key="..."
    )
)
```

## When to Use Local vs Cloud

### Use Local (Ollama, LM Studio)
- **Cost:** No API costs (runs on your machine)
- **Latency:** Often faster (no network roundtrip)
- **Privacy:** Data stays on your machine
- **Setup:** 1-2 commands to start server
- **Best for:** Development, testing, simple tasks

### Use Cloud (Gemini, OpenAI, Anthropic)
- **Performance:** Strongest open models available
- **Scaling:** Auto-scale to any load
- **Availability:** 99.9% uptime SLAs
- **Best for:** Production agents, complex reasoning

### Use Enterprise (vLLM, TGI)
- **Cost:** Amortized across team
- **Control:** Runs in your infrastructure
- **Compliance:** Meet regulatory requirements
- **Performance:** Fine-tuned for your use cases
- **Best for:** Regulated industries, high-volume deployments

---

## Dual-LLM Optimization (New in v0.6.1)

Split fast prefiltering from heavy code generation to optimize cost and latency:

```python
from delfhos import Agent, LLMConfig

agent = Agent(
    tools=[...],
    light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
    heavy_llm="gemini-2.5-flash",
)
```

**Execution:**
1. **Prefilter (light_llm):** 7B local model → selects relevant tools (fast, free)
2. **Code generation (heavy_llm):** Cloud model → writes optimized code (accurate, 1-2 API calls per task)

**Cost savings:** ~80% reduction in cloud API tokens while maintaining accuracy.

---

## OpenAI-Compatible Endpoint Guide

### Ollama (Local, Free)

```bash
# Start Ollama locally
ollama serve
ollama pull llama3.2

# In Delfhos
from delfhos import Agent, LLMConfig

agent = Agent(
    tools=[...],
    llm=LLMConfig(model="llama3.2", base_url="http://localhost:11434/v1")
)
```

### LM Studio (GUI, Free)

Start LM Studio → Load model → Server is ready at `http://localhost:1234/v1`

```python
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="lmstudio-community/Meta-Llama-3-8B-Instruct-GGUF",
        base_url="http://localhost:1234/v1"
    )
)
```

### vLLM (Enterprise, Fastest)

```bash
python -m vLLM.entrypoints.openai_api_server \
  --model mistral-7b-instruct \
  --tensor-parallel-size 4 \
  --host 0.0.0.0 \
  --port 8000
```

```python
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="mistral-7b-instruct",
        base_url="http://localhost:8000/v1"
    )
)
```

### Groq (Fastest Inference API)

```python
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="llama-3.3-70b-versatile",
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk_..."  # Get from groq.com
    )
)
```

### Local Anthropic Server

Run Anthropic's model locally (if available):

```python
agent = Agent(
    tools=[...],
    llm=LLMConfig(
        model="claude-3.5-sonnet",
        base_url="http://localhost:8000/v1",
        api_key="local"  # Can be any string for local servers
    )
)
```

---

## Model Recommendations

### For Development (Cost-Optimized)

```python
# Fast, cheap local prefilter + accurate cloud generation
agent = Agent(
    tools=[...],
    light_llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1"),
    heavy_llm="gemini-3.1-flash-lite-preview",
)
```

### For Production (Balanced)

```python
# Dual cloud LLMs for reliability and speed
agent = Agent(
    tools=[...],
    light_llm="gemini-3.1-flash-lite-preview",
    heavy_llm="gemini-2.5-flash",
)
```

### For Private Deployment (On-Prem)

```python
# Both models run in your infrastructure
agent = Agent(
    tools=[...],
    light_llm=LLMConfig(
        model="qwen2.5:7b",
        base_url="https://llm-internal.corp/v1",
        api_key="internal-token"
    ),
    heavy_llm=LLMConfig(
        model="mistral-7b-instruct",
        base_url="https://llm-internal.corp/v1",
        api_key="internal-token"
    ),
)
```

---

## Configuration

### Via Environment Variables

```bash
# Cloud provider APIs
export GOOGLE_API_KEY="AIzaSy..."
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Custom endpoints (optional)
export OPENAI_BASE_URL="http://localhost:11434/v1"
export OPENAI_API_KEY="local"  # for local servers
```

### Via LLMConfig (Recommended)

Explicitly pass credentials to avoid env var pollution:

```python
llm = LLMConfig(
    model="llama3.2",
    base_url="http://localhost:11434/v1",
    api_key="local"  # Optional for local servers
)
```

---

## Model Compatibility Matrix

| Model | Type | Speed | Quality | Cost | Delfhos Support |
|-------|------|-------|---------|------|---|
| gemini-2.5-flash | Cloud | ⚡⚡⚡ | ⭐⭐⭐⭐ | $ | ✓ Native |
| gpt-4o | Cloud | ⚡⚡ | ⭐⭐⭐⭐⭐ | $$ | ✓ Native |
| claude-4.6-sonnet | Cloud | ⚡⚡ | ⭐⭐⭐⭐⭐ | $$ | ✓ Native |
| llama-3.3-70b (Groq) | Cloud API | ⚡⚡⚡ | ⭐⭐⭐⭐ | $$ | ✓ LLMConfig |
| mistral-7b (vLLM) | Enterprise | ⚡⚡⚡ | ⭐⭐⭐ | Free | ✓ LLMConfig |
| qwen2.5:7b (Ollama) | Local | ⚡⚡⚡ | ⭐⭐⭐ | Free | ✓ LLMConfig |
| llama3.2 (Ollama) | Local | ⚡⚡⚡ | ⭐⭐⭐ | Free | ✓ LLMConfig |

---

## Troubleshooting

### "Connection refused to http://localhost:11434/v1"

Make sure the local server is running:
```bash
ollama serve  # for Ollama
# or
npm run dev  # for LM Studio
```

### "Invalid API key"

Check your environment variable:
```bash
echo $GOOGLE_API_KEY  # should not be empty
# or pass explicitly
llm=LLMConfig(model="...", api_key="sk-...")
```

### Model not found

Make sure the model is downloaded locally:
```bash
ollama pull llama3.2  # Download if not present
```

### Rate limited on cloud API

Use a local backup:
```python
agent = Agent(
    tools=[...],
    llm=LLMConfig(model="qwen2.5:7b", base_url="http://localhost:11434/v1")
)
```

---

## Summary

Delfhos supports **any LLM** via OpenAI-compatible endpoints. Use cloud providers for production, local models for cost-optimized development, and enterprise servers for regulated deployments.

**Key capabilities:**
- ✓ Native support for Gemini, OpenAI, Anthropic
- ✓ LLMConfig for any OpenAI-compatible endpoint
- ✓ Dual-LLM optimization (fast prefilter + accurate generation)
- ✓ Environment variable or explicit configuration
- ✓ Easy switching between cloud and local models
