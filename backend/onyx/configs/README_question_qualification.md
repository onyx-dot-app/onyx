# Question Qualification System

The Question Qualification System allows you to automatically block certain types of questions and return standard responses instead of processing them through the LLM. This is useful for:

- 🔒 **Privacy Protection**: Block requests for personal information
- 🛡️ **Security**: Prevent inappropriate or malicious queries  
- 📋 **Compliance**: Ensure questions stay within allowed topics
- ⚡ **Performance**: Fast responses without LLM processing
- 🔄 **Embedding Caching**: Automatic caching for ultra-fast startup

## How It Works

1. **Embedding-Based Matching**: Uses the same embedding model as your search system
2. **Similarity Threshold**: Configurable sensitivity (0.0 to 1.0)
3. **Standard Response**: Single response for all blocked questions
4. **Universal Coverage**: Works across all assistants and search methods
5. **Smart Caching**: Embeddings are generated once and cached in the config file

## ⚡ Embedding Caching

The system automatically caches embeddings to make startup **much faster**:

- ✅ **First Run**: Generates embeddings for all questions (slower)
- ✅ **Subsequent Runs**: Uses cached embeddings (instant startup)
- ✅ **Auto-Detection**: Only generates embeddings for new questions
- ✅ **Model Changes**: Automatically regenerates if embedding model changes
- ✅ **Backup Safety**: Creates backup before updating config file

## Configuration

### Environment Variable Control

The question qualification system is controlled by a single environment variable:

**`ENABLE_QUESTION_QUALIFICATION`** - Master control switch

```bash
# Enable question qualification
export ENABLE_QUESTION_QUALIFICATION=true

# Disable question qualification (default)
export ENABLE_QUESTION_QUALIFICATION=false
# or simply don't set the variable
```

### Configuration File

Edit `backend/onyx/configs/question_qualification.yaml`:

```yaml
# Global settings
settings:
  similarity_threshold: 0.85  # How similar to trigger (0.0-1.0)
  standard_response: "I'm sorry, but I cannot provide information on that topic."

# List of blocked questions with cached embeddings
blocked_questions:
  - question: "What is someone's salary?"
    embedding: null  # Auto-generated and cached
  - question: "How do I hack into systems?"
    embedding: [0.1, 0.2, 0.3, ...]  # Cached embedding vector
  # Add more questions here...

# Metadata (auto-managed)
metadata:
  last_embedding_model: "nomic-ai/nomic-embed-text-v1" 
  last_updated: "2024-12-19T15:30:00"
  total_questions: 142
```

### Settings Explained

- **Environment Variable**: `ENABLE_QUESTION_QUALIFICATION` (master control)
  - `true` = Enable the system (must be explicitly set)
  - `false` or unset = Disable the system (default)
- **similarity_threshold**: 
  - `0.95+` = Very strict (only very similar questions blocked)
  - `0.85` = Balanced (recommended)  
  - `0.70` = Permissive (catches more variations)
- **standard_response**: The message users see when questions are blocked

**Note**: Only the environment variable controls whether the system is enabled.

### Caching Details

- **embedding**: `null` = needs generation, `[...]` = cached vector
- **metadata.last_embedding_model**: Tracks which model generated embeddings
- **metadata.last_updated**: When embeddings were last generated
- **metadata.total_questions**: Total count for verification

## Adding Blocked Questions

### Method 1: Edit Config File (Recommended)
```yaml
blocked_questions:
  - question: "Your new blocked question here"
    embedding: null  # Will be auto-generated on next startup
```

### Method 2: Programmatic Addition
```python
from onyx.server.query_and_chat.question_qualification import get_question_qualification_service

service = get_question_qualification_service()
service.add_blocked_question("What is the CEO's personal email?")
```

The system will:
1. ✅ Generate embedding automatically
2. ✅ Save to config file with backup
3. ✅ Use immediately for blocking
4. ✅ Cache for future use

### Tips for Good Blocked Questions

- **Be specific but natural**: "What is John's salary?" not "salary"
- **Use representative examples**: Include common phrasings
- **Test variations**: The system catches similar questions, not just exact matches
- **Start with essentials**: Add the most important blocks first

## Testing

Run the comprehensive test script:

