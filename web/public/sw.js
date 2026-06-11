/**
 * Onyx Background Chat Service Worker
 *
 * Intercepts /api/chat/send-chat-message requests and processes them with
 * stream=false so the response completes even when the browser tab is
 * backgrounded (mobile sleep, app switch, tab switch).
 *
 * The SW converts ChatFullResponse to NDJSON lines matching the streaming
 * packet format so the page's existing handleSSEStream + useChatController
 * pipeline processes the result identically to a live streaming response.
 */

var CHAT_PATH = "/api/chat/send-chat-message";

self.addEventListener("install", function () {
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", function (event) {
  var url = new URL(event.request.url);

  if (!url.pathname.endsWith(CHAT_PATH)) return;
  if (event.request.method !== "POST") return;

  event.respondWith(handleChatRequest(event));
});

function handleChatRequest(event) {
  return event.request
    .clone()
    .json()
    .then(function (originalBody) {
      originalBody.stream = false;

      return fetch(event.request.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(originalBody),
      });
    })
    .then(function (httpResponse) {
      if (!httpResponse.ok) {
        return httpResponse;
      }
      return httpResponse.json().then(function (fullResponse) {
        var ndjsonLines = convertFullResponseToNDJSON(fullResponse);
        var ndjsonBody = ndjsonLines.join("\n") + "\n";

        return new Response(ndjsonBody, {
          status: 200,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Background-Processed": "true",
          },
        });
      });
    })
    .catch(function () {
      return fetch(event.request);
    });
}

/**
 * Convert ChatFullResponse to NDJSON lines matching the streaming packet
 * format the page's handleSSEStream / useChatController expects.
 *
 * Packet order:
 *   1. MessageResponseIDInfo  (user_message_id + reserved_assistant_message_id)
 *   2. Packet:MessageStart    (final_documents)
 *   3. Packet:MessageDelta    (answer text)
 *   4. Packet:CitationInfo    (one per citation)
 *   5. StreamingError         (if error_msg is set — MUST come before BackendMessage
 *                              because the loop checks Object.hasOwn("error") first)
 *   6. Packet:OverallStop     (stop_reason)
 *   7. BackendMessage         (citations map, tool_call, etc. — error is null here)
 */
function convertFullResponseToNDJSON(resp) {
  var lines = [];

  lines.push(
    JSON.stringify({
      user_message_id:
        resp.user_message_id != null ? resp.user_message_id : null,
      reserved_assistant_message_id: resp.message_id,
    })
  );

  var docs = resp.top_documents || [];
  lines.push(
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "message_start",
        id: "",
        content: "",
        final_documents: docs,
      },
    })
  );

  lines.push(
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "message_delta",
        content: resp.answer || "",
      },
    })
  );

  if (resp.citation_info) {
    for (var i = 0; i < resp.citation_info.length; i++) {
      var c = resp.citation_info[i];
      lines.push(
        JSON.stringify({
          placement: { turn_index: 0 },
          obj: {
            type: "citation_info",
            citation_number: c.citation_number,
            document_id: c.document_id,
          },
        })
      );
    }
  }

  var errorMsg = resp.error_msg;
  if (errorMsg) {
    lines.push(
      JSON.stringify({
        error: errorMsg,
        stack_trace: null,
        error_code: null,
        is_retryable: true,
      })
    );
  }

  lines.push(
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "stop",
        stop_reason: errorMsg ? "error" : "finished",
      },
    })
  );

  var citationsMap = buildCitationMap(resp.citation_info);

  var toolCalls = resp.tool_calls;
  var toolCall = null;
  if (toolCalls && toolCalls.length > 0) {
    toolCall = {
      tool_name: toolCalls[0].tool_name,
      tool_args: toolCalls[0].tool_arguments,
      tool_result: toolCalls[0].tool_result,
    };
  }

  lines.push(
    JSON.stringify({
      message_id: resp.message_id,
      message_type: "assistant",
      parent_message: null,
      latest_child_message: null,
      message: resp.answer || "",
      rephrased_query: null,
      context_docs: docs,
      time_sent: new Date().toISOString(),
      overridden_model: "",
      alternate_assistant_id: null,
      chat_session_id: resp.chat_session_id || "",
      citations: citationsMap,
      files: [],
      tool_call: toolCall,
      current_feedback: null,
      sub_questions: [],
      comments: null,
      parentMessageId: null,
      refined_answer_improvement: null,
      is_agentic: null,
      preferred_response_id: null,
      model_display_name: null,
      error: null,
    })
  );

  return lines;
}

function buildCitationMap(citationInfo) {
  if (!citationInfo) return {};
  var map = {};
  for (var i = 0; i < citationInfo.length; i++) {
    var c = citationInfo[i];
    map[c.citation_number] = c.document_id;
  }
  return map;
}
