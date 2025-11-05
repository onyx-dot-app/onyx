# Question Qualification System

The Question Qualification System allows you to automatically block certain types of questions and return standard responses instead of processing them through the LLM. This is useful for:

- 🔒 **Privacy Protection**: Block requests for personal information
- 🛡️ **Security**: Prevent inappropriate or malicious queries  
- 📋 **Compliance**: Ensure questions stay within allowed topics
- ⚡ **Performance**: Fast responses without full LLM processing

## How It Works

1. **LLM-Based Semantic Matching**: Uses a fast LLM to evaluate semantic similarity between user questions and blocked questions
2. **Confidence Threshold**: Configurable sensitivity (0.0 to 1.0) - questions are blocked if the LLM's confidence score meets or exceeds the threshold
3. **Standard Response**: Single response for all blocked questions
4. **Universal Coverage**: Works across all assistants and search methods
5. **Real-Time Evaluation**: Questions are evaluated in real-time without caching

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

**Note**: The system is disabled by default. You must explicitly set `ENABLE_QUESTION_QUALIFICATION=true` to enable it.

### Configuration File

Edit `backend/onyx/configs/question_qualification.yaml`:

```yaml
# Settings for the question qualification system.
# Note: The system is controlled by the ENABLE_QUESTION_QUALIFICATION environment variable.
# Set ENABLE_QUESTION_QUALIFICATION=true to enable the system.
settings:
  # The similarity threshold for blocking a question.
  # A higher value means the user's question needs to be more similar to a blocked question to be caught.
  # A lower value will catch a wider range of questions, but may have more false positives.
  threshold: 0.85
  # The standard response to show the user when their question is blocked.
  standard_response: "I am sorry, but I cannot answer this question."

# A list of questions that should be blocked by the system.
# The system uses LLM-based semantic matching to compare user questions against this list.
# Questions are evaluated in real-time using the configured LLM without caching.
questions:
  - question: "What is someone's salary?"
  - question: "How do I hack into systems?"
  # Add more questions here...
```

### Settings Explained

- **Environment Variable**: `ENABLE_QUESTION_QUALIFICATION` (master control)
  - `true` = Enable the system (must be explicitly set)
  - `false` or unset = Disable the system (default)
- **threshold**: 
  - `0.95+` = Very strict (only very similar questions blocked)
  - `0.85` = Balanced (recommended)  
  - `0.70` = Permissive (catches more variations)
- **standard_response**: The message users see when questions are blocked

**Note**: Only the environment variable controls whether the system is enabled. The config file settings are only used when the system is enabled.

## Adding Blocked Questions

Edit the `question_qualification.yaml` file directly:

```yaml
questions:
  - question: "Your new blocked question here"
```

The system will use the new questions immediately after the next server restart (if enabled).

## Integration

The system automatically integrates with:
- ✅ All chat endpoints (`/chat/send-message`)
- ✅ All assistants (no configuration needed)
- ✅ All search methods
- ✅ Web interface and API

When a question is blocked:
1. 🚫 LLM processing is skipped
2. 📝 Standard response is returned immediately  
3. 📊 Confidence score is logged
4. ⚡ Fast response time

## Deployment

1. **Edit Config**: Update `question_qualification.yaml` with your blocked questions
2. **Set Threshold**: Adjust `threshold` based on your needs
3. **Enable System**: Set `ENABLE_QUESTION_QUALIFICATION=true` environment variable
4. **Restart**: Restart the service to load the configuration
5. **Test**: Send test questions to verify behavior

## Monitoring

Check logs for blocked questions:

```bash
grep "Question blocked" logs/onyx.log
```

Look for entries like:
```
Question qualification: blocked=True, confidence=0.891, threshold=0.85
Question blocked by LLM analysis: confidence 0.891 >= 0.85
```

## Troubleshooting

**System not working?**
- ✅ Check `ENABLE_QUESTION_QUALIFICATION=true` environment variable is set
- ✅ Verify config file path exists
- ✅ Ensure LLM is configured and accessible
- ✅ Check logs for errors

**Too many questions blocked?**
- 🔧 Increase `threshold` (e.g., 0.80 → 0.90)
- 🔧 Remove overly broad blocked questions
- 🔧 Use more specific blocked questions

**Not catching variations?**
- 🔧 Add more example blocked questions
- 🔧 Decrease `threshold` (e.g., 0.90 → 0.80)
- 🔧 Test with different question phrasings

## Security Note

This system provides a first line of defense but should not be the only security measure. Always implement proper access controls and monitoring for sensitive data.
