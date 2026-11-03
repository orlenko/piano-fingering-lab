import Foundation

@main struct ModelChecks {
    static func main() {
        let model = StudioModel()
        let known = NoteRow(["id": "ev_0000", "pitch": "C4", "hand": "L", "finger": "4", "tier": "low"])!
        let unknown = NoteRow(["id": "ev_0001", "pitch": "D4", "hand": "unknown", "finger": "unknown", "tier": "unknown"])!
        model.notes = [known, unknown]
        model.select(known.id)
        precondition(model.correctionHand == "L" && model.correctionFinger == "4")
        model.select(unknown.id)
        precondition(model.correctionHand.isEmpty && model.correctionFinger.isEmpty, "Unknown note must not inherit an invented correction")
        print("PASS per-note correction state")
    }
}
