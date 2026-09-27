import Foundation

/// Mobile commands are explicit whole utterances. Existing desktop command behavior stays separate.
public enum MobileVoiceCommand: String, Sendable {
    case repeatAlert = "repeat", mute, unmute, describe, stop, explain, acknowledge, quiet, normal
    case reportFalseAlert = "report_false_alert"
    case pause, resume, end, path, status
    case agentSummary = "agent_summary", agentWhy = "agent_why"

    public static func parse(_ transcript: String) -> Self? {
        let words = transcript.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
        let commandWords: ArraySlice<String>
        if words.first == "skycompanion" {
            commandWords = words.dropFirst()
        } else if words.count >= 2, words[0] == "sky", words[1] == "companion" {
            commandWords = words.dropFirst(2)
        } else {
            return nil
        }
        let command = commandWords.joined(separator: " ")
        let local: [String: Self] = ["status": .status, "are you working": .status, "is it working": .status, "can i rely on alerts": .status, "resume alerts": .unmute, "path": .path, "path status": .path, "pause": .pause, "pause analysis": .pause,
                                   "resume": .resume, "resume analysis": .resume,
                                   "end assistance": .end, "end session": .end,
                                   "trip summary": .agentSummary, "ask assistant why": .agentWhy]
        if let result = local[command] { return result }
        // Reuse the shared action grammar only after validating the mobile wake phrase.
        return VoiceCommand.parse("skycompanion " + command).flatMap { Self(rawValue: $0.rawValue) }
    }
}
