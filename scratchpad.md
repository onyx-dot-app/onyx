Instructions: Please investigate the codebase (for the user file feature especially) to answer the questions in the scratchpad please. Write down your insights and check each question one by one as they are fully and concisely answered please. I have repeated the instructions in the scratchpad so you don't forget

Questions
[✓] How are the tokens for documents counted

- Tokens are counted using the default LLM's tokenizer when a file is uploaded
- In `backend/onyx/db/user_documents.py`, the `create_user_files` function:
  - Gets the default LLM and its tokenizer
  - Reads the file content and counts tokens with `token_count = len(llm_tokenizer.encode(content))`
  - Stores this count in the `token_count` field of the `UserFile` model
- Total token counts for files/folders are calculated with `calculate_user_files_token_count` function
- This is used for tracking usage and ensuring documents don't exceed LLM token limits

[✓] How are documents indexed, these uploaded docs should be prioritized

- User-uploaded documents are indexed with high priority through `create_user_file_with_indexing` function
- After creating file records, it triggers immediate high-priority indexing via `trigger_indexing_for_cc_pair`
- This function in `backend/onyx/server/documents/connector.py` sends a high-priority task to Celery:
  ```python
  primary_app.send_task(
      OnyxCeleryTask.CHECK_FOR_INDEXING,
      priority=OnyxCeleryPriority.HIGH,
      kwargs={"tenant_id": tenant_id},
  )
  ```
- The priority is set to `HIGH` (value 1), which is the second highest in the priority enum
- This ensures user uploads are indexed quickly and made available for search sooner
- The actual indexing uses Vespa as the search backend via the `VespaIndex` class

[✓] How to make indexing have even higher priority

- ✅ IMPLEMENTED: Changed user file indexing to use `OnyxCeleryPriority.HIGHEST` (value 0) instead of HIGH
- Modified the `trigger_indexing_for_cc_pair` function in `backend/onyx/server/documents/connector.py`:
  - Added an `is_user_file` parameter (default to False)
  - Updated the priority based on this parameter:
    ```python
    priority = OnyxCeleryPriority.HIGHEST if is_user_file else OnyxCeleryPriority.HIGH
    primary_app.send_task(
        OnyxCeleryTask.CHECK_FOR_INDEXING,
        priority=priority,
        kwargs={"tenant_id": tenant_id},
    )
    ```
- Updated the call in `create_user_file_with_indexing` to pass `is_user_file=True`
- Also updated the `create_file_from_link` function to trigger indexing with highest priority
- These changes ensure user file indexing always takes precedence over other indexing tasks
- User files will now be indexed as soon as possible, ahead of any other indexing tasks
