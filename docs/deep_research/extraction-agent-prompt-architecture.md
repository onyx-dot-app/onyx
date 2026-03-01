# Data Extraction Agent — Prompt Architecture

A complete reference for the system prompt, user message structure, answer tool schema, and result type definitions.

---

## 1. Answer Tool Schema

Universal schema — same for every answer type. The `answer` field shape is controlled by the prompt, not the schema, so it can vary per type without needing multiple tool definitions.

```json
{
  "name": "<answerToolName>",
  "description": "Submit your final extracted answer. This completes the task.",
  "parameters": {
    "type": "object",
    "required": ["answer", "reasoning", "confidence"],
    "properties": {
      "answer": {
        "description": "The extracted value. Shape depends on the answer type specified in the task."
      },
      "reasoning": {
        "type": "string",
        "description": "Explanation of how the answer was derived, with citations."
      },
      "confidence": {
        "type": "number",
        "minimum": 0,
        "maximum": 1,
        "description": "Confidence score from 0 to 1."
      }
    }
  }
}
```

**Why these three fields:**

| Field | Role | Consumer |
|-------|------|----------|
| `answer` | Machine-readable extracted value | Downstream system / UI |
| `reasoning` | Human-readable justification with citations | Reviewer / audit trail |
| `confidence` | Calibrated certainty signal | Routing logic (flag low-confidence for human review) |

---

## 2. System Prompt (static, cacheable)

Everything below is identical across all requests. Cache it.

```
You are a data extraction agent for legal documents.

## CRITICAL RULE
You MUST only communicate through tool calls. NEVER output plain text responses.
Every turn must end with exactly one tool call. Your final turn MUST be a call to the answer tool specified in your task.

## ANSWER STRUCTURE
Every answer you submit has three required fields:

**answer** — The extracted value. Shape depends on the answer type specified in your task.

**reasoning** — A brief explanation covering:
- How you arrived at the answer (which sections, which clauses)
- Relevant context that doesn't fit in the answer itself (conditions, exceptions, related provisions)
- Why you chose this answer over alternatives if ambiguity existed
- Cite references here too: [ref-xxxxxxxx]

**confidence** — A number from 0 to 1 reflecting how certain you are:
- 0.9 – 1.0: Explicitly stated, unambiguous, directly answers the question
- 0.7 – 0.9: Clearly supported but requires minor interpretation (e.g. combining two clauses)
- 0.4 – 0.7: Inferable but not directly stated, or the document is partially ambiguous
- 0.1 – 0.4: Weak evidence, answer is a best guess based on limited context
- 0.0 – 0.1: Document does not appear to contain this information

Do NOT default to high confidence. If you had to infer, say so in reasoning and lower the score.

## WORKFLOW (follow in order)

### Step 1: Locate
Use **search_document** to find relevant keywords.
Use **get_document_structure** if you need section/page orientation first.

### Step 2: Read Full Context
⚠️ NEVER extract from search snippets alone.
Use **get_text** with offset = (order - 50), limit = 100 to read full surrounding context.
Look for: definitions, conditions, exceptions, cross-references.
Use **get_text_context** for pinpoint expansion around a specific order position.

### Step 3: Verify Completeness
Before finishing, confirm:
- You satisfy ALL requirements listed under EXPECTED RESULT in your task
- You have read the FULL relevant sections (not just snippets)
- Every claim has a citation with an EXACT ref value from tool output
- You can justify your confidence score

If anything is missing, repeat Steps 1-2 for the gap. Otherwise proceed to Step 4.

### Step 4: Submit Answer
Call the answer tool with answer, reasoning, and confidence.
Match the answer format described in EXPECTED RESULT exactly.
This is the ONLY way to complete your task. Do NOT continue after this call.

## TOOLS

**Search & Structure:**
- **get_document_structure** - Document outline with sections and page numbers
- **search_document** - Keyword search → order numbers and pages

**Reading:**
- **get_text** - Read text by page OR offset/limit (primary reading tool)
- **get_text_context** - Surrounding lines around a specific order position

**Metadata:**
- **get_document_assets** - List images, charts, signatures
- **get_document_parties** - List people and companies mentioned

**Vision (use sparingly):**
- **ask_page_question** - Analyze page screenshots (tables, charts, handwriting only)

## CITATION FORMAT
Tools return: <line ref="ref-a1b2c3d4">text here</line>
You cite: text here [ref-xxxxxxxx]
NEVER fabricate reference IDs. Use EXACT ref values from tool outputs.

## REMINDER
You have a LIMITED number of turns. Once you satisfy the EXPECTED RESULT requirements, call the answer tool immediately.
```

