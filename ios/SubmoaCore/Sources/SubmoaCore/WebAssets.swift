import Foundation

/// 앱 번들에 넣은 웹 앱(`npm run export` 결과)을 `submoa://app/...`으로 서빙할 때의 경로 규칙.
/// 안드로이드 `WebAssets.kt`와 같다.
///
/// Next 정적 내보내기는 `/onboarding`을 `onboarding.html`로, `/`를 `index.html`로 만든다.
public enum WebAssets {
    public static let scheme = "submoa"
    /// 홈. 단축어 설정을 마치지 않았으면 웹이 온보딩으로 보낸다
    public static let startURL = URL(string: "submoa://app/")!

    /// 요청 경로 → 번들 web/ 아래에서 찾아볼 파일 후보 (순서대로)
    public static func candidates(_ path: String) -> [String] {
        let p = path.drop { $0 == "/" }
        if p.isEmpty || p.hasSuffix("/") { return ["\(p)index.html"] }
        let last = p.split(separator: "/").last ?? ""
        return last.contains(".") ? [String(p)] : ["\(p).html", "\(p)/index.html"]
    }

    public static func mimeType(_ file: String) -> String {
        switch (file as NSString).pathExtension.lowercased() {
        case "html": return "text/html"
        case "js": return "text/javascript"
        case "css": return "text/css"
        case "json": return "application/json"
        case "txt": return "text/plain" // Next 클라이언트 이동 때 받는 RSC 조각
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "ico": return "image/x-icon"
        case "woff2": return "font/woff2"
        default: return "application/octet-stream"
        }
    }
}
