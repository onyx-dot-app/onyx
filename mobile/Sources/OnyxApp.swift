import SwiftUI
import WebKit

let onyxURL = URL(string: "https://cloud.onyx.app")!

@main
struct OnyxApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
                .preferredColorScheme(nil)
        }
    }
}

struct ContentView: View {
    @StateObject private var model = WebViewModel()

    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            WebView(model: model)

            if model.isLoading && !model.didFirstLoad {
                ProgressView().scaleEffect(1.3)
            }

            if model.failed {
                VStack(spacing: 16) {
                    Image(systemName: "wifi.slash")
                        .font(.system(size: 44))
                        .foregroundStyle(.secondary)
                    Text("Can't reach Onyx")
                        .font(.headline)
                    Text("Check your connection and try again.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Button("Retry") { model.reload() }
                        .buttonStyle(.borderedProminent)
                }
                .padding()
            }

            if model.isAdminPage {
                AdminDesktopNotice(model: model)
            }
        }
    }
}

// Admin pages are desktop-first; on mobile we surface a notice instead of a
// broken layout. Mobile targets the end-user chat experience.
struct AdminDesktopNotice: View {
    @ObservedObject var model: WebViewModel

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "desktopcomputer")
                .font(.system(size: 52))
                .foregroundStyle(.secondary)
            Text("Best viewed on desktop")
                .font(.title3.weight(.semibold))
            Text("Admin settings aren't optimized for mobile yet. Open Onyx in a web browser to manage them.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            VStack(spacing: 12) {
                Button {
                    model.openInBrowser()
                } label: {
                    Text("Open in browser").frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                Button("Back to chat") { model.goToChat() }
            }
            .padding(.top, 4)
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
    }
}

final class WebViewModel: ObservableObject {
    @Published var isLoading = true
    @Published var failed = false
    @Published var didFirstLoad = false
    @Published var isAdminPage = false
    @Published var currentURL: URL = onyxURL
    weak var webView: WKWebView?

    func reload() {
        failed = false
        isLoading = true
        webView?.load(URLRequest(url: currentURL))
    }

    func goToChat() {
        webView?.load(URLRequest(url: URL(string: "/chat", relativeTo: onyxURL)!.absoluteURL))
    }

    func openInBrowser() {
        UIApplication.shared.open(currentURL)
    }
}

struct WebView: UIViewRepresentable {
    @ObservedObject var model: WebViewModel

    func makeCoordinator() -> Coordinator { Coordinator(model: model) }

