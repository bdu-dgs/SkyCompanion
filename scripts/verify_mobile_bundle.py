#!/usr/bin/env python3
"""Check the real built app/extension contracts without disclosing pairing material."""
import argparse
import json
import plistlib
from pathlib import Path


def verify(app: Path):
    extension = app / "PlugIns/SkyCompanionBroadcast.appex"
    app_info = plistlib.loads((app / "Info.plist").read_bytes())
    extension_info = plistlib.loads((extension / "Info.plist").read_bytes())
    assert app_info["CFBundleIcons"]["CFBundlePrimaryIcon"]["CFBundleIconName"] == "AppIcon"
    assert (app / "Assets.car").is_file()
    assert (app / "LucideLicense.txt").is_file()
    assert app_info["CFBundleDisplayName"] == "SkyCompanion"
    assert extension_info["CFBundleDisplayName"] == "SkyCompanion Broadcast"
    assert extension_info["NSExtension"]["NSExtensionPrincipalClass"].endswith(".LocalSampleHandler")
    assert app_info["SkyCompanionBroadcastExtensionIdentifier"] == extension_info["CFBundleIdentifier"]
    assert not list(app.rglob("LocalCaptureConfig.json")), "Desktop configuration must not ship"
    assert "NSAppTransportSecurity" not in app_info, "Unexpected remote transport exception"
    assert (app / "selectedModel.json").read_bytes() == (extension / "selectedModel.json").read_bytes()
    assert (app / "DevicePairing.json").read_bytes() == (extension / "DevicePairing.json").read_bytes()
    assert len(json.loads((app / "DevicePairing.json").read_text())["token"]) >= 32
    manifest = json.loads((app / "selectedModel.json").read_text())
    depth = json.loads((app / "selectedDepthModel.json").read_text())
    assert (app / "selectedDepthModel.json").read_bytes() == (extension / "selectedDepthModel.json").read_bytes()
    assert depth["validationState"] == "unvalidated"

    assert len(manifest["names"]) == len(set(manifest["names"])) > 0
    assert (manifest['task'], manifest['maskChannels']) in [('detect', 0), ('segment', 32)]
    channels = 4 + len(manifest['names']) + manifest['maskChannels']
    assert any(o['shape'][:2] == [1, channels] and len(o['shape']) == 3 for o in manifest['outputs'])
    for bundle in (app, extension):
        assert (bundle / "DepthModelLicense.txt").is_file()
        depth_meta = json.loads((bundle / (depth["resourceName"]+".mlmodelc") / "metadata.json").read_text())[0]
        assert int(depth_meta["inputSchema"][0]["width"]) == depth["inputSize"]
        assert json.loads(depth_meta["outputSchema"][0]["shape"]) == depth["outputShape"]
        assert (bundle / "en.lproj/Localizable.strings").is_file(), "English copy resource missing"
        model = bundle / (manifest["resourceName"] + ".mlmodelc")
        metadata = json.loads((model / "metadata.json").read_text())[0]
        inputs = {entry["name"]: entry for entry in metadata["inputSchema"]}
        image = inputs[manifest["inputName"]]
        assert int(image["width"]) == int(image["height"]) == manifest["inputSize"]
        assert image["colorspace"] == "RGB"
        outputs = {entry["name"]: json.loads(entry["shape"]) for entry in metadata["outputSchema"]}
        for output in manifest["outputs"]:
            assert outputs[output["name"]] == output["shape"], "Model output contract mismatch"
    return {
        "app": str(app.resolve()), "bundleIdentifier": app_info["CFBundleIdentifier"],
        "minimumOSVersion": app_info["MinimumOSVersion"],
        "model": manifest["resourceName"], "classes": len(manifest['names']),
        "sourceSHA256": manifest['sourceSHA256'], "task": manifest['task'], "maskChannels": manifest['maskChannels'],
        "depthModel": depth["resourceName"], "depthValidation": depth["validationState"],
        "matchingModelAndPairingInBothTargets": True, "desktopConfigurationAbsent": True,
        "appIconAndLicenseBundled": True, "englishResourcesInBothTargets": True, "compiledModelContractsMatch": True,
        "signedProfilePresent": (app / "embedded.mobileprovision").is_file(),
        "scope": "Static checks of actual built bundles; not device execution or precision validation",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    print(json.dumps(verify(parser.parse_args().app), indent=2))
