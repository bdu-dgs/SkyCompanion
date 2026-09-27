#!/usr/bin/env python3
"""Exercise the production CaptureRegion persistence independently of UIKit."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / "ios/OnDevice/LocalProtocol.swift").read_text()
region = "struct CaptureRegion" + source.split("struct CaptureRegion", 1)[1].split("struct LocalCaptureSettings", 1)[0]
harness = r'''
@main struct Check {
    static func main() throws {
        let suite = "sky-area-test-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        precondition(CaptureRegion.saved(in: defaults) == nil)
        let crop = CaptureRegion(x:0.1,y:0.25,width:0.8,height:0.45)
        var selection = CaptureAreaSelection()
        selection.draft = crop
        precondition(selection.apply())
        for _ in 0..<10 {
            selection.reopen()
            precondition(selection.draft == crop && selection.applied == crop)
        }
        selection.draft = CaptureRegion() // Unapplied full-screen edit must not replace the selection.
        selection.reopen()
        precondition(selection.draft == crop)
        selection.draft = CaptureRegion(); precondition(selection.apply())
        selection.reopen(); precondition(selection.draft == CaptureRegion())
        selection.draft = crop; precondition(selection.apply())
        selection.draft.width = 2; precondition(!selection.apply())
        selection.reopen(); precondition(selection.draft == crop)
        crop.save(in: defaults)
        precondition(CaptureRegion.saved(in: UserDefaults(suiteName: suite)!) == crop)
        precondition(CaptureRegion.saved(in: defaults)!.rect == CGRect(x:0.1,y:0.25,width:0.8,height:0.45))
        var invalid = crop; invalid.width = 2; invalid.save(in: defaults)
        precondition(CaptureRegion.saved(in: defaults) == crop)
        CaptureRegion().save(in: defaults)
        precondition(CaptureRegion.saved(in: defaults) == CaptureRegion())
        defaults.set(Data("bad".utf8),forKey:"skycompanion.drone.videoArea")
        precondition(CaptureRegion.saved(in: defaults) == nil)
        defaults.set(try JSONEncoder().encode(invalid),forKey:"skycompanion.drone.videoArea")
        precondition(CaptureRegion.saved(in: defaults) == nil)
        print("PASS: 10 same-session reopens, unapplied draft discarded, explicit full-image apply, invalid apply rejected, saved crop reload, recording rectangle, invalid save, corrupt data, invalid stored data")
    }
}
'''
with tempfile.TemporaryDirectory(prefix="sky-area-persistence-") as folder:
    folder = Path(folder)
    swift = folder / "Check.swift"
    swift.write_text("import Foundation\nimport CoreGraphics\n" + region + harness)
    executable = folder / "check"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", str(swift), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