```bash
cd backend
python onyx/server/query_and_chat/question_qualification_test.py
```

This will test:
- ✅ Question classification (blocked vs allowed)
- ✅ Embedding caching performance  
- ✅ Adding new questions dynamically
- ✅ Config reload functionality
- ✅ Performance metrics

Sample output:
```
🔍 Question Qualification Test
📊 Total questions: 142
🔗 Cached embeddings: 142
🎯 Similarity threshold: 0.85
🤖 Embedding model: nomic-ai/nomic-embed-text-v1
🕒 Last updated: 2024-12-19T15:30:00

🚀 Average check time: 2.1ms (10 tests)
🔥 Questions per second: 476.2
```

## Integration

The system automatically integrates with:
- ✅ All chat endpoints (`/chat/send-message`)
- ✅ All assistants (no configuration needed)
- ✅ All search methods
- ✅ Web interface and API

When a question is blocked:
1. 🚫 LLM processing is skipped
2. 📝 Standard response is returned immediately  
3. 📊 Similarity score is logged
4. ⚡ Ultra-fast response time (~2ms)

## Deployment

1. **Edit Config**: Update `question_qualification.yaml` with your blocked questions
2. **Set Threshold**: Adjust `similarity_threshold` based on your needs
3. **Enable System**: Set `enabled: true`
4. **First Restart**: Service generates and caches all embeddings (slower)
5. **Subsequent Restarts**: Service uses cached embeddings (fast)
6. **Test**: Use the test script to verify behavior

### Performance Expectations

| Scenario | Startup Time | Check Time |
|----------|-------------|------------|
| **First run** (no cache) | ~30-60s | ~2-5ms |
| **Cached** (normal) | ~1-3s | ~1-3ms |
| **New questions added** | ~5-15s | ~1-3ms |

## Monitoring

Check logs for blocked questions:

```bash
grep "Question blocked" logs/onyx.log
```

Look for entries like:
```
Question blocked - similarity: 0.891, threshold: 0.85, matched: 'What is someone's salary?'
Generated and cached 5 new embeddings
All embeddings are up to date, using cached versions
```

## Troubleshooting

**System not working?**
- ✅ Check `enabled: true` in config
- ✅ Verify config file path exists
- ✅ Ensure embedding model is running
- ✅ Check logs for errors
- ✅ Try deleting `.backup` files if corruption

**Slow startup?**
- ✅ Check if embeddings are cached (`embedding: [...]` vs `embedding: null`)
- ✅ Look for "using cached versions" in logs
- ✅ Verify embedding model hasn't changed

**Too many questions blocked?**
- 🔧 Increase `similarity_threshold` (e.g., 0.80 → 0.90)
- 🔧 Remove overly broad blocked questions
- 🔧 Use more specific blocked questions

**Not catching variations?**
- 🔧 Add more example blocked questions
- 🔧 Decrease `similarity_threshold` (e.g., 0.90 → 0.80)
- 🔧 Test with the test script

**Cache issues?**
- 🔧 Delete embeddings: set all `embedding: null` and restart
- 🔧 Check embedding model consistency in metadata
- 🔧 Look for backup files (`*.backup`) if config corrupted

## Advanced Usage

### Statistics and Monitoring
```python
service = get_question_qualification_service()
stats = service.get_stats()
print(f"Cache hit rate: {stats['cached_embeddings']}/{stats['total_questions']}")
```

### Programmatic Management
```python
# Add multiple questions
questions = ["What's the budget?", "Show me contracts", "Who got fired?"]
for q in questions:
    service.add_blocked_question(q)

# Force reload
service.reload_config()

# Get detailed stats
stats = service.get_stats()
```

### Batch Updates
When adding many questions:
1. Edit config file with `embedding: null` for all new questions
2. Restart service once (generates all embeddings in batch)
3. Future startups will be fast with cached embeddings

## Security Note

This system provides a first line of defense but should not be the only security measure. Always implement proper access controls and monitoring for sensitive data.

## Performance Tips

- 🚀 **Use caching**: Let the system cache embeddings automatically
- 🚀 **Batch additions**: Add multiple questions at once, restart once
- 🚀 **Monitor logs**: Watch for cache hits vs misses
- 🚀 **Test regularly**: Use the test script to verify performance 