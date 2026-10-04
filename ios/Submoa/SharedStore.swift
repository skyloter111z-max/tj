import Foundation
import SubmoaCore

extension AlertStore {
    /// 화면과 단축어 동작(SaveCardAlertIntent)이 함께 쓰는 저장소. 앱 컨테이너 밖으로 나가지 않는다.
    static let shared: AlertStore = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return AlertStore(url: dir.appendingPathComponent("card-alerts.jsonl"))
    }()
}
