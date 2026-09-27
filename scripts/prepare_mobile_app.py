#!/usr/bin/env python3
"""Prepare local-only runtime resources and wire the existing Xcode targets reproducibly.

No server URL or desktop pairing secret is embedded in the mobile app. Generated
credentials stay untracked. The original project is preserved once for desktop tests.
"""
import hashlib
import json
import plistlib
import re
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "ios"


def ident(name):
    return hashlib.sha256(("skycompanion-local:" + name).encode()).hexdigest()[:24].upper()


def main():
    config = IOS / "Shared/DevicePairing.json"
    if not config.exists():
        config.write_text(json.dumps({"token": secrets.token_urlsafe(32)}) + "\n")
        config.chmod(0o600)
    model_manifest = IOS / "Models/selectedModel.json"
    manifest = json.loads(model_manifest.read_text())
    model = "Models/" + manifest["resourceName"] + ".mlpackage"
    if not (IOS / model).is_dir():
        raise SystemExit("Selected Core ML package is missing. Run export_mobile_model.py first.")
    package = (IOS / model).resolve()
    if not manifest.get("files"):
        raise SystemExit("Model manifest has no package hashes.")
    for relative, expected in manifest["files"].items():
        path = (package / relative).resolve()
        if not path.is_relative_to(package) or not path.is_file():
            raise SystemExit("Invalid or missing model file: " + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit("Model hash mismatch: " + relative)
    project = IOS / "SkyCompanionCapture.xcodeproj/project.pbxproj"
    backup = IOS / "LegacyDesktop/project.pbxproj"
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        shutil.copy2(project, backup)
    text = project.read_text()
    # The marked generated blocks are replaced on repeated preparation.
    text = re.sub(r"/\* SKYCOMPANION_LOCAL_BEGIN .*?\*/.*?/\* SKYCOMPANION_LOCAL_END \*/\n", "", text, flags=re.S)
    common = ["WearerTracker.swift", "DepthEngine.swift", "PathEngine.swift", "LocalProtocol.swift", "LocalRecordingAudio.swift", "LoopbackChannel.swift", "RecoveringBroadcastChannel.swift", "LocalVisionPipeline.swift", "VisionEngine.swift"]
    app = ["RecordingAudioRelay.swift", "SpeechPCMPlayer.swift", "SkyAppearance.swift", "LocalVoiceController.swift", "LocalCommandListener.swift", "LocalSessionModel.swift", "LocalContentView.swift", "ExperimentalScreens.swift", "PhotonCompanion.swift", "CompanionScreen.swift", "NavigationController.swift", "NavigationScreen.swift"]
    extension = ["LocalSampleHandler.swift", "BroadcastMovieWriter.swift", "BroadcastRecording.swift", "RecordingAudioMixer.swift"]
    sources = ["OnDevice/" + value for value in common + app + extension]
    resources = ["SkyCompanionCapture/Assets.xcassets", "Shared/LucideLicense.txt", "Models/selectedDepthModel.json", "Models/DepthModelLicense.txt", "Shared/DevicePairing.json", "Models/selectedModel.json", "OnDevice/Localizable.xcstrings"]
    file_refs = []
    build_refs = []
    children = []
    app_sources = ["A10000000000000000000001"]  # existing @main entry, now points at SkyCompanionRootView
    extension_sources = []
    app_resources = []
    extension_resources = []
    depth_manifest = json.loads((IOS / "Models/selectedDepthModel.json").read_text())
    depth_model = "Models/" + depth_manifest["resourceName"] + ".mlpackage"
    depth_package = (IOS / depth_model).resolve()
    for relative, expected in depth_manifest["files"].items():
        path = (depth_package / relative).resolve()
        if not path.is_relative_to(depth_package) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise SystemExit("Depth model hash mismatch: " + relative)
    for path in sources + resources + [model, depth_model]:
        file_id = ident("file:" + path); children.append(file_id)
        kind = "sourcecode.swift" if path.endswith(".swift") else "folder.mlpackage" if path.endswith(".mlpackage") else "folder.assetcatalog" if path.endswith(".xcassets") else "text.json.xcstrings" if path.endswith(".xcstrings") else "text.json"
        file_refs.append(f'\t\t{file_id} = {{isa = PBXFileReference; lastKnownFileType = {kind}; path = "{path}"; sourceTree = SOURCE_ROOT; }};')
        for target in ("app", "extension"):
            filename = Path(path).name
            include = path not in sources or filename in common or filename in (app if target == "app" else extension)
            if target == "extension" and path.endswith(".xcassets"): include = False
            if not include:
                continue
            build_id = ident(target + ":" + path)
            build_refs.append(f"\t\t{build_id} = {{isa = PBXBuildFile; fileRef = {file_id}; }};")
            if path in resources:
                (app_resources if target == "app" else extension_resources).append(build_id)
            else:
                (app_sources if target == "app" else extension_sources).append(build_id)

    for name, lines in (("PBXFileReference", file_refs), ("PBXBuildFile", build_refs)):
        text = text.replace(f"/* End {name} section */", f"/* SKYCOMPANION_LOCAL_BEGIN {name} */\n" + "\n".join(lines) + f"\n/* SKYCOMPANION_LOCAL_END */\n/* End {name} section */")
    main_group = "F20000000000000000000001"
    text = re.sub(rf"({main_group} = \{{.*?children = \()(.*?)(\);)", lambda m: m[1] + m[2].rstrip() + "\n/* SKYCOMPANION_LOCAL_BEGIN children */\n" + ",\n".join(children) + ",\n/* SKYCOMPANION_LOCAL_END */\n" + m[3], text, count=1, flags=re.S)

    def files(phase, values):
        nonlocal text
        text, count = re.subn(rf"(^[ \t]*{phase} /\*[^\n]*?\*/ = \{{.*?files = \()(.*?)(\);)", lambda m: m[1]+"\n"+"".join("\t\t\t\t"+v+",\n" for v in values)+"\t\t\t"+m[3], text, count=1, flags=re.S | re.M)
        if count != 1:
            raise SystemExit("Expected exactly one build phase: " + phase)
    files("E20000000000000000000001", app_sources)
    files("E20000000000000000000002", extension_sources)
    files("E30000000000000000000001", app_resources)
    files("E30000000000000000000002", extension_resources)

    package_id = ident("package")
    package_objects = [f'{package_id} = {{isa = XCLocalSwiftPackageReference; relativePath = CaptureCore; }};']
    package_build = []
    for target, target_id, phase in (("app", "D10000000000000000000001", "E10000000000000000000001"), ("extension", "D10000000000000000000002", "E10000000000000000000002")):
        dep = ident("product:" + target); build = ident("link:" + target)
        package_objects.append(f'{dep} = {{isa = XCSwiftPackageProductDependency; package = {package_id}; productName = CaptureCore; }};')
        package_build.append(f'{build} = {{isa = PBXBuildFile; productRef = {dep}; }};')
        text = re.sub(rf'({target_id} /\*.*?\*/ = \{{.*?)(\n\t\t\tname =)', lambda m: m[1]+f'\n/* SKYCOMPANION_LOCAL_BEGIN product */\npackageProductDependencies = ({dep},);\n/* SKYCOMPANION_LOCAL_END */'+m[2], text, count=1, flags=re.S)
        files(phase, [build])
    text = text.replace("/* End PBXBuildFile section */", "/* SKYCOMPANION_LOCAL_BEGIN packagebuild */\n"+"\n".join(package_build)+"\n/* SKYCOMPANION_LOCAL_END */\n/* End PBXBuildFile section */")
    text = text.replace("/* Begin XCBuildConfiguration section */", "/* SKYCOMPANION_LOCAL_BEGIN packageobjects */\n"+"\n".join(package_objects)+"\n/* SKYCOMPANION_LOCAL_END */\n/* Begin XCBuildConfiguration section */")
    text = text.replace('projectDirPath = "";', f'projectDirPath = "";\n/* SKYCOMPANION_LOCAL_BEGIN packages */\npackageReferences = ({package_id},);\n/* SKYCOMPANION_LOCAL_END */')
    # Keep source paths/bundle IDs stable for existing development signatures and data.
    # Product names and the shared scheme are the new public brand.
    for old, new in (("SkyCompanionCapture", "SkyCompanion"), ("SkyCompanionBroadcast", "SkyCompanionBroadcast")):
        text = text.replace(f"name = {old};", f"name = {new};")
        text = text.replace(f"productName = {old};", f"productName = {new};")
        text = text.replace(old + (".app" if old == "SkyCompanionCapture" else ".appex"), new + (".app" if old == "SkyCompanionCapture" else ".appex"))
    text = re.sub(r"(?:ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;\s*)?INFOPLIST_FILE = SkyCompanionCapture/Info.plist;", "ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon; INFOPLIST_FILE = SkyCompanionCapture/Info.plist;", text)
    project.write_text(text)
    schemes = IOS / "SkyCompanionCapture.xcodeproj/xcshareddata/xcschemes"
    scheme = schemes / "SkyCompanion.xcscheme"
    old_scheme = schemes / "SkyCompanionCapture.xcscheme"
    if not scheme.exists():
        shutil.copy2(old_scheme, backup.parent / "SkyCompanionCapture.xcscheme")
        old_scheme.rename(scheme)
    scheme.write_text(scheme.read_text().replace('BuildableName="SkyCompanionCapture.app"', 'BuildableName="SkyCompanion.app"')
                      .replace('BlueprintName="SkyCompanionCapture"', 'BlueprintName="SkyCompanion"'))
    entry = IOS / "SkyCompanionCapture/SkyCompanionCaptureApp.swift"
    entry.write_text(re.sub(r"\b(?:LocalContentView|ContentView)\(\)", "SkyCompanionRootView()", entry.read_text()))
    for target in ("SkyCompanionCapture", "SkyCompanionBroadcast"):
        path = IOS / target / "Info.plist"
        info = plistlib.loads(path.read_bytes())
        info.pop("NSLocalNetworkUsageDescription", None)
        info.pop("NSAppTransportSecurity", None)
        if target == "SkyCompanionCapture":
            info["CFBundleDisplayName"] = "SkyCompanion"
            info["NSLocationWhenInUseUsageDescription"] = "SkyCompanion uses your location for walking routes and short turn cues, including while a route continues in the background."
            info["UIBackgroundModes"] = list(dict.fromkeys(info.get("UIBackgroundModes", []) + ["location"]))
            for key in ("NSMicrophoneUsageDescription", "NSSpeechRecognitionUsageDescription"):
                info[key] = info[key].replace("SkyCompanion", "SkyCompanion")
        else:
            info["CFBundleDisplayName"] = "SkyCompanion Broadcast"
            info["NSExtension"]["NSExtensionPrincipalClass"] = "$(PRODUCT_MODULE_NAME).LocalSampleHandler"
        path.write_bytes(plistlib.dumps(info, sort_keys=False))
    ignore = ROOT / ".gitignore"
    text = ignore.read_text()
    for line in [".venv-mobile-export/", "ios/Shared/DevicePairing.json", "ios/Models/*.mlpackage/", "ios/Models/*.mlmodelc/"]:
        if line not in text.splitlines():
            text += "\n" + line
    ignore.write_text(text.rstrip()+"\n")
    print("Prepared local-only targets with " + manifest["resourceName"] + ". Pairing secret was not printed.")


if __name__ == "__main__":
    main()