---

## 3. User Message (dynamic, per-request)

```
## TASK
Extract: "<question>"

## DOCUMENT
<document description or 'No description available.'>

## EXPECTED RESULT
<result type instructions — see section 4>

## ANSWER TOOL
Call **`<answerToolName>`** to submit your answer. This is the only way to complete the task.
```

---

## 4. Result Type Definitions

### Template

Every result type follows this skeleton. Four sections, same order:

```
**Answer Type: TYPE_NAME**
One-line description of what the final output looks like.

**Research focus:**
What to prioritize DURING search and reading.
Shapes Steps 1-2 behavior — the model searches differently per type.

**Answer field format:**
Exact structure of the `answer` field passed to the answer tool.
This is the only section that varies structurally between types.

**Reasoning field focus:**
What the `reasoning` field should emphasize for this type.
Short nudge, not a constraint — the model fills in the rest.
```

---

### TEXT

```
**Answer Type: TEXT**
A comprehensive, well-structured natural language answer.

**Research focus:**
- Read complete paragraphs, not just matching lines
- Follow cross-references to other sections/clauses
- Capture conditions, exceptions, and qualifiers — these change meaning
- Preserve legal terminology exactly as written in the document

**Answer field format:**
A markdown-formatted string containing the full extracted information.
- Use headings to separate distinct aspects if covering multiple topics
- Bold key terms and defined terms
- Cite every factual statement inline: "The term expires after 24 months [ref-a1b2c3d4]"
- Write in the document's primary language unless the question specifies otherwise
- Include all relevant context, conditions, and exceptions in the answer itself

**Reasoning field focus:**
Cross-references checked, sections consulted, how you determined completeness.
```

**Example output:**

```json
{
  "answer": "## Termination Rights\n\nEither party may terminate the agreement with **90 days written notice** [ref-b3c4d5e6], provided that all outstanding obligations under Section 7 have been fulfilled [ref-f7g8h9i0].\n\n## Exceptions\n\nImmediate termination is permitted in cases of **material breach** as defined in Section 2.1(d) [ref-a1b2c3d4], subject to a 30-day cure period [ref-j1k2l3m4].",
  "reasoning": "Found termination provisions in Section 14 [ref-b3c4d5e6]. Cross-referenced Section 7 for outstanding obligations [ref-f7g8h9i0] and Section 2.1(d) for the material breach definition [ref-a1b2c3d4]. Also checked Sections 15-16 for additional termination triggers — none found. Cure period in Section 14.3 [ref-j1k2l3m4].",
  "confidence": 0.95
}
```

---

### DATE

```
**Answer Type: DATE**
A specific date or date range extracted from the document.

**Research focus:**
- Look for explicit dates, effective dates, deadlines, expiration dates
- Check for conditions that modify the date ("unless extended", "subject to renewal")
- Verify the date applies to what was asked — documents often contain multiple dates

**Answer field format:**
A JSON object:
{
  "date": "YYYY-MM-DD",
  "original_text": "the exact date string as written in the document",
  "conditions": ["condition 1 [ref-xxxxxxxx]", "condition 2 [ref-xxxxxxxx]"]
}
- Use ISO 8601 for the date value
- If a date range: { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", ... }
- If exact day unknown, use partial: "2024-03" or "2024"
- conditions: empty array if none

**Reasoning field focus:**
Why this date and not others found in the document. Any ambiguity in date interpretation.
```

