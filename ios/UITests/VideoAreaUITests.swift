import XCTest

/// Exercises actual Form button dispatch, not only the crop persistence value type.
@MainActor
final class VideoAreaUITests: XCTestCase {
    func testApplyAndReopenKeepsEditedCrop() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["SKYCOMPANION_PREVIEW_ROUTE"] = "drone"
        app.launchArguments = ["-skycompanion.onboarding.completed", "YES"]
        app.launch()
        let chooseArea = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Choose video area")).firstMatch
        XCTAssertTrue(chooseArea.waitForExistence(timeout: 15), app.debugDescription)
        chooseArea.tap()
        let precise = app.buttons["Precise adjustment"]
        reveal(precise, in: app)
        precise.tap()
        let sliders = app.sliders
        XCTAssertEqual(sliders.count, 4, app.debugDescription)
        // Change actual SwiftUI sliders; resetting to full screen must remain a separate action.
        let width = sliders.element(boundBy: 2)
        reveal(width, in: app)
        width.adjust(toNormalizedSliderPosition: 0.52)
        let height = sliders.element(boundBy: 3)
        reveal(height, in: app)
        height.adjust(toNormalizedSliderPosition: 0.43)
        let summary = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", "Left ")).firstMatch
        let edited = summary.label
        XCTAssertFalse(edited.contains("Width 100%"), "Slider did not edit crop: \(edited)")
        let apply = app.buttons["Apply video area"]
        reveal(apply, in: app)
        apply.tap()
        reveal(chooseArea, in: app, up: true)
        chooseArea.tap()
        XCTAssertEqual(summary.label, edited, "Apply fired a sibling reset or reopening lost the crop")
        for _ in 0..<3 {
            chooseArea.tap()
            chooseArea.tap()
            XCTAssertEqual(summary.label, edited)
        }
        // Editing again must start from the committed rectangle.
        reveal(precise, in: app)
        if app.sliders.count == 0 { precise.tap() }
        reveal(sliders.element(boundBy: 2), in: app)
        sliders.element(boundBy: 2).adjust(toNormalizedSliderPosition: 0.63)
        let secondEdit = summary.label
        XCTAssertNotEqual(secondEdit, edited)
        reveal(apply, in: app); apply.tap()
        reveal(chooseArea, in: app, up: true); chooseArea.tap()
        XCTAssertEqual(summary.label, secondEdit)
        app.terminate(); app.launch()
        XCTAssertTrue(chooseArea.waitForExistence(timeout: 15))
        chooseArea.tap()
        XCTAssertEqual(summary.label, secondEdit, "Applied crop must also survive relaunch")
    }

    private func reveal(_ element: XCUIElement, in app: XCUIApplication, up: Bool = false) {
        for _ in 0..<8 {
            if element.isHittable { return }
            if up { app.swipeDown() } else { app.swipeUp() }
        }
        XCTAssertTrue(element.isHittable, app.debugDescription)
    }
}
