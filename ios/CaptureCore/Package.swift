// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "CaptureCore",
    products: [.library(name: "CaptureCore", targets: ["CaptureCore"])],
    targets: [
        .target(name: "CaptureCore"),
        .testTarget(name: "CaptureCoreTests", dependencies: ["CaptureCore"])
    ]
)