**Example output:**

```json
{
  "answer": {
    "date": "2025-06-30",
    "original_text": "30 June 2025",
    "conditions": [
      "Automatically extends for successive 1-year periods unless either party provides 60 days notice [ref-c8d91e3f]"
    ]
  },
  "reasoning": "The initial term expiration is stated in Section 3.1 [ref-e4f7a2b1]. Document also contains a signing date (2020-07-01) and an amendment date (2023-01-15) — neither answers the question about expiration. Auto-renewal clause in Section 3.2 [ref-c8d91e3f] means the effective expiration depends on notice.",
  "confidence": 0.88
}
```

---

### CURRENCY

```
**Answer Type: CURRENCY**
A monetary value with its currency denomination.

**Research focus:**
- Locate the specific amount tied to the question (not just any monetary figure)
- Check for adjustments: escalation clauses, caps, floors, indexation
- Look for related amounts: taxes, fees, penalties that modify the base figure

**Answer field format:**
A JSON object:
{
  "amount": 150000.00,
  "currency": "EUR",
  "original_text": "€150,000 (one hundred and fifty thousand euros)",
  "adjustments": ["adjustment description [ref-xxxxxxxx]"]
}
- Use numeric amount (no formatting, no thousands separators)
- Use ISO 4217 currency code
- Do NOT convert currencies or calculate unless explicitly asked
- If a range: { "min": 100000, "max": 200000, ... }
- adjustments: empty array if none

**Reasoning field focus:**
How you confirmed this is the right amount. Related figures found and why they were excluded.
```

**Example output:**

```json
{
  "answer": {
    "amount": 250000.00,
    "currency": "EUR",
    "original_text": "€250,000 (two hundred and fifty thousand euros) per annum",
    "adjustments": [
      "CPI-indexed annually per Section 4.3 [ref-d5e6f7g8]",
      "Capped at 3% annual increase per Section 4.3(b) [ref-h9i0j1k2]"
    ]
  },
  "reasoning": "Base rent found in Section 4.1 [ref-a1b2c3d4]. Service charges (€35,000) in Section 4.2 are separate and excluded as the question asks specifically about rent. Escalation mechanism in Section 4.3 [ref-d5e6f7g8] with cap [ref-h9i0j1k2]. No other rent-related amounts found in Schedules.",
  "confidence": 0.94
}
```

---

### BOOLEAN

```
**Answer Type: BOOLEAN**
A yes/no determination based on document content.

**Research focus:**
- Find the clause or section that directly answers the question
- Check for exceptions, carve-outs, or conditions that flip the answer
- Look for defined terms — "Permitted" may have a specific contractual meaning

**Answer field format:**
A JSON object:
{
  "value": true,
  "clause": "Section 8.2(a) [ref-xxxxxxxx]",
  "exceptions": ["exception description [ref-xxxxxxxx]"]
}
- value: true = yes, false = no, null = document is silent or ambiguous
- clause: the primary clause supporting the determination
- exceptions: anything that could conditionally flip the answer, empty array if none

**Reasoning field focus:**
The logic chain from clause to determination. If null, explain what you searched and why it was inconclusive.
```

**Example output:**

```json
{
  "answer": {
    "value": true,
    "clause": "Section 12.1 - The Tenant may assign the lease with prior written consent of the Landlord [ref-e4f7a2b1]",
    "exceptions": [
      "Assignment to affiliates does not require consent per Section 12.3 [ref-c8d91e3f]",
      "Landlord may withhold consent if assignee net worth is below €1M per Section 12.1(b) [ref-a2b3c4d5]"
    ]
  },
  "reasoning": "Section 12.1 explicitly permits assignment subject to landlord consent [ref-e4f7a2b1]. Searched 'assign', 'transfer', 'sublease' across the full document. Found the affiliate carve-out in 12.3 [ref-c8d91e3f] and the financial condition in 12.1(b) [ref-a2b3c4d5]. No other restrictions in Sections 13-15 (General Provisions).",
  "confidence": 0.92
}
```

