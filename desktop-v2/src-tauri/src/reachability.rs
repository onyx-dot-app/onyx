//! Why the server could not be reached, in a form both the offline window
//! and the launcher can show.

use std::error::Error as StdError;
use std::fmt;
use std::io::ErrorKind;

use reqwest::StatusCode;
use serde::Serialize;
use url::Url;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum Unreachable {
    NoNetwork,
    Dns,
    Tls,
    Timeout,
    /// Nothing listens on the server's port.
    Refused,
    /// The server answered with a 5xx status.
    ServerError {
        status: u16,
    },
    Unknown,
}

impl Unreachable {
    /// `None` for errors that are not about the connection (for example a body
    /// that does not decode).
    pub fn from_reqwest(error: &reqwest::Error) -> Option<Self> {
        if error.is_timeout() {
            return Some(Self::Timeout);
        }
        if !error.is_connect() && !error.is_request() {
            return None;
        }
        let mut source: Option<&(dyn StdError + 'static)> = error.source();
        let mut found = None;
        while let Some(cause) = source {
            if cause.downcast_ref::<native_tls::Error>().is_some() {
                return Some(Self::Tls);
            }
            if let Some(io) = cause.downcast_ref::<std::io::Error>() {
                match io.kind() {
                    ErrorKind::ConnectionRefused => found = found.or(Some(Self::Refused)),
                    ErrorKind::NetworkUnreachable
                    | ErrorKind::NetworkDown
                    | ErrorKind::HostUnreachable
                    | ErrorKind::AddrNotAvailable => found = found.or(Some(Self::NoNetwork)),
                    ErrorKind::TimedOut => found = found.or(Some(Self::Timeout)),
                    _ => {}
                }
            }
            // hyper-util's connect error type is private; its message names the step.
            let text = cause.to_string().to_ascii_lowercase();
            if text == "dns error" {
                found = found.or(Some(Self::Dns));
            } else if text.contains("certificate") {
                return Some(Self::Tls);
            }
            source = cause.source();
        }
        Some(found.unwrap_or(Self::Unknown))
    }

    /// A 5xx status means the server is up but cannot serve the app.
    pub fn from_status(status: StatusCode) -> Option<Self> {
        status.is_server_error().then_some(Self::ServerError {
            status: status.as_u16(),
        })
    }

    /// One line for the launcher and dialogs.
    pub fn message(&self, server: &str) -> String {
        let host = display_host(server);
        match self {
            Self::ServerError { status } => {
                format!("{host} has a problem (error {status}). Try again later.")
            }
            _ => format!("Can't reach {host}. Check your connection."),
        }
    }
}

impl fmt::Display for Unreachable {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::ServerError { status } => write!(f, "server error {status}"),
            other => write!(f, "{other:?}"),
        }
    }
}

/// The message for a failed request: the one-line text for a connection
/// error, otherwise the error itself.
pub fn describe(server: &str, error: &reqwest::Error) -> String {
    match Unreachable::from_reqwest(error) {
        Some(reason) => reason.message(server),
        None => error.to_string(),
    }
}

/// `host` or `host:port`, as people type it.
pub fn display_host(server: &str) -> String {
    let Ok(url) = Url::parse(server) else {
        return server.to_string();
    };
    match (url.host_str(), url.port()) {
        (Some(host), Some(port)) => format!("{host}:{port}"),
        (Some(host), None) => host.to_string(),
        _ => server.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::time::Duration;

    use super::{display_host, Unreachable};
    use crate::api::Api;

    /// A port that refuses connections. Tests bind only ephemeral ports
    /// (port 0), so no parallel test can take this one, as a freed port could.
    const CLOSED_PORT: u16 = 1;

    /// A one-shot server that answers the first request with `response`.
    fn serve_once(response: &'static [u8]) -> u16 {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            if let Ok((mut stream, _)) = listener.accept() {
                let mut buf = [0u8; 1024];
                let _ = stream.read(&mut buf);
                let _ = stream.write_all(response);
            }
        });
        port
    }

    fn get(url: &str, timeout: Duration) -> reqwest::Error {
        let client = reqwest::Client::builder().timeout(timeout).build().unwrap();
        // The request's timer needs the runtime, so the future is made inside it.
        tauri::async_runtime::block_on(async { client.get(url).send().await }).unwrap_err()
    }

    #[test]
    fn closed_port_is_refused() {
        let error = get(
            &format!("http://127.0.0.1:{CLOSED_PORT}/"),
            Duration::from_secs(5),
        );
        assert_eq!(
            Unreachable::from_reqwest(&error),
            Some(Unreachable::Refused)
        );
    }

    #[test]
    fn unknown_host_is_dns() {
        let error = get("http://onyx-desktop-test.invalid/", Duration::from_secs(10));
        assert_eq!(Unreachable::from_reqwest(&error), Some(Unreachable::Dns));
    }

    #[test]
    fn plain_http_on_https_is_tls() {
        let port = serve_once(b"HTTP/1.1 200 OK\r\ncontent-length: 0\r\n\r\n");
        let error = get(
            &format!("https://127.0.0.1:{port}/"),
            Duration::from_secs(5),
        );
        assert_eq!(Unreachable::from_reqwest(&error), Some(Unreachable::Tls));
    }

    #[test]
    fn silent_server_is_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let error = get(
            &format!("http://127.0.0.1:{port}/"),
            Duration::from_millis(300),
        );
        drop(listener);
        assert_eq!(
            Unreachable::from_reqwest(&error),
            Some(Unreachable::Timeout)
        );
    }

    #[test]
    fn health_reports_refused_and_server_errors() {
        let api = Api::new();
        let down = format!("http://127.0.0.1:{CLOSED_PORT}");
        assert_eq!(
            tauri::async_runtime::block_on(api.health(&down)),
            Err(Unreachable::Refused)
        );
        let port = serve_once(b"HTTP/1.1 503 Service Unavailable\r\ncontent-length: 0\r\n\r\n");
        let failing = format!("http://127.0.0.1:{port}");
        assert_eq!(
            tauri::async_runtime::block_on(api.health(&failing)),
            Err(Unreachable::ServerError { status: 503 })
        );
    }

    #[test]
    fn only_5xx_statuses_are_unreachable() {
        use reqwest::StatusCode;
        for status in [
            StatusCode::OK,
            StatusCode::TEMPORARY_REDIRECT,
            StatusCode::UNAUTHORIZED,
            StatusCode::NOT_FOUND,
        ] {
            assert_eq!(Unreachable::from_status(status), None, "{status}");
        }
        assert_eq!(
            Unreachable::from_status(StatusCode::BAD_GATEWAY),
            Some(Unreachable::ServerError { status: 502 })
        );
    }

    #[test]
    fn messages_name_the_host() {
        assert_eq!(
            Unreachable::Refused.message("http://localhost:3000"),
            "Can't reach localhost:3000. Check your connection."
        );
        assert_eq!(display_host("https://cloud.onyx.app"), "cloud.onyx.app");
        assert_eq!(
            serde_json::to_value(Unreachable::ServerError { status: 502 }).unwrap(),
            serde_json::json!({ "kind": "serverError", "status": 502 })
        );
    }
}
