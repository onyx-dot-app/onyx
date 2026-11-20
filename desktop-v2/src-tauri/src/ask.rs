//! Streams an answer for the launcher. Parses the NDJSON packet stream tolerantly:
//! unknown packet types are ignored so newer servers do not break older clients.

use std::collections::{BTreeMap, HashMap};
use std::time::Duration;

use futures_util::StreamExt;
use serde::Serialize;
use serde_json::Value;
use tauri::ipc::Channel;

use crate::api::{Api, AttachedFile};

/// The server's built-in default agent.
pub const DEFAULT_AGENT_ID: i64 = 0;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Citation {
    /// The number the answer text uses for this source, e.g. 3 for "[3]".
    pub number: u64,
    pub title: String,
    pub link: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum AskEvent {
    Session {
        #[serde(rename = "chatSessionId")]
        chat_session_id: String,
    },
    Delta {
        text: String,
    },
    /// What the answer is doing while no text streams (searching, reading).
    Status {
        text: String,
    },
    /// A new message after a tool step: the text so far was the agent's
    /// narration, not the answer, and the answer starts again with `text`.
    Restart {
        text: String,
    },
    Citations {
        docs: Vec<Citation>,
    },
    /// Approvals and questions continue in the Onyx window.
    NeedsInput {
        tool: Option<String>,
    },
    Done,
    /// The server surely did not take the question; an `Error` follows.
    NotSent,
    Error {
        message: String,
    },
}

#[derive(Default)]
struct StreamState {
    docs: HashMap<String, Citation>,
    cited: BTreeMap<u64, String>,
    finished: bool,
    stop_reason: Option<String>,
    approval_tool: Option<String>,
    /// Answer text has been sent since the last message started.
    has_text: bool,
}

fn status(text: impl Into<String>) -> Option<AskEvent> {
    Some(AskEvent::Status { text: text.into() })
}

impl StreamState {
    fn record_docs(&mut self, docs: Option<&Value>) {
        let Some(list) = docs.and_then(Value::as_array) else {
            return;
        };
        for doc in list {
            let (Some(id), Some(title)) = (
                doc.get("document_id").and_then(Value::as_str),
                doc.get("semantic_identifier").and_then(Value::as_str),
            ) else {
                continue;
            };
            let link = doc.get("link").and_then(Value::as_str).map(str::to_string);
            self.docs.insert(
                id.to_string(),
                Citation {
                    number: 0,
                    title: title.to_string(),
                    link,
                },
            );
        }
    }

    /// Consume the ACP notification received on the chat stream.
    fn apply(&mut self, line: &Value) -> Result<Option<AskEvent>, String> {
        let packet = match (line.get("jsonrpc"), line["method"].as_str()) {
            // Self-hosted servers predating protocol_version return v1 packets.
            (None, None) => line,
            (Some(version), method) if version == "2.0" => {
                let params = &line["params"];
                match method {
                    Some("session/update") => {
                        let update = &params["update"];
                        if update["sessionUpdate"] == "agent_message_chunk" {
                            return Ok(update["content"]["text"].as_str().map(|text| {
                                self.has_text |= !text.is_empty();
                                AskEvent::Delta {
                                    text: text.to_owned(),
                                }
                            }));
                        }
                        let obj = update
                            .get("rawOutput")
                            .filter(|value| value["type"].is_string())
                            .unwrap_or(&update["_meta"]["onyx"]["packet"]);
                        return Ok(self.apply_obj(obj));
                    }
                    Some(method) if method.starts_with("_onyx/") => &params["packet"],
                    _ => return Ok(None),
                }
            }
            _ => return Err("The server sent an invalid ACP chat notification.".into()),
        };
        if let Some(error) = packet["error"].as_str() {
            return Err(error.to_owned());
        }
        Ok(self.apply_obj(&packet["obj"]))
    }

    fn apply_obj(&mut self, obj: &Value) -> Option<AskEvent> {
        let content = || {
            obj.get("content")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_string()
        };
        match obj.get("type").and_then(Value::as_str) {
            Some("message_start") => {
                self.record_docs(obj.get("final_documents"));
                let text = content();
                if std::mem::replace(&mut self.has_text, !text.is_empty()) {
                    Some(AskEvent::Restart { text })
                } else {
                    (!text.is_empty()).then_some(AskEvent::Delta { text })
                }
            }
            Some("message_delta") => {
                let text = content();
                self.has_text |= !text.is_empty();
                Some(AskEvent::Delta { text })
            }
            Some("reasoning_start") => status("Thinking…"),
            Some("search_tool_start") => {
                if obj.get("is_internet_search").and_then(Value::as_bool) == Some(true) {
                    status("Searching the web…")
                } else {
                    status("Searching your company's knowledge…")
                }
            }
            Some("search_tool_documents_delta") => {
                let count = obj
                    .get("documents")
                    .and_then(Value::as_array)
                    .map_or(0, Vec::len);
                self.record_docs(obj.get("documents"));
                (count > 0).then(|| AskEvent::Status {
                    text: format!(
                        "Reading {count} source{}…",
                        if count == 1 { "" } else { "s" }
                    ),
                })
            }
            Some("open_url_start") => status("Opening pages…"),
            Some("file_reader_start") => status("Reading files…"),
            Some("python_tool_start") | Some("code_mode_start") => status("Running code…"),
            Some("image_generation_start") => status("Creating an image…"),
            Some("custom_tool_start") => obj
                .get("display_name")
                .and_then(Value::as_str)
                .and_then(|name| status(format!("Using {name}…"))),
            Some("citation_info") => {
                if let (Some(number), Some(id)) = (
                    obj.get("citation_number").and_then(Value::as_u64),
                    obj.get("document_id").and_then(Value::as_str),
                ) {
                    self.cited.insert(number, id.to_string());
                }
                None
            }
            Some("tool_approval_request") if obj["agent_name"].is_null() => {
                self.approval_tool = obj
                    .get("display_name")
                    .and_then(Value::as_str)
                    .map(str::to_string);
                None
            }
            Some("tool_approval_resolved" | "tool_question_request") => {
                self.approval_tool = None;
                None
            }
            Some("stop") => {
                self.finished = true;
                self.stop_reason = obj
                    .get("stop_reason")
                    .and_then(Value::as_str)
                    .map(str::to_string);
                None
            }
            _ => None,
        }
    }

    fn citations(&self) -> Vec<Citation> {
        self.cited
            .iter()
            .filter_map(|(number, id)| {
                self.docs.get(id).map(|doc| Citation {
                    number: *number,
                    ..doc.clone()
                })
            })
            .collect()
    }
}

/// Longest wait for the next chunk of an answer.
const STREAM_IDLE_TIMEOUT: Duration = Duration::from_secs(120);
/// Longest single packet; a stream without newlines must not grow without bound.
const MAX_RECORD_BYTES: usize = 4 * 1024 * 1024;

/// Applies one NDJSON record. Blank records are skipped; anything else must be
/// JSON (unknown packet types are still fine).
fn apply_record(
    record: &[u8],
    state: &mut StreamState,
    send: &dyn Fn(AskEvent),
) -> Result<(), String> {
    if record.iter().all(u8::is_ascii_whitespace) {
        return Ok(());
    }
    let value = serde_json::from_slice::<Value>(record)
        .map_err(|_| "The server sent an answer the app could not read.".to_string())?;
    if let Some(event) = state.apply(&value)? {
        send(event);
    }
    Ok(())
}

/// A stream that ends without the server's `stop` packet was cut off; its
/// text is not a finished answer.
fn stream_complete(state: &StreamState) -> Result<(), String> {
    if !state.finished {
        return Err("The answer stopped before it was complete.".into());
    }
    match state.stop_reason.as_deref() {
        Some("timed_out") => {
            Err("The server ran out of time before the answer was complete.".into())
        }
        Some("user_cancelled") => Err("The answer was stopped before it was complete.".into()),
        _ => Ok(()),
    }
}

/// Applies every complete line in `buffer` and keeps the unfinished tail.
fn drain_records(
    buffer: &mut Vec<u8>,
    state: &mut StreamState,
    send: &dyn Fn(AskEvent),
) -> Result<(), String> {
    let mut start = 0;
    while let Some(offset) = buffer[start..].iter().position(|b| *b == b'\n') {
        let end = start + offset;
        if end - start > MAX_RECORD_BYTES {
            return Err("The server sent an answer packet that is too large.".into());
        }
        apply_record(&buffer[start..end], state, send)?;
        start = end + 1;
    }
    buffer.drain(..start);
    if buffer.len() > MAX_RECORD_BYTES {
        return Err("The server sent an answer packet that is too large.".into());
    }
    Ok(())
}

pub struct Question<'a> {
    pub text: &'a str,
    /// The chat to continue with a follow-up; `None` starts a new chat.
    pub follow_up_of: Option<&'a str>,
    /// The agent of a new chat (`None`: the default agent). A follow-up keeps
    /// its chat's agent.
    pub agent_id: Option<i64>,
    pub files: &'a [AttachedFile],
}

