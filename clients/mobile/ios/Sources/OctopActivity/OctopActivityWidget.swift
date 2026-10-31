import ActivityKit
import SwiftUI
import WidgetKit

@main
struct OctopActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: OctopActivityAttributes.self) { context in
            HStack(spacing: 12) {
                Image(systemName: icon(context.state.status))
                VStack(alignment: .leading) {
                    Text(context.attributes.agentName).font(.headline)
                    Text(label(context.state.status, locale: context.state.locale ?? context.attributes.locale)).font(.caption)
                }
                Spacer()
                if context.state.status == "working" { ProgressView() }
                if ["working", "paused"].contains(context.state.status), let navigation = context.attributes.actionNavigation,
                   let device = context.attributes.deviceID,
                   let url = URL(string: "octop-mobile://task-action/\(context.attributes.serverFingerprint)/\(device)/\(navigation)") {
                    Link(L("native_review_cancel"), destination: url).font(.caption)
                }
            }
            .padding()
            .activityBackgroundTint(Color.black.opacity(0.85))
            .activitySystemActionForegroundColor(.white)
            .widgetURL(URL(string: "octop-mobile://activity/\(context.attributes.serverFingerprint)/\(context.attributes.agentID)/\(context.attributes.threadID)?device=\(context.attributes.deviceID ?? "")"))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { Image(systemName: "bubble.left.and.bubble.right.fill") }
                DynamicIslandExpandedRegion(.trailing) { Text(label(context.state.status, locale: context.state.locale ?? context.attributes.locale)).font(.caption) }
                DynamicIslandExpandedRegion(.bottom) { Text(context.attributes.agentName).font(.headline) }
            } compactLeading: { Image(systemName: "bubble.left.fill") }
              compactTrailing: { Image(systemName: icon(context.state.status)) }
              minimal: { Image(systemName: "bubble.left.fill") }
        }
    }
    private func icon(_ status: String) -> String {
        switch status {
        case "working": return "ellipsis.bubble.fill"
        case "approval": return "questionmark.bubble.fill"
        case "paused": return "pause.circle.fill"
        case "failed": return "exclamationmark.bubble.fill"
        default: return "checkmark.bubble.fill"
        }
    }
    private func label(_ status: String, locale: String) -> String {
        switch status {
        case "working": return L("native_working", locale: locale)
        case "approval": return L("native_approval_needed", locale: locale)
        case "failed": return L("native_failed_or_interrupted", locale: locale)
        case "paused": return L("native_paused", locale: locale)
        default: return L("native_complete", locale: locale)
        }
    }
}
