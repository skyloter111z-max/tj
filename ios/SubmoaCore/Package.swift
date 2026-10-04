// swift-tools-version:5.9
// 아이폰 앱(ios/Submoa)이 쓰는 순수 로직. UIKit·WebKit에 의존하지 않아 리눅스에서도 `swift test`가 돈다.
import PackageDescription

let package = Package(
    name: "SubmoaCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "SubmoaCore", targets: ["SubmoaCore"])],
    targets: [
        .target(name: "SubmoaCore"),
        .testTarget(name: "SubmoaCoreTests", dependencies: ["SubmoaCore"]),
    ]
)