pub async fn run(
    api: &Api,
    server: &str,
    token: &str,
    question: &Question<'_>,
    channel: &Channel<AskEvent>,
    // False once the session that started this answer has ended.
    is_current: &(dyn Fn() -> bool + Sync),
) -> Result<Answered, String> {
    let follow_up_of = question.follow_up_of;
    let session_id = match follow_up_of {
        Some(id) => id.to_string(),
        None => {
            let agent = question.agent_id.unwrap_or(DEFAULT_AGENT_ID);
            api.create_chat_session(server, token, agent).await?
        }
    };
    // A sign-out while the chat was being created must not send the question.
    if !is_current() {
        return Err("Signed out.".into());
    }
    let _ = channel.send(AskEvent::Session {
        chat_session_id: session_id.clone(),
    });

    let response = api
        .send_message(
            server,
            token,
            &session_id,
            question.text,
            follow_up_of.is_some(),
            question.files,
        )
        .await
        .map_err(|e| {
            if e.not_sent {
                let _ = channel.send(AskEvent::NotSent);
            }
            e.message
        })?;
    let mut stream = response.bytes_stream();
    let mut buffer: Vec<u8> = Vec::new();
    let mut state = StreamState::default();
    let send = |event: AskEvent| {
        let _ = channel.send(event);
    };

    loop {
        // An answer that is still streaming resets this; a server that stops
        // sending ends the request instead of leaving the launcher waiting.
        let next = tokio::time::timeout(STREAM_IDLE_TIMEOUT, stream.next())
            .await
            .map_err(|_| "The server stopped sending the answer.".to_string())?;
        if !is_current() {
            return Err("Signed out.".into());
        }
        let Some(chunk) = next else { break };
        let chunk = chunk.map_err(|e| format!("The answer stream broke: {e}"))?;
        buffer.extend_from_slice(&chunk);
        drain_records(&mut buffer, &mut state, &send)?;
    }
    apply_record(&buffer, &mut state, &send)?;
    stream_complete(&state)?;

    let citations = state.citations();
    if !citations.is_empty() {
        let _ = channel.send(AskEvent::Citations { docs: citations });
    }
    let awaiting_input = state.stop_reason.as_deref() == Some("awaiting_user");
    if awaiting_input {
        let _ = channel.send(AskEvent::NeedsInput {
            tool: state.approval_tool,
        });
    }
    log::info!("ask finished (stop packet: {})", state.finished);
    Ok(Answered { awaiting_input })
}