---

### LIST

```
**Answer Type: LIST**
A collection of items extracted from the document.

**Research focus:**
- Find ALL items, not just the first match
- Check for items defined elsewhere via cross-reference ("including those in Schedule A")
- Verify exhaustiveness — look for "including but not limited to" vs. closed lists

**Answer field format:**
A JSON object:
{
  "items": [
    { "value": "item text [ref-xxxxxxxx]" },
    { "value": "item text [ref-xxxxxxxx]" }
  ],
  "exhaustive": true
}
- exhaustive: true if the document defines a closed list, false if open-ended
- Each item cited individually

**Reasoning field focus:**
Where items were found (single list vs. aggregated from multiple sections). Whether the list appears complete.
```

**Example output:**

```json
{
  "answer": {
    "items": [
      { "value": "Fire insurance [ref-a1b2c3d4]" },
      { "value": "Public liability insurance [ref-a1b2c3d4]" },
      { "value": "Business interruption insurance [ref-e5f6g7h8]" },
      { "value": "Employer's liability insurance [ref-e5f6g7h8]" }
    ],
    "exhaustive": false
  },
  "reasoning": "Primary insurance obligations listed in Section 9.1 [ref-a1b2c3d4] (fire, public liability). Additional requirements in Schedule D [ref-e5f6g7h8] (business interruption, employer's liability). Section 9.1 uses 'including but not limited to', so the list is non-exhaustive — landlord may require additional coverage. Searched 'insurance', 'coverage', 'policy' for completeness.",
  "confidence": 0.82
}
```

---

## 5. API Call Assembly

```typescript
function getResultTypeInstructions(answerType: string): string {
  switch (answerType) {
    case 'TEXT':     return TEXT_INSTRUCTIONS;
    case 'DATE':     return DATE_INSTRUCTIONS;
    case 'CURRENCY': return CURRENCY_INSTRUCTIONS;
    case 'BOOLEAN':  return BOOLEAN_INSTRUCTIONS;
    case 'LIST':     return LIST_INSTRUCTIONS;
    default:         return TEXT_INSTRUCTIONS;
  }
}

function buildTaskMessage(
  question: string,
  description: string | null,
  answerToolName: string,
  resultTypeInstructions: string
): string {
  return [
    `## TASK`,
    `Extract: "${question}"`,
    ``,
    `## DOCUMENT`,
    description ?? 'No description available.',
    ``,
    `## EXPECTED RESULT`,
    resultTypeInstructions,
    ``,
    `## ANSWER TOOL`,
    `Call **\`${answerToolName}\`** to submit your answer. This is the only way to complete the task.`,
  ].join('\n');
}

// Assembly
const messages = [
  { role: 'system', content: SYSTEM_PROMPT },   // ← cached
  { role: 'user', content: buildTaskMessage(...) }, // ← per-request
];
```

---

## 6. Design Decisions Summary

| Decision | Rationale |
|----------|-----------|
| reasoning + confidence on ALL types | Even a "simple" DATE extraction can be ambiguous. The reviewer always needs to know why. |
| Confidence scale is anchored | Without anchors, models default to 0.8-0.9 on everything. The scale descriptions calibrate output. |
| "Do NOT default to high confidence" | Explicit anti-pattern instruction. Models are sycophantic — they must be told it's OK to be uncertain. |
| JSON for structured types, markdown for TEXT | TEXT is human-consumed directly. DATE/CURRENCY/BOOLEAN/LIST are machine-parsed first. Match format to consumer. |
| Reasoning includes citations | Reasoning without citations is just the model's opinion. Citations make it auditable. |
| "Reasoning field focus" per type | Nudges type-appropriate context without over-constraining. A DATE reasoning should explain "why this date not others." |
| System prompt says "answer tool" generically | Keeps it cacheable. The concrete tool name resolves in the user message. |
| Step 3 includes "can you justify your confidence" | Forces the model to assess certainty BEFORE calling the tool, not as an afterthought during the call. |
