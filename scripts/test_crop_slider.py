#!/usr/bin/env python3
"""Render the production crop slider offscreen; requires macOS SwiftUI/AppKit."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "ios/OnDevice/LocalContentView.swift").read_text()
view = source.split("private struct CropSlider: View", 1)[1].split("private struct CalibrationPreview", 1)[0]
harness = '\nimport AppKit\n@main struct CropSliderRegression {\n    @MainActor static func main() {\n        _ = NSApplication.shared\n        let cases: [(Double, ClosedRange<Double>)] = [\n            (0,0...0), (0.06,0.06...0.06), (0,0...0.000001),\n            (0.06,0.06...0.061), (0.2,0...0.5), (1,0.06...1)\n        ]\n        for (value, bounds) in cases {\n            let view = CropSlider(title: "Crop regression", value: .constant(value), range: bounds)\n            let host = NSHostingView(rootView: view)\n            host.frame = CGRect(x:0,y:0,width:320,height:120)\n            host.layoutSubtreeIfNeeded()\n            _ = host.fittingSize\n            print("PASS native SwiftUI crop slider range \\(bounds)")\n        }\n    }\n}\n'
with tempfile.TemporaryDirectory(prefix="sky-crop-slider-") as folder:
    path = Path(folder)
    swift = path / "Regression.swift"
    swift.write_text("import SwiftUI\nprivate struct CropSlider: View" + view + harness)
    executable = path / "regression"
    subprocess.run(["xcrun", "swiftc", "-parse-as-library", str(swift), "-o", str(executable),
                    "-module-cache-path", str(path / "cache")], check=True)
    subprocess.run([str(executable)], check=True)
