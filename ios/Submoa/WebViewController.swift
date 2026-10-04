import SubmoaCore
import UIKit
import WebKit

/// 번들에 넣은 웹 앱을 띄우고, 쌓인 결제 알림을 `window.SubmoaBridge`로 건넨다.
///
/// 안드로이드는 JS가 네이티브를 동기 호출할 수 있지만 WKWebView는 안 된다. 그래서 알림 목록을
/// 페이지에 미리 심어 두고(`__submoaAlerts`), 앱이 다시 앞으로 올 때마다 갱신한 뒤
/// `submoa:resume`을 쏜다 — 웹(lib/card-alerts/bridge.ts)은 두 플랫폼을 같은 모양으로 본다.
final class WebViewController: UIViewController, WKNavigationDelegate, WKScriptMessageHandler {
    private var webView: WKWebView!
    private var activeObserver: NSObjectProtocol?

    private static let bridgeScript = """
    window.SubmoaBridge = {
      platform: function () { return "ios"; },
      isAccessGranted: function () { return window.__submoaGranted === true; },
      openAccessSettings: function () { window.webkit.messageHandlers.submoa.postMessage("openShortcuts"); },
      getAlerts: function () { return JSON.stringify(window.__submoaAlerts || []); }
    };
    """

    override func loadView() {
        let config = WKWebViewConfiguration()
        config.setURLSchemeHandler(BundleSchemeHandler(), forURLScheme: WebAssets.scheme)
        config.userContentController.add(WeakMessageHandler(self), name: "submoa")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.isOpaque = false
        webView.backgroundColor = .black
        installUserScripts()
        view = webView
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        webView.load(URLRequest(url: WebAssets.startURL))
        // 단축어 앱에서 자동화를 만들고 돌아온 순간, 새로 쌓인 알림을 웹에 넘긴다
        activeObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main
        ) { [weak self] _ in self?.refreshBridge() }
    }

    deinit {
        if let observer = activeObserver { NotificationCenter.default.removeObserver(observer) }
    }

    /// 지금 저장된 알림. 하나라도 있으면 자동화가 동작한다는 증거라 "허용됨"으로 본다
    private func stateScript() -> String {
        let store = AlertStore.shared
        let granted = !store.all().isEmpty
        return "window.__submoaAlerts = \(store.json()); window.__submoaGranted = \(granted);"
    }

    /// 페이지가 새로 열릴 때마다 브리지와 최신 상태를 문서 맨 앞에 심는다
    private func installUserScripts() {
        let controller = webView.configuration.userContentController
        controller.removeAllUserScripts()
        for source in [Self.bridgeScript, stateScript()] {
            controller.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        }
    }

    private func refreshBridge() {
        installUserScripts()
        webView.evaluateJavaScript(stateScript() + " window.dispatchEvent(new Event('submoa:resume'));")
    }

    // MARK: WKScriptMessageHandler

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, message.body as? String == "openShortcuts",
              let url = URL(string: "shortcuts://") else { return }
        UIApplication.shared.open(url)
    }

    // MARK: WKNavigationDelegate

    /// 브리지는 결제 알림을 내준다. 우리 웹 앱이 아닌 페이지는 이 WebView에서 열지 않는다.
    func webView(
        _ webView: WKWebView,
        decidePolicyFor action: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = action.request.url else { return decisionHandler(.cancel) }
        if url.scheme == WebAssets.scheme { return decisionHandler(.allow) }
        UIApplication.shared.open(url)
        decisionHandler(.cancel)
    }
}

/// `submoa://app/...` 요청을 번들 web/ 폴더의 파일로 답한다 (WebAssets 경로 규칙)
final class BundleSchemeHandler: NSObject, WKURLSchemeHandler {
    private let root = Bundle.main.resourceURL!.appendingPathComponent("web")

    func webView(_ webView: WKWebView, start task: WKURLSchemeTask) {
        guard let url = task.request.url, !url.path.contains("..") else {
            return task.didFailWithError(URLError(.badURL))
        }
        for file in WebAssets.candidates(url.path) {
            guard let data = try? Data(contentsOf: root.appendingPathComponent(file)) else { continue }
            let headers = [
                "Content-Type": "\(WebAssets.mimeType(file)); charset=utf-8",
                "Content-Length": "\(data.count)",
            ]
            task.didReceive(HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1", headerFields: headers)!)
            task.didReceive(data)
            task.didFinish()
            return
        }
        task.didFailWithError(URLError(.fileDoesNotExist))
    }

    func webView(_ webView: WKWebView, stop task: WKURLSchemeTask) {}
}

/// WKUserContentController는 핸들러를 강하게 붙잡는다. 컨트롤러가 해제되도록 약한 참조로 감싼다.
private final class WeakMessageHandler: NSObject, WKScriptMessageHandler {
    private weak var target: WKScriptMessageHandler?

    init(_ target: WKScriptMessageHandler) {
        self.target = target
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        target?.userContentController(controller, didReceive: message)
    }
}
