import ActivityKit

struct OctopActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var status: String
        var updatedAt: Int
        var locale: String? = nil
    }
    var serverFingerprint: String
    var agentID: String
    var threadID: String
    var agentName: String
    var locale: String
    var deviceID: String? = nil
    var actionNavigation: String? = nil
}
