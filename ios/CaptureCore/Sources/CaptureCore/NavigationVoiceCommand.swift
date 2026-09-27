import Foundation

/// Navigation commands require the mobile wake phrase at the start of the utterance.
/// Destinations retain their original spelling, numbers, and internal punctuation for map search.
public enum NavigationVoiceCommand: Equatable, Sendable {
    case destination(String)
    case cancel
    /// One-based index into the currently spoken search choices.
    case select(Int)
    case status

    public static func parse(_ transcript: String) -> Self? {
        let pattern = #"^\s*sky(?:companion|\s+companion)(?=$|[^\p{L}\p{N}])[^\p{L}\p{N}]*"#
        guard let wake = transcript.range(of: pattern, options: [.regularExpression, .caseInsensitive]) else { return nil }
        let body = String(transcript[wake.upperBound...])
        let words = body.lowercased().components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }.joined(separator: " ")
        switch words {
        case "cancel navigation", "stop navigation", "end navigation": return .cancel
        case "navigation status", "route status": return .status
        default: break
        }
        let numbers = ["one": 1, "two": 2, "three": 3, "1": 1, "2": 2, "3": 3]
        for prefix in ["option ", "choose ", "choose option ", "select ", "select option "] {
            if words.hasPrefix(prefix), let index = numbers[String(words.dropFirst(prefix.count))] {
                return .select(index)
            }
        }
        let destinationPrefix = #"^(?:navigate\s+to|take\s+me\s+to|directions\s+to)\s+"#
        guard let prefix = body.range(of: destinationPrefix, options: [.regularExpression, .caseInsensitive]) else { return nil }
        let destination = String(body[prefix.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: ".,!?")))
        guard destination.unicodeScalars.contains(where: { CharacterSet.alphanumerics.contains($0) }) else { return nil }
        return .destination(destination)
    }
}
