import SwiftUI

@main
struct SubmoaApp: App {
    var body: some Scene {
        WindowGroup {
            WebView()
                .ignoresSafeArea(edges: .bottom)
                .background(Color.black)
        }
    }
}

/// 화면은 웹 앱 그대로다. 해석·판정 로직도 웹 쪽 TypeScript 하나뿐이다.
struct WebView: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> WebViewController { WebViewController() }
    func updateUIViewController(_ controller: WebViewController, context: Context) {}
}