/// How an answer that streamed to the end stopped.
pub struct Answered {
    /// The answer needs a decision or a reply in the Onyx window.
    pub awaiting_input: bool,
}

#[cfg(test)]
mod tests {
    use super::{
        apply_record, drain_records, stream_complete, AskEvent, StreamState, MAX_RECORD_BYTES,
    };

    fn text_of(event: Option<AskEvent>) -> Option<String> {
        match event {
            Some(AskEvent::Delta { text }) => Some(text),
            _ => None,
        }
    }
    use serde_json::json;

    #[test]
    fn collects_text_and_citations() {
        let mut state = StreamState::default();
        let extension = |kind: &str, packet| json!({"jsonrpc":"2.0","method":format!("_onyx/{kind}"),"params":{"sessionId":"s","packet":packet}});
        let update = |body| json!({"jsonrpc":"2.0","method":"session/update","params":{"sessionId":"s","update":body}});
        let lines = [
            extension("message_id_info", json!({"user_message_id":1})),
            update(
                json!({"sessionUpdate":"tool_call_update","toolCallId":"search","rawOutput":{
                    "type":"search_tool_documents_delta","documents":[{"document_id":"d1","semantic_identifier":"Handbook","link":"https://x/1"}]
                }}),
            ),
            extension(
                "message_start",
                json!({"placement":{},"obj":{"type":"message_start","id":"m","content":"Hi"}}),
            ),
            update(
                json!({"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":" there"}}),
            ),
            extension(
                "citation_info",
                json!({"placement":{},"obj":{"type":"citation_info","citation_number":1,"document_id":"d1"}}),
            ),
            update(json!({"sessionUpdate":"unrecognized_update"})),
            extension("stop", json!({"placement":{},"obj":{"type":"stop"}})),
        ];
        let text: String = lines
            .iter()
            .filter_map(|line| text_of(state.apply(line).unwrap()))
            .collect();
        assert_eq!(text, "Hi there");
        assert!(state.finished);
        let citations = state.citations();
        assert_eq!(citations.len(), 1);
        assert_eq!(citations[0].title, "Handbook");
        assert_eq!(citations[0].number, 1);
    }

    #[test]
    fn reads_an_answer_from_a_server_returning_v1() {
        let mut state = StreamState::default();
        let raw =
            json!({"placement":{"turn_index":0},"obj":{"type":"message_delta","content":"Hi"}});
        assert_eq!(text_of(state.apply(&raw).unwrap()).as_deref(), Some("Hi"));
        let err = json!({"error":"Model unavailable"});
        assert_eq!(state.apply(&err).unwrap_err(), "Model unavailable");
    }

    #[test]
    fn reasoning_deltas_do_not_repeat_the_launcher_status() {
        let mut state = StreamState::default();
        let mut events = Vec::new();
        let frames = [
            json!({"jsonrpc":"2.0","method":"_onyx/reasoning_start","params":{"packet":{"obj":{"type":"reasoning_start"}}}}),
            json!({"jsonrpc":"2.0","method":"session/update","params":{"update":{"sessionUpdate":"agent_thought_chunk","content":{"type":"text","text":"part"}}}}),
        ];
        for frame in frames {
            events.extend(state.apply(&frame).unwrap());
        }
        assert!(matches!(events.as_slice(), [AskEvent::Status { text }] if text == "Thinking…"));
    }

    #[test]
    fn notes_a_stop_that_waits_for_approval() {
        let mut state = StreamState::default();
        let lines = [
            json!({"obj": {"type": "tool_approval_request", "approval_id": "a", "tool_call_id": "t",
                "tool_name": "send", "display_name": "Send email", "arguments": {}}}),
            json!({"obj": {"type": "stop", "stop_reason": "awaiting_user"}}),
        ];
        for line in &lines {
            state.apply(line).unwrap();
        }
        assert_eq!(state.stop_reason.as_deref(), Some("awaiting_user"));
        assert_eq!(state.approval_tool.as_deref(), Some("Send email"));
    }

    #[test]
    fn a_question_after_an_approval_waits_for_a_reply() {
        let mut state = StreamState::default();
        for obj in [
            json!({"type":"tool_approval_request","display_name":"Send email"}),
            json!({"type":"tool_approval_resolved"}),
            json!({"type":"tool_question_request"}),
            json!({"type":"stop","stop_reason":"awaiting_user"}),
        ] {
            state.apply(&json!({"obj":obj})).unwrap();
        }
        assert_eq!(state.stop_reason.as_deref(), Some("awaiting_user"));
        assert!(state.approval_tool.is_none());
    }

    #[test]
    fn reads_records_across_chunks_and_rejects_bad_ones() {
        let texts = std::cell::RefCell::new(String::new());
        let send = |e: AskEvent| {
            if let Some(t) = text_of(Some(e)) {
                texts.borrow_mut().push_str(&t);
            }
        };
        let mut state = StreamState::default();
        let mut buffer =
            b"{\"jsonrpc\":\"2.0\",\"method\":\"session/update\",\"params\":{\"sessionId\":\"s\",\"update\":{\"sessionUpdate\":\"agent_message_chunk\",\"content\":{\"type\":\"text\",\"text\":\"a\"}}}}\n\n{\"ty".to_vec();
        drain_records(&mut buffer, &mut state, &send).unwrap();
        assert_eq!(texts.borrow().as_str(), "a");
        assert!(apply_record(&buffer, &mut state, &send).is_err());
        assert!(apply_record(b"  \n", &mut state, &send).is_ok());

        let mut huge = vec![b'x'; MAX_RECORD_BYTES + 1];
        assert!(drain_records(&mut huge, &mut state, &send).is_err());
    }

    #[test]
    fn a_stream_without_stop_is_incomplete() {
        let mut state = StreamState::default();
        state
            .apply(&json!({"obj":{"type": "message_delta", "content": "Half"}}))
            .unwrap();
        assert!(stream_complete(&state).is_err());
        state.apply(&json!({"obj":{"type": "stop"}})).unwrap();
        assert!(stream_complete(&state).is_ok());
    }

    #[test]
    fn a_timed_out_stop_is_incomplete() {
        let mut state = StreamState::default();
        state
            .apply(&json!({"obj":{"type": "stop", "stop_reason": "timed_out"}}))
            .unwrap();
        assert!(stream_complete(&state).is_err());
    }

    #[test]
    fn narration_before_a_tool_step_is_not_part_of_the_answer() {
        let mut state = StreamState::default();
        let events: Vec<_> = [
            json!({"obj": {"type": "message_start", "content": "Retrying with a simpler query."}}),
            json!({"obj": {"type": "search_tool_start"}}),
            json!({"obj": {"type": "search_tool_documents_delta", "documents": [
                {"document_id": "d1", "semantic_identifier": "Handbook"}
            ]}}),
            json!({"obj": {"type": "message_start", "content": "I couldn't find"}}),
        ]
        .iter()
        .filter_map(|line| state.apply(line).unwrap())
        .collect();
        assert!(
            matches!(&events[0], AskEvent::Delta { text } if text == "Retrying with a simpler query.")
        );
        assert!(matches!(&events[1], AskEvent::Status { text } if text.starts_with("Searching")));
        assert!(matches!(&events[2], AskEvent::Status { text } if text == "Reading 1 source…"));
        assert!(matches!(&events[3], AskEvent::Restart { text } if text == "I couldn't find"));
    }

    #[test]
    fn surfaces_stream_errors() {
        let mut state = StreamState::default();
        assert_eq!(
            state
                .apply(&json!({
                    "jsonrpc": "2.0", "method": "_onyx/error",
                    "params": {"sessionId": "s", "packet": {"error": "no LLM configured"}}
                }))
                .unwrap_err(),
            "no LLM configured"
        );
    }
}