    // Onyx Cloud's web UI is desktop-first. Inject mobile CSS so dialogs/settings
    // (Radix `[role="dialog"]`) scroll instead of clipping on short viewports.
    // Persists across SPA route changes because the <style> tag stays in <head>.
    // Safe-area insets are handled in SwiftUI (the web view stays within the safe area).
    private static func makeMobileContentController() -> WKUserContentController {
        let ucc = WKUserContentController()
        let cssLiteral = jsStringLiteral(loadMobileCSS())
        let js = """
        (function(){
          var id='onyx-ios-mobile-css';
          var existing=document.getElementById(id);
          var s=existing||document.createElement('style');
          s.id=id;
          s.textContent=\(cssLiteral);
          if(!existing)(document.head||document.documentElement).appendChild(s);

          // Wrap any table wider than the screen in a horizontal-scroll div so
          // dense admin tables (Users, Existing Connectors) are swipeable instead
          // of clipped. A <table> with an explicit pixel width can't scroll itself.
          function wrapTables(){
            document.querySelectorAll('table').forEach(function(t){
              var p=t.parentElement;
              if(!p || p.dataset.onyxScroll) return;
              if(t.scrollWidth > (window.innerWidth||9999)+2){
                var w=document.createElement('div');
                w.dataset.onyxScroll='1';
                p.insertBefore(w,t);
                w.appendChild(t);
              }
            });
          }
          wrapTables();
          var scheduled=false;
          var obs=new MutationObserver(function(){
            if(scheduled) return; scheduled=true;
            setTimeout(function(){ scheduled=false; wrapTables(); },600);
          });
          obs.observe(document.body,{childList:true,subtree:true});
        })();
        """
        ucc.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentEnd, forMainFrameOnly: true))

        // Start the nav/admin sidebar collapsed on phones. The web app reads the
        // `sidebarIsToggled` cookie on mount ("true" = collapsed); set it before any
        // app script runs so the drawer doesn't open over content on first load.
        // Only set when unset, so it never overrides a deliberate user toggle.
        let cookieJS = """
        (function(){
          try{
            if(!/(^|;\\s*)sidebarIsToggled=/.test(document.cookie)){
              document.cookie='sidebarIsToggled=true; path=/';
              try{localStorage.setItem('sidebarIsToggled','true');}catch(e){}
            }
          }catch(e){}
        })();
        """
        ucc.addUserScript(WKUserScript(source: cookieJS, injectionTime: .atDocumentStart, forMainFrameOnly: true))

        // Report client-side route changes to native (the SPA doesn't trigger
        // WKNavigationDelegate on in-app nav) so we can show the desktop notice
        // when the user opens an /admin page.
        let navJS = """
        (function(){
          function report(){try{window.webkit.messageHandlers.onyxNav.postMessage(location.href);}catch(e){}}
          var push=history.pushState, rep=history.replaceState;
          history.pushState=function(){var r=push.apply(this,arguments);report();return r;};
          history.replaceState=function(){var r=rep.apply(this,arguments);report();return r;};
          window.addEventListener('popstate',report);
          document.addEventListener('DOMContentLoaded',report);
          report();
        })();
        """
        ucc.addUserScript(WKUserScript(source: navJS, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        return ucc
    }

    // Dev-only: jump straight to a surface for QA, e.g.
    // `SIMCTL_CHILD_ONYX_PATH=/admin/users xcrun simctl launch booted app.onyx.ios`
    // (simctl strips the SIMCTL_CHILD_ prefix, so the app reads ONYX_PATH).
    // Only a relative path is honored so it can never point the authenticated
    // session at a different origin. Falls back to the app root.
    private static func startURL() -> URL {
        if let path = ProcessInfo.processInfo.environment["ONYX_PATH"],
           path.hasPrefix("/"),
           let url = URL(string: path, relativeTo: onyxURL) {
            return url.absoluteURL
        }
        return onyxURL
    }

    private static func loadMobileCSS() -> String {
        guard let url = Bundle.main.url(forResource: "mobile", withExtension: "css"),
              let css = try? String(contentsOf: url, encoding: .utf8) else { return "" }
        return css
    }

    // Encode an arbitrary string as a valid JS string literal (quoted + escaped)
    // so it can be embedded in injected script without breaking on quotes,
    // backticks, backslashes, or newlines.
    private static func jsStringLiteral(_ s: String) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: [s]),
              let json = String(data: data, encoding: .utf8) else { return "\"\"" }
        return String(json.dropFirst().dropLast())
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.websiteDataStore = .default()
        config.userContentController = Self.makeMobileContentController()
        config.userContentController.add(context.coordinator, name: "onyxNav")

        let webView = WKWebView(frame: .zero, configuration: config)
        // Google OAuth ("Use secure browsers") returns 403 disallowed_useragent for default
        // WKWebView UAs. Present a real mobile Safari UA so SSO completes inside the app.
        webView.customUserAgent = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        model.webView = webView
        webView.load(URLRequest(url: Self.startURL()))
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {
        // Block the web view's edge-swipe back gesture while the admin notice
        // covers it, so the user can't navigate the hidden page behind the overlay.
        uiView.allowsBackForwardNavigationGestures = !model.isAdminPage
    }

    static func dismantleUIView(_ uiView: WKWebView, coordinator: Coordinator) {
        uiView.configuration.userContentController.removeScriptMessageHandler(forName: "onyxNav")
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        let model: WebViewModel
        init(model: WebViewModel) { self.model = model }

        // JS bridge: the single source of truth for the current route. Fires on
        // initial load and every SPA navigation, posting location.href — more
        // reliable than webView.url, which lags on client-side route changes.
        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "onyxNav",
                  let href = message.body as? String,
                  let url = URL(string: href) else { return }
            DispatchQueue.main.async {
                self.model.currentURL = url
                self.model.isAdminPage = url.path.hasPrefix("/admin")
            }
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            model.isLoading = true
            model.failed = false
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            model.isLoading = false
            model.didFirstLoad = true
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            handle(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            handle(error)
        }

        private func handle(_ error: Error) {
            model.isLoading = false
            if (error as NSError).code == NSURLErrorCancelled { return }
            if !model.didFirstLoad { model.failed = true }
        }

        // Open target=_blank links in the same web view instead of dropping them.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url {
                webView.load(URLRequest(url: url))
            }
            return nil
        }
    }
}
